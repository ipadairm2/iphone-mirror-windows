"""Tests for ScreenRecorder (live MP4 video + AAC audio recording)."""
import tempfile
import unittest
from pathlib import Path

import av
import numpy as np

from iphone_mirror.recorder import ScreenRecorder


class RecorderTests(unittest.TestCase):
    def test_record_video_and_audio_odd_dimensions(self):
        with tempfile.TemporaryDirectory() as tmp:
            rec = ScreenRecorder(output_dir=Path(tmp), fps=30)
            rec.start("odd_av.mp4")
            for i in range(6):
                frame = np.full((579, 321, 4), (i * 35) % 255, dtype=np.uint8)
                rec.push_video(frame, pts_sec=10.0 + i * 0.033)
            for _ in range(4):
                pcm = np.full((1024, 2), 1200, dtype=np.int16)
                rec.push_audio(pcm)
            out = rec.stop()
            self.assertIsNotNone(out)
            self.assertTrue(out.exists())
            self.assertIsNotNone(rec.active_encoder)

            with av.open(str(out)) as container:
                v_streams = [s for s in container.streams if s.type == "video"]
                a_streams = [s for s in container.streams if s.type == "audio"]
                self.assertEqual(len(v_streams), 1)
                self.assertEqual(len(a_streams), 1)
                self.assertEqual((v_streams[0].width, v_streams[0].height), (322, 580))
                self.assertGreaterEqual(v_streams[0].frames, 6)
                self.assertEqual(a_streams[0].codec_context.name, "aac")
                self.assertGreater(a_streams[0].frames, 0)

    def test_record_video_only_and_rotation(self):
        with tempfile.TemporaryDirectory() as tmp:
            rec = ScreenRecorder(output_dir=Path(tmp), fps=30, expect_audio=False)
            rec.start("rot.mp4")
            for i in range(3):
                rec.push_video(np.full((420, 240, 4), 80, dtype=np.uint8), pts_sec=20.0 + i * 0.033)
            for i in range(3, 6):
                rec.push_video(np.full((240, 420, 4), 160, dtype=np.uint8), pts_sec=20.0 + i * 0.033)
            out = rec.stop()
            self.assertIsNotNone(out)
            self.assertTrue(out.exists())

            with av.open(str(out)) as container:
                v_streams = [s for s in container.streams if s.type == "video"]
                a_streams = [s for s in container.streams if s.type == "audio"]
                self.assertEqual(len(v_streams), 1)
                self.assertEqual(len(a_streams), 0)
                self.assertEqual((v_streams[0].width, v_streams[0].height), (240, 420))
                self.assertGreaterEqual(v_streams[0].frames, 6)

    def test_record_no_frames_returns_none_and_cleans_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            rec = ScreenRecorder(output_dir=Path(tmp), fps=30)
            target = rec.start("empty.mp4")
            out = rec.stop()
            self.assertIsNone(out)
            self.assertFalse(target.exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
