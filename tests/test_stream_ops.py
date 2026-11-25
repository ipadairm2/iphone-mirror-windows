"""Unit tests for iphone_mirror.stream_ops."""
import os
import struct
import sys
import unittest
from pathlib import Path

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from iphone_mirror.stream_ops import (  # noqa: E402
    START,
    avcc_to_annexb,
    decrypt_audio_rtp,
    decrypt_mirror_nal,
    encode_txt_records,
    parse_avcc_config,
    scale_pcm_i16,
    visible_size,
)


class StreamOpsTests(unittest.TestCase):
    def test_avcc_to_annexb_valid_and_malformed(self):
        nal1 = bytes([0x65, 1, 2, 3])
        nal2 = bytes([0x41, 4, 5])
        avcc = struct.pack(">I", len(nal1)) + nal1 + struct.pack(">I", len(nal2)) + nal2
        self.assertEqual(avcc_to_annexb(avcc), START + nal1 + START + nal2)
        self.assertEqual(avcc_to_annexb(b""), b"")
        self.assertIsNone(avcc_to_annexb(b"\x00\x00"))
        self.assertIsNone(avcc_to_annexb(b"\x00\x00\x00\x00"))
        self.assertIsNone(avcc_to_annexb(b"\x00\x00\x00\x05\x65\x01"))
        self.assertIsNone(avcc_to_annexb(b"\x00\x00\x00\x02\x80\x01"))

    def test_decrypt_mirror_nal_matches_stateful_ctr_across_unaligned_chunks(self):
        key = bytes(range(16))
        iv = bytes(range(16, 32))
        enc = Cipher(algorithms.AES(key), modes.CTR(iv)).encryptor()

        nals = [
            bytes([0x65]) + os.urandom(11),
            bytes([0x41]) + os.urandom(27),
            bytes([0x41]) + os.urandom(128),
        ]
        offset = 0
        for nal in nals:
            plain = struct.pack(">I", len(nal)) + nal
            ct = enc.update(plain)
            got = decrypt_mirror_nal(key, iv, offset, ct)
            self.assertEqual(got, START + nal)
            offset += len(ct)

    def test_decrypt_mirror_nal_counter_wrap_and_validation(self):
        key = b"\x11" * 16
        iv = b"\xff" * 16
        enc = Cipher(algorithms.AES(key), modes.CTR(iv)).encryptor()
        p1 = struct.pack(">I", 4) + b"\x65abc"
        p2 = struct.pack(">I", 12) + b"\x41" + b"0123456789a"
        c1 = enc.update(p1)
        c2 = enc.update(p2)
        self.assertEqual(decrypt_mirror_nal(key, iv, 0, c1), START + b"\x65abc")
        self.assertEqual(decrypt_mirror_nal(key, iv, len(c1), c2), START + b"\x41" + b"0123456789a")
        self.assertEqual(decrypt_mirror_nal(key, iv, 0, b""), b"")
        with self.assertRaises(ValueError):
            decrypt_mirror_nal(b"short", iv, 0, c1)
        with self.assertRaises(ValueError):
            decrypt_mirror_nal(key, iv, -1, c1)

    def test_parse_avcc_config(self):
        sps = b"\x67\x64\x00\x1f"
        pps = b"\x68\xee\x3c\x80"
        cfg = bytes([1, 0x64, 0, 0x1F, 0xFF, 0xE1]) + struct.pack(">H", len(sps)) + sps + b"\x01" + struct.pack(">H", len(pps)) + pps
        self.assertEqual(parse_avcc_config(cfg), START + sps + START + pps)
        self.assertIsNone(parse_avcc_config(b"short"))
        self.assertIsNone(parse_avcc_config(b"\x00\x00\x00\x00hvc1" + b"\x00" * 20))
        self.assertIsNone(parse_avcc_config(cfg[:-1]))

    def test_decrypt_audio_rtp_sequence_and_tail(self):
        key = b"\x22" * 16
        iv = b"\x33" * 16
        plain = bytes(range(37))  # 2 AES blocks + 5 tail bytes
        n = (len(plain) // 16) * 16
        ct = Cipher(algorithms.AES(key), modes.CBC(iv)).encryptor().update(plain[:n]) + plain[n:]
        pkt = bytes([0x80, 0x60]) + struct.pack(">HII", 65535, 1000, 0xAABBCCDD) + ct

        self.assertEqual(decrypt_audio_rtp(key, iv, pkt, -1), (65535, plain))
        # duplicate and late rejected
        self.assertIsNone(decrypt_audio_rtp(key, iv, pkt, 65535))
        pkt_late = bytes([0x80, 0x60]) + struct.pack(">HII", 65530, 1000, 0) + ct
        self.assertIsNone(decrypt_audio_rtp(key, iv, pkt_late, 65535))
        # wrap-around 65535 -> 0 accepted
        pkt_wrap = bytes([0x80, 0x60]) + struct.pack(">HII", 0, 2000, 0) + ct
        self.assertEqual(decrypt_audio_rtp(key, iv, pkt_wrap, 65535), (0, plain))
        self.assertIsNone(decrypt_audio_rtp(key, iv, b"short", -1))
        with self.assertRaises(ValueError):
            decrypt_audio_rtp(b"bad", iv, pkt, -1)

    def test_scale_pcm_i16(self):
        samples = struct.pack("<4h", -32768, -1000, 1000, 32767)
        self.assertEqual(scale_pcm_i16(samples, 0.5), struct.pack("<4h", -16384, -500, 500, 16383))
        self.assertEqual(scale_pcm_i16(samples, 2.0), struct.pack("<4h", -32768, -2000, 2000, 32767))
        self.assertEqual(scale_pcm_i16(b"", 1.0), b"")
        with self.assertRaises(ValueError):
            scale_pcm_i16(b"\x01", 1.0)
        with self.assertRaises(ValueError):
            scale_pcm_i16(samples, -0.5)

    def test_visible_size_and_txt_records(self):
        self.assertEqual(visible_size(1216, 2656, 1206, 2622), (1206, 2622))
        self.assertEqual(visible_size(1216, 2656, 0, 0), (1216, 2656))
        self.assertEqual(visible_size(1216, 2656, 402, 874), (1216, 2656))

        wire = encode_txt_records(["deviceid", "vv"], ["aa:bb", "2"])
        self.assertEqual(wire, b"\x0edeviceid=aa:bb\x04vv=2")
        with self.assertRaises(ValueError):
            encode_txt_records(["a"], ["1", "2"])
        with self.assertRaises(ValueError):
            encode_txt_records(["k"], ["x" * 255])


if __name__ == "__main__":
    unittest.main()
