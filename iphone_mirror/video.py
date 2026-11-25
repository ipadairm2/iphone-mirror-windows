"""Screen-mirroring video: TCP stream parsing, AES-CTR decryption, HW/SW H.264/HEVC decoding."""
import asyncio
import collections
import hashlib
import logging
import queue
import struct
import threading
import time
from fractions import Fraction

import av
import numpy as np
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from . import net
from .stream_ops import (
    avcc_to_annexb,
    decrypt_mirror_nal,
    parse_avcc_config,
    visible_size as _visible_size_pair,
)

log = logging.getLogger(__name__)

START = b"\x00\x00\x00\x01"
_HW_DECODERS = {
    "h264": ("h264_cuvid", "h264_qsv"),
    "hevc": ("hevc_cuvid", "hevc_qsv"),
}


def mirror_key_iv(aeskey: bytes, stream_connection_id: int) -> tuple[bytes, bytes]:
    """Derive 16-byte AES-128-CTR key and IV for the mirror stream."""
    skey = f"AirPlayStreamKey{stream_connection_id}".encode()
    siv = f"AirPlayStreamIV{stream_connection_id}".encode()
    key = hashlib.sha512(skey + aeskey).digest()[:16]
    iv = hashlib.sha512(siv + aeskey).digest()[:16]
    return key, iv


def mirror_cipher(aeskey: bytes, stream_connection_id: int):
    """AES-128-CTR decryptor for the mirror stream (key/iv derived like the receiver)."""
    key, iv = mirror_key_iv(aeskey, stream_connection_id)
    return Cipher(algorithms.AES(key), modes.CTR(iv))


def visible_size(frame_w: int, frame_h: int, visible) -> tuple[int, int]:
    """Drop encoder padding. Ignore a size that is not the same picture."""
    if not visible:
        return int(frame_w), int(frame_h)
    return _visible_size_pair(int(frame_w), int(frame_h), int(visible[0]), int(visible[1]))


class VideoDecoder(threading.Thread):
    """Decodes Annex-B access units; hands the newest frame (BGRA ndarray) to on_frame."""

    def __init__(self, on_frame, codec="h264", hw_decode=False, on_raw_frame=None):
        super().__init__(name="video-decoder", daemon=True)
        self.on_frame = on_frame
        self.codec_name = codec  # "h264" for AirPlay, "hevc" for USB picture
        self.hw_decode = bool(hw_decode)
        self.on_raw_frame = on_raw_frame
        self.extradata = None  # optional HEVC hvcC record
        self.visible = None  # (w, h) real screen; HEVC frame can be padded on right/bottom
        self.q = queue.Queue(maxsize=240)
        self.target = None  # (w, h) in device pixels, set by the UI
        self.last_frame = None  # full-resolution av.VideoFrame (for screenshots)
        self.active_codec = codec
        self.hw_active = False
        self.decode_ms = 0.0
        self.dropped_frames = 0
        self._codec = None
        self._stopped = False
        self._announced = False
        self._crop_logged = False
        self._last_deliver = 0.0
        self._scale_graph = None
        self._scale_key = None
        self._scale_src = None
        self._scale_sink = None
        self._scale_bad = None
        self._epoch = 0  # discard() bumps this so a packet already taken is not painted
        self._hw_failed = False
        self._hw_empty_runs = 0
        self._hw_got_frame = False
        self._hw_probe_packets: list[bytes] = []
        self._sw_err_logged = 0
        self._cached_config = None

    def submit(self, data: bytes | None):
        try:
            self.q.put_nowait(data)
        except queue.Full:
            self.dropped_frames += 1
            log.warning("decoder queue full, dropping frame")

    def set_codec_config(self, config: bytes | None):
        self._cached_config = config

    def set_hw_decode(self, enabled: bool):
        enabled = bool(enabled)
        if enabled != self.hw_decode:
            self.hw_decode = enabled
            self._hw_failed = False
            self._hw_empty_runs = 0
            self._hw_got_frame = False
            self._hw_probe_packets.clear()
            self._sw_err_logged = 0
            self.reset()

    def reset(self):
        self._hw_empty_runs = 0
        self.submit(None)

    def discard(self):
        """Drop packets still queued. A closed stream must not paint another frame."""
        self._epoch += 1
        self._cached_config = None
        self._announced = False
        self._hw_got_frame = False
        self._hw_empty_runs = 0
        self._hw_probe_packets.clear()
        self._sw_err_logged = 0
        while True:
            try:
                self.q.get_nowait()
            except queue.Empty:
                break

    def stop(self):
        self._stopped = True
        self.submit(b"")

    def _codec_candidates(self) -> tuple[str, ...]:
        if self.hw_decode and not self._hw_failed:
            return _HW_DECODERS.get(self.codec_name, ()) + (self.codec_name,)
        return (self.codec_name,)

    def _new_codec(self):
        last_err = None
        for name in self._codec_candidates():
            try:
                c = av.CodecContext.create(name, "r")
                if name == self.codec_name:
                    try:
                        c.thread_type = "SLICE"  # no frame-threading delay
                    except Exception:
                        pass
                try:
                    c.options = {"flags": "low_delay"}
                except Exception:
                    pass
                if self.extradata:
                    c.extradata = self.extradata
                if name != self.codec_name:
                    c.open()
                self.active_codec = name
                self.hw_active = name != self.codec_name
                self._hw_empty_runs = 0
                log.info("video decoder initialized: %s (hw=%s)", name, self.hw_active)
                return c
            except Exception as e:
                last_err = e
                log.debug("decoder %s unavailable: %s", name, e)
        raise last_err or RuntimeError(f"no decoder available for {self.codec_name}")

    def _fallback_to_software(self, packet_data: bytes, reason: str = ""):
        log.warning(
            "hardware decoder %s failed (%s), falling back to software %s",
            self.active_codec,
            reason or "unknown error",
            self.codec_name,
        )
        self._hw_failed = True
        self._hw_empty_runs = 0
        self._hw_got_frame = False
        replay = list(self._hw_probe_packets)
        self._hw_probe_packets.clear()
        if not replay or replay[-1] is not packet_data:
            replay.append(packet_data)
        self._codec = self._new_codec()
        frames = []
        if self._cached_config and not replay[0].startswith(self._cached_config):
            try:
                frames.extend(self._codec.decode(av.Packet(self._cached_config)))
            except av.error.FFmpegError:
                pass
        for idx, pkt in enumerate(replay):
            try:
                frames.extend(self._codec.decode(av.Packet(pkt)))
            except av.error.FFmpegError as e:
                if self._sw_err_logged < 3:
                    self._sw_err_logged += 1
                    log.warning("software fallback decode error on packet %d: %s", idx, e)
                else:
                    log.debug("software fallback decode error on packet %d: %s", idx, e)
        return frames

    def run(self):
        while not self._stopped:
            epoch = self._epoch
            data = self.q.get()
            if self._stopped:
                break
            if epoch != self._epoch:
                continue
            if data is None:
                self._codec = None
                self._hw_got_frame = False
                self._hw_empty_runs = 0
                self._hw_probe_packets.clear()
                self._sw_err_logged = 0
                continue
            if not data:
                continue
            if self._codec is None:
                self._codec = self._new_codec()

            if self.hw_active and not self._hw_got_frame and len(self._hw_probe_packets) < 64:
                self._hw_probe_packets.append(data)

            t0 = time.perf_counter()
            try:
                frames = self._codec.decode(av.Packet(data))
            except av.error.FFmpegError as e:
                if self.hw_active:
                    frames = self._fallback_to_software(data, reason=str(e))
                else:
                    if self._sw_err_logged < 3:
                        self._sw_err_logged += 1
                        log.warning("decode error (%s): %s", self.active_codec, e)
                    else:
                        log.debug("decode error (%s): %s", self.active_codec, e)
                    continue

            if not frames:
                if self.hw_active:
                    self._hw_empty_runs += 1
                    if self._hw_empty_runs >= 12:
                        frames = self._fallback_to_software(
                            data, reason=f"no output after {self._hw_empty_runs} packets"
                        )
                if not frames:
                    continue
            else:
                self._hw_empty_runs = 0
                if not self._hw_got_frame:
                    self._hw_got_frame = True
                    self._hw_probe_packets.clear()

            # Drop a frame only when a newer one is already waiting and we just painted.
            if epoch != self._epoch:
                continue
            if not self.q.empty() and time.monotonic() - self._last_deliver < 0.008:
                self.dropped_frames += 1
                continue
            frame = frames[-1]
            try:
                if epoch != self._epoch:
                    continue
                self._deliver(frame)
                elapsed_ms = (time.perf_counter() - t0) * 1000.0
                self.decode_ms = elapsed_ms if self.decode_ms == 0.0 else (self.decode_ms * 0.8 + elapsed_ms * 0.2)
            except Exception:
                log.exception("frame conversion failed")

    def _deliver(self, frame):
        self.last_frame = frame
        if self.on_raw_frame is not None:
            try:
                self.on_raw_frame(frame)
            except Exception:
                log.exception("raw frame hook failed")
        if not self._announced:
            self._announced = True
            log.info("first frame %dx%d (%s)", frame.width, frame.height, self.active_codec)
        self._last_deliver = time.monotonic()
        vw, vh = visible_size(frame.width, frame.height, self.visible)
        tw, th = self.target or (vw, vh)
        tw, th = max(16, int(tw)), max(16, int(th))
        # keep the source aspect if the UI has not adapted yet
        if abs(tw / th - vw / vh) > 0.02:
            th = max(16, round(tw * vh / vw))
        if (vw, vh) != (frame.width, frame.height) and not self._crop_logged:
            self._crop_logged = True
            log.info("cropping frame %dx%d to %dx%d", frame.width, frame.height, vw, vh)
        try:
            img = self._scale(frame, vw, vh, tw, th)
        except Exception:
            log.exception("fast scale failed")
            self._scale_bad = (frame.width, frame.height, frame.format.name, vw, vh, tw, th)
            self._scale_key = None
            img = self._scale_slow(frame, vw, vh, tw, th)
        self.on_frame(img, vw, vh)

    def _scale(self, frame, vw, vh, tw, th):
        """Crop, then one scale. full_chroma_int keeps the gray dashes off the left edge."""
        key = (frame.width, frame.height, frame.format.name, vw, vh, tw, th)
        if key == self._scale_bad:
            return self._scale_slow(frame, vw, vh, tw, th)
        if key != self._scale_key:
            graph = av.filter.Graph()
            src = graph.add_buffer(template=frame, time_base=frame.time_base or Fraction(1, 1000))
            nodes = [src]
            if (vw, vh) != (frame.width, frame.height):
                nodes.append(graph.add("crop", f"{int(vw)}:{int(vh)}:0:0"))
            nodes.append(graph.add("scale", f"{int(tw)}:{int(th)}:flags=area+accurate_rnd+full_chroma_int"))
            nodes.append(graph.add("format", "bgra"))
            sink = graph.add("buffersink")
            nodes.append(sink)
            graph.link_nodes(*nodes)
            graph.configure()
            self._scale_graph = graph
            self._scale_src = src
            self._scale_sink = sink
            self._scale_key = key
        self._scale_src.push(frame)
        return np.ascontiguousarray(self._scale_sink.pull().to_ndarray())

    def _scale_slow(self, frame, vw, vh, tw, th):
        """Cut to the real screen before scaling. Scaling the pad leaves dashes."""
        if (vw, vh) != (frame.width, frame.height):
            raw = frame.reformat(format="bgra").to_ndarray()
            cropped = np.ascontiguousarray(raw[:vh, :vw])
            img = (
                av.VideoFrame.from_ndarray(cropped, format="bgra")
                .reformat(width=tw, height=th, format="bgra", interpolation="AREA")
                .to_ndarray()
            )
        else:
            img = frame.reformat(width=tw, height=th, format="bgra", interpolation="AREA").to_ndarray()
        return np.ascontiguousarray(img)


class MirrorStream:
    """Accepts the iPhone's mirror TCP connection and feeds the decoder."""

    def __init__(self, aeskey: bytes, stream_connection_id: int, decoder: VideoDecoder, events):
        self._video_key, self._video_iv = mirror_key_iv(aeskey, stream_connection_id)
        self._stream_offset = 0
        self.decoder = decoder
        self.events = events  # callable(event: str, **info)
        self.server = None
        self.port = 0
        self._writer = None
        self._sps_pps = None
        self._checked = False
        self._bad = 0
        self._task = None
        self.frames = 0
        self._bw_samples = collections.deque()

    @property
    def bitrate_kbps(self) -> float:
        now = time.monotonic()
        while self._bw_samples and now - self._bw_samples[0][0] > 2.0:
            self._bw_samples.popleft()
        if not self._bw_samples:
            return 0.0
        total_bytes = sum(b for _, b in self._bw_samples)
        span = max(0.25, now - self._bw_samples[0][0])
        return round((total_bytes * 8.0) / (span * 1000.0), 1)

    async def start(self) -> int:
        self.server = await asyncio.start_server(self._handle, host=net.BIND_HOST, port=0)
        self.port = self.server.sockets[0].getsockname()[1]
        log.info("mirror data port %d", self.port)
        return self.port

    async def stop(self):
        writer = self._writer
        if writer is not None:
            transport = getattr(writer, "transport", None)
            try:
                writer.close()
            except Exception:
                pass
            if transport is not None:
                try:
                    transport.abort()
                except Exception:
                    pass
        server = self.server
        self.server = None
        if server is not None:
            server.close()
        task = self._task
        self._task = None
        if task is not None and task is not asyncio.current_task() and not task.done():
            task.cancel()
            try:
                await asyncio.wait_for(task, timeout=1)
            except (asyncio.CancelledError, asyncio.TimeoutError):
                pass
        if server is not None:
            try:
                await asyncio.wait_for(server.wait_closed(), timeout=1)
            except (asyncio.TimeoutError, Exception):
                pass

    async def _handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        self._task = asyncio.current_task()
        self._writer = writer
        peer = writer.get_extra_info("peername")
        log.info("mirror stream connected from %s", peer)
        sock = writer.get_extra_info("socket")
        try:
            import socket as _s

            # A multi-megabyte buffer lets old video pile up and the picture falls behind.
            sock.setsockopt(_s.SOL_SOCKET, _s.SO_RCVBUF, 256 * 1024)
        except Exception:
            pass
        self.decoder.reset()
        try:
            while True:
                hdr = await reader.readexactly(128)
                size = struct.unpack_from("<I", hdr, 0)[0]
                payload = await reader.readexactly(size) if size else b""
                self._packet(hdr, payload)
        except (asyncio.IncompleteReadError, ConnectionError):
            log.info("mirror stream closed")
        except asyncio.CancelledError:
            pass
        except Exception:
            log.exception("mirror stream error")
        finally:
            self._writer = None
            try:
                writer.close()
            except Exception:
                pass
            self.decoder.discard()
            self.events("mirror_stopped")

    def _packet(self, hdr: bytes, payload: bytes):
        ptype = hdr[4]
        if ptype == 0:  # encrypted video access unit
            nal = decrypt_mirror_nal(self._video_key, self._video_iv, self._stream_offset, payload)
            self._stream_offset += len(payload)
            self._bw_samples.append((time.monotonic(), len(payload)))
            if nal is None:
                self._bad += 1
                if not self._checked:
                    self._checked = True
                    log.error("first video packet failed to decrypt into valid H.264 (key mismatch?)")
                    self.events("decrypt_error")
                return
            if not self._checked:
                self._checked = True
                log.info("video decryption OK")
            if self._sps_pps:
                nal = self._sps_pps + nal
                self._sps_pps = None
            self.frames += 1
            self.decoder.submit(nal)
        elif ptype == 1:  # unencrypted codec config (SPS + PPS)
            if payload[4:8] == b"hvc1":
                log.error("client sent H.265, which is not supported")
                return
            cfg = parse_avcc_config(payload)
            if cfg is None:
                log.warning("malformed AVCC codec config (%d bytes)", len(payload))
                return
            self._sps_pps = cfg
            self.decoder.set_codec_config(cfg)
            w, h = struct.unpack_from("<ff", hdr, 56)
            sw, sh = struct.unpack_from("<ff", hdr, 40)
            log.info("codec config: video %dx%d (source %dx%d) option %02x", w, h, sw, sh, hdr[6])
            if hdr[6] in (0x56, 0x5E):
                self.events("paused")
            else:
                self.events("format", width=int(w), height=int(h))
        # 2 = heartbeat (old protocol), 5 = streaming report: nothing to do
