"""Pure streaming data-plane operations for AirPlay/USB video, audio, and mDNS TXT framing."""
import math
import struct

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

START = b"\x00\x00\x00\x01"
_U128_MASK = (1 << 128) - 1


def avcc_to_annexb(data: bytes) -> bytes | None:
    """Convert 4-byte big-endian length-prefixed NALs to Annex-B start codes; None if malformed."""
    out = bytearray()
    pos, n = 0, len(data)
    while pos < n:
        if pos + 4 > n:
            return None
        size = int.from_bytes(data[pos:pos + 4], "big")
        if size <= 0 or pos + 4 + size > n or (data[pos + 4] & 0x80):
            return None
        out += START
        out += data[pos + 4:pos + 4 + size]
        pos += 4 + size
    return bytes(out)


def decrypt_mirror_nal(key: bytes, iv: bytes, offset: int, payload: bytes) -> bytes | None:
    """Stateless AES-128-CTR decryption at byte stream `offset`, then AVCC-to-Annex-B conversion."""
    if len(key) != 16 or len(iv) != 16:
        raise ValueError("AES-128-CTR key and iv must be 16 bytes")
    if offset < 0:
        raise ValueError("stream offset must be non-negative")
    if not payload:
        return b""
    block_idx = offset // 16
    intra = offset % 16
    ctr_iv = ((int.from_bytes(iv, "big") + block_idx) & _U128_MASK).to_bytes(16, "big")
    dec = Cipher(algorithms.AES(key), modes.CTR(ctr_iv)).decryptor()
    if intra:
        dec.update(b"\x00" * intra)
    plain = dec.update(payload) + dec.finalize()
    return avcc_to_annexb(plain)


def parse_avcc_config(payload: bytes) -> bytes | None:
    """Parse AirPlay ptype=1 AVCC SPS+PPS configuration record -> Annex-B bytes, or None."""
    if len(payload) < 11:
        return None
    if payload[4:8] == b"hvc1":
        return None
    sps_size = struct.unpack_from(">H", payload, 6)[0]
    if sps_size == 0 or sps_size + 11 > len(payload):
        return None
    sps = payload[8:8 + sps_size]
    pps_size = struct.unpack_from(">H", payload, sps_size + 9)[0]
    if pps_size == 0 or sps_size + 11 + pps_size > len(payload):
        return None
    pps = payload[sps_size + 11:sps_size + 11 + pps_size]
    return START + sps + START + pps


def decrypt_audio_rtp(key: bytes, iv: bytes, pkt: bytes, last_seq: int) -> tuple[int, bytes] | None:
    """Validate RTP sequence ordering (pass last_seq < 0 for first packet) and AES-128-CBC decrypt."""
    if len(key) != 16 or len(iv) != 16:
        raise ValueError("AES-128-CBC key and iv must be 16 bytes")
    if len(pkt) < 12:
        return None
    seq = int.from_bytes(pkt[2:4], "big")
    if last_seq >= 0:
        diff = (seq - (last_seq & 0xFFFF)) & 0xFFFF
        if diff == 0 or diff > 0x8000:
            return None
    payload = pkt[12:]
    n = (len(payload) // 16) * 16
    if n:
        dec = Cipher(algorithms.AES(key), modes.CBC(iv)).decryptor()
        clear = dec.update(payload[:n]) + payload[n:]
    else:
        clear = bytes(payload)
    return (seq, clear)


def scale_pcm_i16(pcm: bytes, gain: float) -> bytes:
    """Scale packed little-endian signed 16-bit PCM samples by `gain`, clamped to int16."""
    if len(pcm) % 2 != 0:
        raise ValueError("pcm byte length must be even")
    if not math.isfinite(gain) or gain < 0.0:
        raise ValueError("gain must be finite and non-negative")
    if not pcm:
        return b""
    out = bytearray(len(pcm))
    for i in range(0, len(pcm), 2):
        sample = struct.unpack_from("<h", pcm, i)[0]
        scaled = int(sample * gain)
        if scaled > 32767:
            scaled = 32767
        elif scaled < -32768:
            scaled = -32768
        struct.pack_into("<h", out, i, scaled)
    return bytes(out)


def visible_size(frame_w: int, frame_h: int, vis_w: int, vis_h: int) -> tuple[int, int]:
    """Drop encoder padding when `vis_w`/`vis_h` is within 64 px of the coded frame size."""
    if (
        vis_w > 0
        and vis_h > 0
        and frame_w - 64 <= vis_w <= frame_w
        and frame_h - 64 <= vis_h <= frame_h
    ):
        return (vis_w, vis_h)
    return (frame_w, frame_h)


def encode_txt_records(keys: list[str], values: list[str]) -> bytes:
    """Encode DNS-SD TXT key/value pairs into wire rdata (length-prefixed `k=v` entries)."""
    if len(keys) != len(values):
        raise ValueError("keys and values must have the same length")
    out = bytearray()
    for k, v in zip(keys, values):
        item = f"{k}={v}".encode("utf-8")
        if len(item) > 255:
            raise ValueError("TXT record entry exceeds 255 bytes")
        out.append(len(item))
        out += item
    return bytes(out)
# >>> rust-anything: stream-ops-rs is on. `rust-anything disable ../../rust/stream-ops-rs` removes this block.
def _rust_anything_stream_ops_rs():
    import importlib, os, sys
    mode = os.environ.get("RUST_ANYTHING_MODE")
    if mode == "old" or os.environ.get("RUST_ANYTHING_UNIT_STREAM_OPS") == "original":
        return
    at = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "../../rust/stream-ops-rs/python"))
    sys.path.insert(0, at)
    try:
        native = importlib.import_module("stream_ops_rs")
    except ImportError:
        if mode == "new":
            raise
        return
    finally:
        sys.path.remove(at)
    globals().update({name: getattr(native, name) for name in ["avcc_to_annexb", "decrypt_mirror_nal", "decrypt_audio_rtp", "scale_pcm_i16"]})


_rust_anything_stream_ops_rs()
del _rust_anything_stream_ops_rs
# <<< rust-anything: stream-ops-rs
