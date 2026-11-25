//! The Rust port of `iphone_mirror/stream_ops/`.

#![forbid(unsafe_code)]

use aes::Aes128;
use aes::cipher::{BlockDecryptMut, KeyIvInit, StreamCipher};
use cbc::Decryptor as CbcDecryptor;
use ctr::Ctr128BE;

const START: [u8; 4] = [0x00, 0x00, 0x00, 0x01];

#[inline]
fn to_array16(slice: &[u8], msg: &str) -> Result<[u8; 16], String> {
    slice.try_into().map_err(|_| format!("ValueError: {msg}"))
}

fn avcc_to_annexb_slice(data: &[u8]) -> Option<Vec<u8>> {
    let n = data.len();
    let mut out = Vec::with_capacity(n + 16);
    let mut pos = 0usize;
    while pos < n {
        if pos + 4 > n {
            return None;
        }
        let size =
            u32::from_be_bytes([data[pos], data[pos + 1], data[pos + 2], data[pos + 3]]) as usize;
        if size == 0 || pos + 4 + size > n || (data[pos + 4] & 0x80) != 0 {
            return None;
        }
        out.extend_from_slice(&START);
        out.extend_from_slice(&data[pos + 4..pos + 4 + size]);
        pos += 4 + size;
    }
    Some(out)
}

/// Port of `avcc_to_annexb` (`iphone_mirror/stream_ops/__init__.py:11`).
pub fn avcc_to_annexb(data: Vec<u8>) -> Result<Option<Vec<u8>>, String> {
    Ok(avcc_to_annexb_slice(&data))
}

/// Port of `decrypt_mirror_nal` (`iphone_mirror/stream_ops/__init__.py:27`).
pub fn decrypt_mirror_nal(
    key: Vec<u8>,
    iv: Vec<u8>,
    offset: i64,
    payload: Vec<u8>,
) -> Result<Option<Vec<u8>>, String> {
    let key_arr = to_array16(&key, "AES-128-CTR key and iv must be 16 bytes")?;
    let iv_arr = to_array16(&iv, "AES-128-CTR key and iv must be 16 bytes")?;
    if offset < 0 {
        return Err("ValueError: stream offset must be non-negative".to_string());
    }
    if payload.is_empty() {
        return Ok(Some(Vec::new()));
    }
    let off = offset as u128;
    let block_idx = off / 16;
    let intra = (off % 16) as usize;
    let ctr_iv = u128::from_be_bytes(iv_arr)
        .wrapping_add(block_idx)
        .to_be_bytes();
    let mut cipher = Ctr128BE::<Aes128>::new(&key_arr.into(), &ctr_iv.into());
    if intra > 0 {
        let mut scratch = [0u8; 16];
        cipher.apply_keystream(&mut scratch[..intra]);
    }
    let mut plain = payload;
    cipher.apply_keystream(&mut plain);
    Ok(avcc_to_annexb_slice(&plain))
}

/// Port of `parse_avcc_config` (`iphone_mirror/stream_ops/__init__.py:45`).
pub fn parse_avcc_config(payload: Vec<u8>) -> Result<Option<Vec<u8>>, String> {
    if payload.len() < 11 || &payload[4..8] == b"hvc1" {
        return Ok(None);
    }
    let sps_size = usize::from(u16::from_be_bytes([payload[6], payload[7]]));
    if sps_size == 0 || sps_size + 11 > payload.len() {
        return Ok(None);
    }
    let pps_size = usize::from(u16::from_be_bytes([
        payload[sps_size + 9],
        payload[sps_size + 10],
    ]));
    if pps_size == 0 || sps_size + 11 + pps_size > payload.len() {
        return Ok(None);
    }
    let mut out = Vec::with_capacity(8 + sps_size + pps_size);
    out.extend_from_slice(&START);
    out.extend_from_slice(&payload[8..8 + sps_size]);
    out.extend_from_slice(&START);
    out.extend_from_slice(&payload[sps_size + 11..sps_size + 11 + pps_size]);
    Ok(Some(out))
}

/// Port of `decrypt_audio_rtp` (`iphone_mirror/stream_ops/__init__.py:62`).
pub fn decrypt_audio_rtp(
    key: Vec<u8>,
    iv: Vec<u8>,
    pkt: Vec<u8>,
    last_seq: i64,
) -> Result<Option<(i64, Vec<u8>)>, String> {
    let key_arr = to_array16(&key, "AES-128-CBC key and iv must be 16 bytes")?;
    let iv_arr = to_array16(&iv, "AES-128-CBC key and iv must be 16 bytes")?;
    if pkt.len() < 12 {
        return Ok(None);
    }
    let seq = i64::from(u16::from_be_bytes([pkt[2], pkt[3]]));
    if last_seq >= 0 {
        let diff = (seq - (last_seq & 0xFFFF)).rem_euclid(65536);
        if diff == 0 || diff > 0x8000 {
            return Ok(None);
        }
    }
    let mut clear = pkt[12..].to_vec();
    let aligned = (clear.len() / 16) * 16;
    if aligned > 0 {
        let mut dec = CbcDecryptor::<Aes128>::new(&key_arr.into(), &iv_arr.into());
        for block in clear[..aligned].as_chunks_mut::<16>().0 {
            dec.decrypt_block_mut(block.into());
        }
    }
    Ok(Some((seq, clear)))
}

/// Port of `scale_pcm_i16` (`iphone_mirror/stream_ops/__init__.py:83`).
pub fn scale_pcm_i16(pcm: Vec<u8>, gain: f64) -> Result<Vec<u8>, String> {
    if !pcm.len().is_multiple_of(2) {
        return Err("ValueError: pcm byte length must be even".to_string());
    }
    if !gain.is_finite() || gain < 0.0 {
        return Err("ValueError: gain must be finite and non-negative".to_string());
    }
    if pcm.is_empty() {
        return Ok(Vec::new());
    }
    let mut out = pcm;
    for pair in out.as_chunks_mut::<2>().0 {
        let sample = i16::from_le_bytes(*pair);
        let scaled = (f64::from(sample) * gain).clamp(-32768.0, 32767.0) as i16;
        *pair = scaled.to_le_bytes();
    }
    Ok(out)
}

/// Port of `visible_size` (`iphone_mirror/stream_ops/__init__.py:103`).
pub fn visible_size(
    frame_w: i64,
    frame_h: i64,
    vis_w: i64,
    vis_h: i64,
) -> Result<(i64, i64), String> {
    if vis_w > 0
        && vis_h > 0
        && frame_w.saturating_sub(64) <= vis_w
        && vis_w <= frame_w
        && frame_h.saturating_sub(64) <= vis_h
        && vis_h <= frame_h
    {
        Ok((vis_w, vis_h))
    } else {
        Ok((frame_w, frame_h))
    }
}

/// Port of `encode_txt_records` (`iphone_mirror/stream_ops/__init__.py:115`).
pub fn encode_txt_records(keys: Vec<String>, values: Vec<String>) -> Result<Vec<u8>, String> {
    if keys.len() != values.len() {
        return Err("ValueError: keys and values must have the same length".to_string());
    }
    let mut out = Vec::new();
    for (k, v) in keys.iter().zip(values.iter()) {
        let len = k.len() + 1 + v.len();
        if len > 255 {
            return Err("ValueError: TXT record entry exceeds 255 bytes".to_string());
        }
        out.push(len as u8);
        out.extend_from_slice(k.as_bytes());
        out.push(b'=');
        out.extend_from_slice(v.as_bytes());
    }
    Ok(out)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn roundtrip_avcc_and_txt() {
        let avcc = vec![0, 0, 0, 3, 0x65, 1, 2, 0, 0, 0, 2, 0x41, 9];
        assert_eq!(
            avcc_to_annexb(avcc),
            Ok(Some(vec![0, 0, 0, 1, 0x65, 1, 2, 0, 0, 0, 1, 0x41, 9]))
        );
        assert_eq!(avcc_to_annexb(vec![0, 0, 0, 0]), Ok(None));

        let txt = encode_txt_records(vec!["a".into()], vec!["1".into()]);
        assert_eq!(txt, Ok(b"\x03a=1".to_vec()));
        assert!(encode_txt_records(vec!["a".into()], vec![]).is_err());
    }

    #[test]
    fn validates_crypto_and_pcm_errors() {
        assert!(decrypt_mirror_nal(vec![0; 15], vec![0; 16], 0, vec![1]).is_err());
        assert!(decrypt_mirror_nal(vec![0; 16], vec![0; 16], -1, vec![1]).is_err());
        assert!(decrypt_audio_rtp(vec![0; 15], vec![0; 16], vec![0; 20], -1).is_err());
        assert!(scale_pcm_i16(vec![1], 1.0).is_err());
        assert!(scale_pcm_i16(vec![0, 0], -1.0).is_err());
    }
}
