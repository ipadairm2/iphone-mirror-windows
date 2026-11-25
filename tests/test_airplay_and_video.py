"""Tests for AirPlay plist redaction, clean teardown, and VideoDecoder HW/SW fallback."""
from fractions import Fraction
import json
import socket
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

import av
import numpy as np

from iphone_mirror import airplay, net
from iphone_mirror.config import Settings
from iphone_mirror.video import VideoDecoder


def _encode_single_h264_idr(width: int = 64, height: int = 64) -> bytes:
    cc = av.CodecContext.create("libx264", "w")
    cc.width = width
    cc.height = height
    cc.pix_fmt = "yuv420p"
    cc.time_base = Fraction(1, 30)
    cc.options = {"tune": "zerolatency", "preset": "ultrafast"}
    cc.open()
    frame = av.VideoFrame(width, height, "yuv420p")
    frame.pts = 0
    packets = list(cc.encode(frame))
    packets.extend(cc.encode(None))
    return b"".join(bytes(p) for p in packets)


def _encode_h264_sequence(width: int = 64, height: int = 64, count: int = 14) -> list[bytes]:
    cc = av.CodecContext.create("libx264", "w")
    cc.width = width
    cc.height = height
    cc.pix_fmt = "yuv420p"
    cc.time_base = Fraction(1, 30)
    cc.gop_size = 120
    cc.max_b_frames = 0
    cc.options = {"tune": "zerolatency", "preset": "ultrafast"}
    cc.open()
    out = []
    for i in range(count):
        arr = np.full((height, width, 3), (i * 19) % 255, dtype=np.uint8)
        frame = av.VideoFrame.from_ndarray(arr, format="rgb24").reformat(format="yuv420p")
        frame.pts = i
        for p in cc.encode(frame):
            out.append(bytes(p))
    for p in cc.encode(None):
        out.append(bytes(p))
    return out


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class AirPlayAndVideoTests(unittest.TestCase):
    def test_describe_plist_redacts_bytes(self):
        payload = {
            "eiv": b"0123456789abcdef",
            "streams": [
                {"type": 110, "key": bytearray(72)},
            ],
            "nested": {"a": {"b": {"c": {"d": b"secret"}}}},
        }
        described = airplay._describe_plist(payload)
        self.assertEqual(described["eiv"], "<16 bytes>")
        self.assertEqual(described["streams"][0]["type"], 110)
        self.assertEqual(described["streams"][0]["key"], "<72 bytes>")
        self.assertEqual(described["nested"]["a"]["b"]["c"], "{...}")

    def test_receiver_stop_releases_port(self):
        port = _free_port()
        old = (net.BIND_HOST, net.ADVERTISE, net.PORT)
        net.BIND_HOST, net.ADVERTISE, net.PORT = "127.0.0.1", False, port
        try:
            with tempfile.TemporaryDirectory() as tmp:
                settings = Settings(Path(tmp) / "settings.json")
                settings["name"] = "TestMirror"
                listening = threading.Event()

                def on_event(ev, info):
                    if ev == "listening":
                        listening.set()

                rx = airplay.Receiver(settings, on_frame=lambda *a: None, on_event=on_event, hw_decode=False)
                rx.start()
                self.assertTrue(listening.wait(timeout=4.0), "Receiver did not emit listening")
                with socket.create_connection(("127.0.0.1", port), timeout=1.0):
                    pass

                rx.stop()
                rx.stop()  # idempotent second stop

                # Port must be bindable again promptly once stopped.
                deadline = time.monotonic() + 2.0
                rebound = False
                while time.monotonic() < deadline:
                    try:
                        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                            s.bind(("127.0.0.1", port))
                            rebound = True
                            break
                    except OSError:
                        time.sleep(0.05)
                self.assertTrue(rebound, "Receiver.stop() did not release TCP port")
        finally:
            net.BIND_HOST, net.ADVERTISE, net.PORT = old

    def test_video_decoder_discard_retires_queued_packets(self):
        frames = []
        dec = VideoDecoder(on_frame=lambda arr, w, h: frames.append((arr, w, h)), codec="h264", hw_decode=False)
        dec.set_codec_config(b"\x00\x00\x00\x01\x67")
        dec.submit(b"\x00\x00\x00\x01\x65\x00")
        dec.submit(b"\x00\x00\x00\x01\x41\x00")
        self.assertEqual(dec.q.qsize(), 2)
        dec.discard()
        self.assertEqual(dec._epoch, 1)
        self.assertTrue(dec.q.empty())
        self.assertIsNone(dec._cached_config)

        dec.start()
        time.sleep(0.05)
        dec.stop()
        dec.join(timeout=2.0)
        self.assertEqual(frames, [])

    def test_video_decoder_hw_fallback_to_software(self):
        idr = _encode_single_h264_idr(64, 64)
        real_create = av.CodecContext.create
        got_frame = threading.Event()
        delivered = []
        raw_frames = []

        def on_frame(arr, w, h):
            delivered.append((arr, w, h))
            got_frame.set()

        def fake_create(name, mode="r"):
            if mode == "r" and name in ("h264_cuvid", "h264_qsv"):
                raise av.error.FFmpegError(0, "mocked hw failure")
            return real_create(name, mode)

        with mock.patch("iphone_mirror.video.av.CodecContext.create", side_effect=fake_create):
            dec = VideoDecoder(
                on_frame=on_frame,
                codec="h264",
                hw_decode=True,
                on_raw_frame=raw_frames.append,
            )
            dec.start()
            try:
                dec.submit(idr)
                self.assertTrue(got_frame.wait(timeout=5.0), "Software fallback did not deliver a frame")
                self.assertEqual(len(delivered), 1)
                arr, vw, vh = delivered[0]
                self.assertEqual((vw, vh), (64, 64))
                self.assertEqual(arr.shape, (64, 64, 4))
                self.assertEqual(arr.dtype, np.uint8)
                self.assertFalse(dec.hw_active)
                self.assertEqual(dec.active_codec, "h264")
                self.assertIsNotNone(dec.last_frame)
                self.assertEqual(len(raw_frames), 1)
            finally:
                dec.stop()
                dec.join(timeout=2.0)

    def test_video_decoder_crop_and_scale(self):
        out = []
        dec = VideoDecoder(on_frame=lambda arr, w, h: out.append((arr, w, h)), codec="h264", hw_decode=False)
        dec.visible = (300, 500)
        dec.target = (150, 250)
        padded = av.VideoFrame(320, 512, "yuv420p")
        dec._deliver(padded)
        self.assertEqual(len(out), 1)
        arr, vw, vh = out[0]
        self.assertEqual((vw, vh), (300, 500))
        self.assertEqual(arr.shape, (250, 150, 4))

    def test_hw_fallback_replays_idr_after_empty_runs(self):
        pkts = _encode_h264_sequence(64, 64, count=14)
        self.assertGreaterEqual(len(pkts), 12)
        real_create = av.CodecContext.create
        got_frame = threading.Event()
        delivered = []

        class EmptyHwCodec:
            options = {}
            extradata = None

            def open(self):
                pass

            def decode(self, pkt):
                _ = pkt
                return []

        def fake_create(name, mode="r"):
            if mode == "r" and name == "h264_cuvid":
                return EmptyHwCodec()
            return real_create(name, mode)

        def on_frame(arr, w, h):
            delivered.append((arr, w, h))
            got_frame.set()

        with mock.patch("iphone_mirror.video.av.CodecContext.create", side_effect=fake_create):
            dec = VideoDecoder(on_frame=on_frame, codec="h264", hw_decode=True)
            dec.start()
            try:
                for p in pkts[:12]:
                    dec.submit(p)
                self.assertTrue(got_frame.wait(timeout=5.0), "Fallback did not replay IDR after empty HW runs")
                self.assertFalse(dec.hw_active)
                self.assertEqual(dec.active_codec, "h264")
                self.assertEqual(delivered[0][1:], (64, 64))
            finally:
                dec.stop()
                dec.join(timeout=2.0)

    def test_hw_fallback_replays_idr_after_pframe_error(self):
        pkts = _encode_h264_sequence(64, 64, count=6)
        self.assertGreaterEqual(len(pkts), 3)
        real_create = av.CodecContext.create
        got_frame = threading.Event()
        delivered = []

        class FailSecondHwCodec:
            options = {}
            extradata = None
            calls = 0

            def open(self):
                pass

            def decode(self, pkt):
                _ = pkt
                self.calls += 1
                if self.calls == 1:
                    return []
                raise av.error.FFmpegError(0, "mocked p-frame hw failure")

        def fake_create(name, mode="r"):
            if mode == "r" and name == "h264_cuvid":
                return FailSecondHwCodec()
            return real_create(name, mode)

        def on_frame(arr, w, h):
            delivered.append((arr, w, h))
            got_frame.set()

        with mock.patch("iphone_mirror.video.av.CodecContext.create", side_effect=fake_create):
            dec = VideoDecoder(on_frame=on_frame, codec="h264", hw_decode=True)
            dec.start()
            try:
                dec.submit(pkts[0])
                dec.submit(pkts[1])
                self.assertTrue(got_frame.wait(timeout=5.0), "Fallback did not replay IDR after P-frame HW error")
                self.assertFalse(dec.hw_active)
                self.assertEqual(dec.active_codec, "h264")
                self.assertEqual(delivered[0][1:], (64, 64))
            finally:
                dec.stop()
                dec.join(timeout=2.0)

    def test_settings_v1_migrates_hw_decode_to_false(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "settings.json"
            path.write_text(json.dumps({"name": "PC", "hw_decode": True}), encoding="utf-8")
            s1 = Settings(path)
            self.assertFalse(s1["hw_decode"])
            self.assertEqual(s1["settings_version"], 2)

            # A v2 config explicitly enabling hw_decode must keep it enabled.
            s1["hw_decode"] = True
            s1.save()
            s2 = Settings(path)
            self.assertTrue(s2["hw_decode"])
            self.assertEqual(s2["settings_version"], 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
