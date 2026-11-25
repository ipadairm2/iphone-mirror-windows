"""Live MP4 screen recorder with hardware H.264 encoding fallback and AAC audio."""
from fractions import Fraction
import logging
import queue
import threading
import time
from pathlib import Path

import av
import numpy as np

log = logging.getLogger(__name__)

_VIDEO_TIME_BASE = Fraction(1, 90_000)
_ENCODER_CANDIDATES = (
    ("h264_nvenc", "yuv420p"),
    ("h264_amf", "yuv420p"),
    ("h264_qsv", "nv12"),
    ("libx264", "yuv420p"),
    ("mpeg4", "yuv420p"),
)


def default_recordings_dir() -> Path:
    return Path.home() / "Videos" / "iPhone Mirror"


def _probe_video_encoder(width: int, height: int, fps: int) -> tuple[str, str]:
    """Return the first H.264/MP4 encoder that opens and encodes a test frame."""
    for codec_name, pix_fmt in _ENCODER_CANDIDATES:
        try:
            cc = av.CodecContext.create(codec_name, "w")
            cc.width = width
            cc.height = height
            cc.pix_fmt = pix_fmt
            cc.time_base = Fraction(1, max(1, fps))
            cc.bit_rate = 8_000_000
            if codec_name == "libx264":
                cc.options = {"preset": "veryfast"}
            cc.open()
            probe = av.VideoFrame(width, height, pix_fmt)
            probe.pts = 0
            list(cc.encode(probe))
            return codec_name, pix_fmt
        except Exception as exc:
            log.debug("recorder probe %s (%s) unavailable: %s", codec_name, pix_fmt, exc)
    raise RuntimeError("No usable video encoder available in FFmpeg/PyAV")


def _to_video_frame(frame_or_arr, enc_w: int, enc_h: int, pix_fmt: str) -> av.VideoFrame:
    """Convert raw av.VideoFrame or ndarray into enc_w x enc_h in target pixel format."""
    if isinstance(frame_or_arr, av.VideoFrame):
        vf = frame_or_arr
    else:
        arr = np.asarray(frame_or_arr, dtype=np.uint8)
        if arr.ndim != 3 or arr.shape[2] not in (3, 4):
            raise ValueError(f"unsupported frame shape {arr.shape}")
        fmt = "bgra" if arr.shape[2] == 4 else "rgb24"
        vf = av.VideoFrame.from_ndarray(np.ascontiguousarray(arr), format=fmt)

    src_w, src_h = vf.width, vf.height
    if abs(src_w - enc_w) <= 2 and abs(src_h - enc_h) <= 2:
        if vf.width == enc_w and vf.height == enc_h and vf.format.name == pix_fmt:
            return vf
        return vf.reformat(width=enc_w, height=enc_h, format=pix_fmt)

    # Preserve aspect ratio (e.g., portrait <-> landscape rotation mid-recording).
    scale = min(enc_w / max(1, src_w), enc_h / max(1, src_h))
    rw = max(2, int(round(src_w * scale)) & ~1)
    rh = max(2, int(round(src_h * scale)) & ~1)
    scaled = vf.reformat(width=rw, height=rh, format="rgb24").to_ndarray(format="rgb24")
    canvas = np.zeros((enc_h, enc_w, 3), dtype=np.uint8)
    y0 = (enc_h - rh) // 2
    x0 = (enc_w - rw) // 2
    canvas[y0:y0 + rh, x0:x0 + rw] = scaled
    return av.VideoFrame.from_ndarray(canvas, format="rgb24").reformat(format=pix_fmt)


def _frame_dimensions(frame_or_arr) -> tuple[int, int]:
    if isinstance(frame_or_arr, av.VideoFrame):
        return frame_or_arr.width, frame_or_arr.height
    arr = np.asarray(frame_or_arr)
    return int(arr.shape[1]), int(arr.shape[0])


def _pcm_to_fltp_frame(pcm: np.ndarray, sample_rate: int) -> av.AudioFrame | None:
    arr = np.asarray(pcm, dtype=np.int16)
    if arr.size == 0:
        return None
    if arr.ndim == 1:
        if arr.size % 2 != 0:
            arr = arr[:-1]
        arr = arr.reshape(-1, 2)
    elif arr.shape[1] == 1:
        arr = np.repeat(arr, 2, axis=1)
    elif arr.shape[1] > 2:
        arr = arr[:, :2]
    if arr.shape[0] == 0:
        return None
    planar = np.ascontiguousarray(arr.astype(np.float32).T / 32768.0, dtype=np.float32)
    af = av.AudioFrame.from_ndarray(planar, format="fltp", layout="stereo")
    af.sample_rate = sample_rate
    return af


class ScreenRecorder:
    """Thread-safe MP4 recorder accepting live decoded video frames and PCM audio."""

    def __init__(
        self,
        output_dir: Path | str | None = None,
        fps: int = 30,
        sample_rate: int = 44100,
        expect_audio: bool | None = None,
    ):
        self.output_dir = Path(output_dir) if output_dir else default_recordings_dir()
        self.fps = max(1, int(fps))
        self.sample_rate = int(sample_rate)
        self.expect_audio = expect_audio
        self.active_encoder: str | None = None
        self.frames_written: int = 0
        self.last_error: str | None = None

        self._lock = threading.Lock()
        self._recording = False
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._vq: queue.Queue[tuple[float, object]] = queue.Queue(maxsize=90)
        self._aq: queue.Queue[np.ndarray] = queue.Queue(maxsize=240)
        self._thread: threading.Thread | None = None
        self._path: Path | None = None
        self._started_at: float = 0.0
        self._run_expect_audio: bool | None = expect_audio

    @property
    def recording(self) -> bool:
        return self._recording

    @property
    def output_path(self) -> Path | None:
        return self._path

    @property
    def elapsed_seconds(self) -> float:
        if not self._recording:
            return 0.0
        return max(0.0, time.monotonic() - self._started_at)

    def start(self, filename: str | None = None, expect_audio: bool | None = None) -> Path:
        with self._lock:
            if self._recording and self._path is not None:
                return self._path
            self.output_dir.mkdir(parents=True, exist_ok=True)
            name = filename or time.strftime("iPhone-Mirror-%Y%m%d-%H%M%S.mp4")
            self._path = self.output_dir / name
            self.active_encoder = None
            self.frames_written = 0
            self.last_error = None
            self._run_expect_audio = self.expect_audio if expect_audio is None else expect_audio
            self._drain_queues()
            self._stop.clear()
            self._wake.clear()
            self._started_at = time.monotonic()
            self._recording = True
            self._thread = threading.Thread(target=self._run, name="screen-recorder", daemon=True)
            self._thread.start()
            log.info("recording started -> %s", self._path)
            return self._path

    def push_video(self, frame, pts_sec: float | None = None):
        if not self._recording or self._stop.is_set():
            return
        ts = time.monotonic() if pts_sec is None else float(pts_sec)
        payload = frame if isinstance(frame, av.VideoFrame) else np.asarray(frame).copy()
        try:
            self._vq.put_nowait((ts, payload))
        except queue.Full:
            return
        self._wake.set()

    def push_audio(self, pcm: np.ndarray, sample_rate: int | None = None):
        _ = sample_rate
        if not self._recording or self._stop.is_set():
            return
        try:
            self._aq.put_nowait(np.asarray(pcm, dtype=np.int16).copy())
        except queue.Full:
            return
        self._wake.set()

    def stop(self, timeout: float = 10.0) -> Path | None:
        with self._lock:
            thread = self._thread
            path = self._path
            if not self._recording and thread is None:
                return path if (path is not None and path.exists() and path.stat().st_size > 0) else None
            self._recording = False
            self._stop.set()
            self._wake.set()
        if thread is not None:
            thread.join(timeout=timeout)
        with self._lock:
            self._thread = None
            path = self._path
        if self.frames_written == 0 or path is None or not path.exists() or path.stat().st_size == 0:
            if path is not None and path.exists():
                try:
                    path.unlink()
                except OSError:
                    pass
            return None
        return path

    def _drain_queues(self):
        while not self._vq.empty():
            try:
                self._vq.get_nowait()
            except queue.Empty:
                break
        while not self._aq.empty():
            try:
                self._aq.get_nowait()
            except queue.Empty:
                break

    def _collect_initial(self) -> tuple[list[tuple[float, object]], bool]:
        pre_v: list[tuple[float, object]] = []
        first_seen: float | None = None
        while True:
            while not self._vq.empty():
                pre_v.append(self._vq.get_nowait())
                if first_seen is None:
                    first_seen = time.monotonic()
            if pre_v:
                if self._run_expect_audio is not None:
                    return pre_v, bool(self._run_expect_audio)
                if not self._aq.empty() or self._stop.is_set() or (time.monotonic() - first_seen) >= 0.08:
                    return pre_v, not self._aq.empty()
            elif self._stop.is_set():
                return [], False
            self._wake.wait(timeout=0.02)
            self._wake.clear()

    def _run(self):
        container = None
        vstream = None
        astream = None
        fifo = None
        try:
            pre_v, want_audio = self._collect_initial()
            if not pre_v:
                return
            t0, first_frame = pre_v[0]
            src_w, src_h = _frame_dimensions(first_frame)
            enc_w = max(2, (src_w + 1) & ~1)
            enc_h = max(2, (src_h + 1) & ~1)
            codec_name, pix_fmt = _probe_video_encoder(enc_w, enc_h, self.fps)
            self.active_encoder = codec_name

            container = av.open(str(self._path), mode="w")
            vstream = container.add_stream(codec_name, rate=self.fps)
            vstream.width = enc_w
            vstream.height = enc_h
            vstream.pix_fmt = pix_fmt
            vstream.bit_rate = 8_000_000
            vstream.time_base = _VIDEO_TIME_BASE
            vstream.codec_context.time_base = _VIDEO_TIME_BASE
            if codec_name == "libx264":
                vstream.options = {"preset": "veryfast"}

            if want_audio:
                astream = container.add_stream("aac", rate=self.sample_rate, layout="stereo")
                astream.bit_rate = 128_000
                astream.time_base = Fraction(1, self.sample_rate)
                fifo = av.AudioFifo()

            log.info(
                "recording muxer opened %s %dx%d (%s audio=%s)",
                self._path,
                enc_w,
                enc_h,
                codec_name,
                bool(astream),
            )

            last_v_pts = -1
            audio_pts = 0
            pending_v = list(pre_v)

            def encode_video(ts: float, raw):
                nonlocal last_v_pts
                vf = _to_video_frame(raw, enc_w, enc_h, pix_fmt)
                pts = max(last_v_pts + 1, int(round((ts - t0) * 90_000)))
                last_v_pts = pts
                vf.pts = pts
                vf.time_base = _VIDEO_TIME_BASE
                for pkt in vstream.encode(vf):
                    container.mux(pkt)
                self.frames_written += 1

            def drain_audio():
                nonlocal audio_pts
                while not self._aq.empty():
                    pcm = self._aq.get_nowait()
                    if astream is None or fifo is None:
                        continue
                    af = _pcm_to_fltp_frame(pcm, self.sample_rate)
                    if af is not None:
                        fifo.write(af)
                    fsize = astream.codec_context.frame_size or 1024
                    while True:
                        chunk = fifo.read(fsize)
                        if chunk is None:
                            break
                        chunk.pts = audio_pts
                        chunk.time_base = Fraction(1, self.sample_rate)
                        audio_pts += chunk.samples
                        for pkt in astream.encode(chunk):
                            container.mux(pkt)

            while True:
                drain_audio()
                for ts, raw in pending_v:
                    encode_video(ts, raw)
                pending_v.clear()

                while not self._vq.empty():
                    ts, raw = self._vq.get_nowait()
                    drain_audio()
                    encode_video(ts, raw)

                if self._stop.is_set() and self._vq.empty() and self._aq.empty():
                    break
                self._wake.wait(timeout=0.03)
                self._wake.clear()

            if astream is not None and fifo is not None:
                fsize = astream.codec_context.frame_size or 1024
                rem = fifo.read(fsize, partial=True)
                if rem is not None:
                    rem.pts = audio_pts
                    rem.time_base = Fraction(1, self.sample_rate)
                    audio_pts += rem.samples
                    for pkt in astream.encode(rem):
                        container.mux(pkt)
                for pkt in astream.encode(None):
                    container.mux(pkt)

            for pkt in vstream.encode(None):
                container.mux(pkt)

            log.info("recording finished %s (%d frames)", self._path, self.frames_written)
        except Exception as exc:
            self.last_error = str(exc)
            log.exception("screen recorder failed")
        finally:
            self._recording = False
            if container is not None:
                try:
                    container.close()
                except Exception:
                    log.debug("error closing recording container", exc_info=True)
