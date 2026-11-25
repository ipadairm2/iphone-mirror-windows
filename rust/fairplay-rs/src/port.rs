//! The Rust port of `iphone_mirror/fairplay/`.

#![forbid(unsafe_code)]

mod garble;
mod tables;

use serde_json::{Value, json};

const MD5_SHIFT: [u32; 64] = [
    7, 12, 17, 22, 7, 12, 17, 22, 7, 12, 17, 22, 7, 12, 17, 22, 5, 9, 14, 20, 5, 9, 14, 20, 5, 9,
    14, 20, 5, 9, 14, 20, 4, 11, 16, 23, 4, 11, 16, 23, 4, 11, 16, 23, 4, 11, 16, 23, 6, 10, 15,
    21, 6, 10, 15, 21, 6, 10, 15, 21, 6, 10, 15, 21,
];

const MD5_K: [u32; 64] = [
    0xd76a_a478,
    0xe8c7_b756,
    0x2420_70db,
    0xc1bd_ceee,
    0xf57c_0faf,
    0x4787_c62a,
    0xa830_4613,
    0xfd46_9501,
    0x6980_98d8,
    0x8b44_f7af,
    0xffff_5bb1,
    0x895c_d7be,
    0x6b90_1122,
    0xfd98_7193,
    0xa679_438e,
    0x49b4_0821,
    0xf61e_2562,
    0xc040_b340,
    0x265e_5a51,
    0xe9b6_c7aa,
    0xd62f_105d,
    0x0244_1453,
    0xd8a1_e681,
    0xe7d3_fbc8,
    0x21e1_cde6,
    0xc337_07d6,
    0xf4d5_0d87,
    0x455a_14ed,
    0xa9e3_e905,
    0xfcef_a3f8,
    0x676f_02d9,
    0x8d2a_4c8a,
    0xfffa_3942,
    0x8771_f681,
    0x6d9d_6122,
    0xfde5_380c,
    0xa4be_ea44,
    0x4bde_cfa9,
    0xf6bb_4b60,
    0xbebf_bc70,
    0x289b_7ec6,
    0xeaa1_27fa,
    0xd4ef_3085,
    0x0488_1d05,
    0xd9d4_d039,
    0xe6db_99e5,
    0x1fa2_7cf8,
    0xc4ac_5665,
    0xf429_2244,
    0x432a_ff97,
    0xab94_23a7,
    0xfc93_a039,
    0x655b_59c3,
    0x8f0c_cc92,
    0xffef_f47d,
    0x8584_5dd1,
    0x6fa8_7e4f,
    0xfe2c_e6e0,
    0xa301_4314,
    0x4e08_11a1,
    0xf753_7e82,
    0xbd3a_f235,
    0x2ad7_d2bb,
    0xeb86_d391,
];

fn bytes_val(b: &[u8]) -> Value {
    json!({ "$bytes": b })
}

fn extract_seq_prefix(v: &Value, limit: usize, allow_str: bool) -> Result<Vec<u8>, String> {
    if let Value::Object(map) = v {
        if let Some(Value::Array(arr)) = map.get("$bytes")
            && map.len() == 1
        {
            let mut out = Vec::with_capacity(arr.len().min(limit));
            for item in arr.iter().take(limit) {
                let n = item
                    .as_u64()
                    .ok_or_else(|| "TypeError: invalid byte element".to_string())?;
                let byte = u8::try_from(n)
                    .map_err(|_| "ValueError: byte must be in range(0, 256)".to_string())?;
                out.push(byte);
            }
            return Ok(out);
        }
        return Err("KeyError: invalid subscript on dict".to_string());
    }
    if let Value::Array(arr) = v {
        let mut out = Vec::with_capacity(arr.len().min(limit));
        for item in arr.iter().take(limit) {
            let n = item
                .as_i64()
                .ok_or_else(|| "TypeError: unsupported sequence element".to_string())?;
            let byte = u8::try_from(n)
                .map_err(|_| "ValueError: byte must be in range(0, 256)".to_string())?;
            out.push(byte);
        }
        return Ok(out);
    }
    if allow_str && let Value::String(s) = v {
        return Err(if s.is_empty() {
            "IndexError: string index out of range".to_string()
        } else {
            "TypeError: string argument without an encoding".to_string()
        });
    }
    Err("TypeError: object is not subscriptable".to_string())
}

fn extract_bytes_arg(v: &Value) -> Result<Vec<u8>, String> {
    extract_seq_prefix(v, usize::MAX, true)
}

#[inline]
fn xor16(a: &[u8], b: &[u8]) -> [u8; 16] {
    let mut out = [0u8; 16];
    for i in 0..16 {
        out[i] = a[i] ^ b[i];
    }
    out
}

#[inline]
fn read_le_words(b: &[u8]) -> Result<[u32; 4], String> {
    if b.len() < 16 {
        return Err("struct.error: unpack requires a buffer of 16 bytes".to_string());
    }
    Ok([
        u32::from_le_bytes([b[0], b[1], b[2], b[3]]),
        u32::from_le_bytes([b[4], b[5], b[6], b[7]]),
        u32::from_le_bytes([b[8], b[9], b[10], b[11]]),
        u32::from_le_bytes([b[12], b[13], b[14], b[15]]),
    ])
}

#[inline]
fn write_le_word(b: &mut [u8], k: usize, w: u32) {
    let bytes = w.to_le_bytes();
    let off = 4 * k;
    b[off..off + 4].copy_from_slice(&bytes);
}

#[inline]
const fn table_index(i: usize) -> usize {
    ((31 * i) % 0x28) << 8
}

#[inline]
const fn message_table_index(i: usize) -> usize {
    ((97 * i) % 144) << 8
}

#[inline]
const fn permute_table_2(i: usize) -> usize {
    ((71 * i) % 144) << 8
}

fn permute_block_1(b: &mut [u8; 16]) {
    let s3 = tables::TABLE_S3;
    b[0] = s3[usize::from(b[0])];
    b[4] = s3[0x400 + usize::from(b[4])];
    b[8] = s3[0x800 + usize::from(b[8])];
    b[12] = s3[0xC00 + usize::from(b[12])];
    let tmp = b[13];
    b[13] = s3[0x100 + usize::from(b[9])];
    b[9] = s3[0xD00 + usize::from(b[5])];
    b[5] = s3[0x900 + usize::from(b[1])];
    b[1] = s3[0x500 + usize::from(tmp)];
    let tmp = b[2];
    b[2] = s3[0xA00 + usize::from(b[10])];
    b[10] = s3[0x200 + usize::from(tmp)];
    let tmp = b[6];
    b[6] = s3[0xE00 + usize::from(b[14])];
    b[14] = s3[0x600 + usize::from(tmp)];
    let tmp = b[3];
    b[3] = s3[0xF00 + usize::from(b[7])];
    b[7] = s3[0x300 + usize::from(b[11])];
    b[11] = s3[0x700 + usize::from(b[15])];
    b[15] = s3[0xB00 + usize::from(tmp)];
}

fn permute_block_2(b: &mut [u8; 16], rnd: usize) {
    let s4 = tables::TABLE_S4;
    let p = |k: usize, v: u8| -> u8 { s4[permute_table_2(rnd * 16 + k) + usize::from(v)] };
    b[0] = p(0, b[0]);
    b[4] = p(4, b[4]);
    b[8] = p(8, b[8]);
    b[12] = p(12, b[12]);
    let tmp = b[13];
    b[13] = p(13, b[9]);
    b[9] = p(9, b[5]);
    b[5] = p(5, b[1]);
    b[1] = p(1, tmp);
    let tmp = b[2];
    b[2] = p(2, b[10]);
    b[10] = p(10, tmp);
    let tmp = b[6];
    b[6] = p(6, b[14]);
    b[14] = p(14, tmp);
    let tmp = b[3];
    b[3] = p(3, b[7]);
    b[7] = p(7, b[11]);
    b[11] = p(11, b[15]);
    b[15] = p(15, tmp);
}

fn key_schedule_core(key_material: &[u8]) -> Result<[[u32; 4]; 11], String> {
    if key_material.len() < 16 {
        return Err("struct.error: unpack requires a buffer of 16 bytes".to_string());
    }
    let mut buf = xor16(key_material, tables::T_KEY);
    let s1 = tables::TABLE_S1;
    let mut sched = [[0u32; 4]; 11];
    let mut ti = 0usize;
    for (rnd, row_slot) in sched.iter_mut().enumerate() {
        let mut row = [0u32; 4];
        row[0] = u32::from_le_bytes([buf[0], buf[1], buf[2], buf[3]]);
        let (t1, t2, t3, t4) = (
            table_index(ti),
            table_index(ti + 1),
            table_index(ti + 2),
            table_index(ti + 3),
        );
        ti += 4;
        buf[0] ^= s1[t1 + usize::from(buf[0x0D])] ^ tables::INDEX_MANGLE[rnd];
        buf[1] ^= s1[t2 + usize::from(buf[0x0E])];
        buf[2] ^= s1[t3 + usize::from(buf[0x0F])];
        buf[3] ^= s1[t4 + usize::from(buf[0x0C])];
        let mut w = read_le_words(&buf)?;
        row[1] = w[1];
        w[1] ^= w[0];
        row[2] = w[2];
        w[2] ^= w[1];
        row[3] = w[3];
        w[3] ^= w[2];
        for (k, word) in w.iter().enumerate() {
            write_le_word(&mut buf, k, *word);
        }
        *row_slot = row;
    }
    Ok(sched)
}

fn cycle_core(block: &mut [u8; 16], sched: &[[u32; 4]; 11]) {
    let w = [
        u32::from_le_bytes([block[0], block[1], block[2], block[3]]),
        u32::from_le_bytes([block[4], block[5], block[6], block[7]]),
        u32::from_le_bytes([block[8], block[9], block[10], block[11]]),
        u32::from_le_bytes([block[12], block[13], block[14], block[15]]),
    ];
    for (k, word) in w.iter().enumerate() {
        write_le_word(block, k, word ^ sched[10][k]);
    }
    permute_block_1(block);
    for rnd in 0..9 {
        let row = sched[9 - rnd];
        let k0 = row[0].to_le_bytes();
        let ab0 = tables::table_s5(usize::from(block[3] ^ k0[3]))
            ^ tables::table_s6(usize::from(block[2] ^ k0[2]))
            ^ tables::table_s8(usize::from(block[0] ^ k0[0]))
            ^ tables::table_s7(usize::from(block[1] ^ k0[1]));
        write_le_word(block, 0, ab0);

        let k1 = row[1].to_le_bytes();
        let ab1 = tables::table_s6(usize::from(block[6] ^ k1[2]))
            ^ tables::table_s5(usize::from(block[7] ^ k1[3]))
            ^ tables::table_s8(usize::from(block[4] ^ k1[0]))
            ^ tables::table_s7(usize::from(block[5] ^ k1[1]));
        write_le_word(block, 1, ab1);

        let k2 = row[2].to_le_bytes();
        let ab2 = tables::table_s5(usize::from(block[11] ^ k2[3]))
            ^ tables::table_s6(usize::from(block[10] ^ k2[2]))
            ^ tables::table_s7(usize::from(block[9] ^ k2[1]))
            ^ tables::table_s8(usize::from(block[8] ^ k2[0]));
        write_le_word(block, 2, ab2);

        let k3 = row[3].to_le_bytes();
        let ab3 = tables::table_s5(usize::from(block[15] ^ k3[3]))
            ^ tables::table_s6(usize::from(block[14] ^ k3[2]))
            ^ tables::table_s7(usize::from(block[13] ^ k3[1]))
            ^ tables::table_s8(usize::from(block[12] ^ k3[0]));
        write_le_word(block, 3, ab3);

        permute_block_2(block, 8 - rnd);
    }
    let w = [
        u32::from_le_bytes([block[0], block[1], block[2], block[3]]),
        u32::from_le_bytes([block[4], block[5], block[6], block[7]]),
        u32::from_le_bytes([block[8], block[9], block[10], block[11]]),
        u32::from_le_bytes([block[12], block[13], block[14], block[15]]),
    ];
    for (k, word) in w.iter().enumerate() {
        write_le_word(block, k, word ^ sched[0][k]);
    }
}

fn decrypt_message_core(message_in: &[u8]) -> Result<[u8; 128], String> {
    let mode = *message_in
        .get(12)
        .ok_or_else(|| "IndexError: index out of range".to_string())?;
    if mode > 3 {
        return Err(format!("ValueError: unsupported FairPlay mode {mode}"));
    }
    if message_in.len() < 144 {
        return Err("ValueError: FairPlay message too short".to_string());
    }
    let s2 = tables::TABLE_S2;
    let s10 = tables::TABLE_S10;
    let mkey = &tables::MESSAGE_KEY[usize::from(mode) * 144..(usize::from(mode) + 1) * 144];
    let miv = &tables::MESSAGE_IV[usize::from(mode) * 16..(usize::from(mode) + 1) * 16];
    let mut out = [0u8; 128];

    for i in 0..8 {
        let mut buf = [0u8; 16];
        let start = if mode == 3 {
            0x80 - 0x10 * i
        } else {
            0x10 * (i + 1)
        };
        buf.copy_from_slice(&message_in[start..start + 16]);
        for j in 0..9 {
            let base = 0x80 - 0x10 * j;
            let m = |k: usize, v: u8| -> u8 {
                s2[message_table_index(base + k) + usize::from(v)] ^ mkey[base + k]
            };
            buf[0x0] = m(0x0, buf[0x0]);
            buf[0x4] = m(0x4, buf[0x4]);
            buf[0x8] = m(0x8, buf[0x8]);
            buf[0xC] = m(0xC, buf[0xC]);
            let tmp = buf[0x0D];
            buf[0xD] = m(0xD, buf[0x9]);
            buf[0x9] = m(0x9, buf[0x5]);
            buf[0x5] = m(0x5, buf[0x1]);
            buf[0x1] = m(0x1, tmp);
            let tmp = buf[0x02];
            buf[0x2] = m(0x2, buf[0xA]);
            buf[0xA] = m(0xA, tmp);
            let tmp = buf[0x06];
            buf[0x6] = m(0x6, buf[0xE]);
            buf[0xE] = m(0xE, tmp);
            let tmp = buf[0x3];
            buf[0x3] = m(0x3, buf[0x7]);
            buf[0x7] = m(0x7, buf[0xB]);
            buf[0xB] = m(0xB, buf[0xF]);
            buf[0xF] = m(0xF, tmp);
            for k in 0..4 {
                let o = 4 * k;
                let w = tables::table_s9(usize::from(buf[o]))
                    ^ tables::table_s9(0x100 + usize::from(buf[o + 1]))
                    ^ tables::table_s9(0x200 + usize::from(buf[o + 2]))
                    ^ tables::table_s9(0x300 + usize::from(buf[o + 3]));
                write_le_word(&mut buf, k, w);
            }
        }
        buf[0x0] = s10[usize::from(buf[0x0])];
        buf[0x4] = s10[(0x4 << 8) + usize::from(buf[0x4])];
        buf[0x8] = s10[(0x8 << 8) + usize::from(buf[0x8])];
        buf[0xC] = s10[(0xC << 8) + usize::from(buf[0xC])];
        let tmp = buf[0x0D];
        buf[0xD] = s10[(0xD << 8) + usize::from(buf[0x9])];
        buf[0x9] = s10[(0x9 << 8) + usize::from(buf[0x5])];
        buf[0x5] = s10[(0x5 << 8) + usize::from(buf[0x1])];
        buf[0x1] = s10[(0x1 << 8) + usize::from(tmp)];
        let tmp = buf[0x02];
        buf[0x2] = s10[(0x2 << 8) + usize::from(buf[0xA])];
        buf[0xA] = s10[(0xA << 8) + usize::from(tmp)];
        let tmp = buf[0x06];
        buf[0x6] = s10[(0x6 << 8) + usize::from(buf[0xE])];
        buf[0xE] = s10[(0xE << 8) + usize::from(tmp)];
        let tmp = buf[0x3];
        buf[0x3] = s10[(0x3 << 8) + usize::from(buf[0x7])];
        buf[0x7] = s10[(0x7 << 8) + usize::from(buf[0xB])];
        buf[0xB] = s10[(0xB << 8) + usize::from(buf[0xF])];
        buf[0xF] = s10[(0xF << 8) + usize::from(tmp)];

        if mode < 3 {
            let src = if i > 0 {
                &message_in[0x10 * i..0x10 * i + 16]
            } else {
                miv
            };
            for k in 0..16 {
                out[0x10 * i + k] = buf[k] ^ src[k];
            }
        } else {
            let pos = 0x70 - 0x10 * i;
            let src = if i < 7 {
                &message_in[pos..pos + 16]
            } else {
                miv
            };
            for k in 0..16 {
                out[pos + k] = buf[k] ^ src[k];
            }
        }
    }
    Ok(out)
}

fn modified_md5_core(block_in: &[u8], key_in: &[u8]) -> Result<[u8; 16], String> {
    let key_words = read_le_words(key_in)?;
    if block_in.len() < 64 {
        return Err("IndexError: block_in requires at least 64 bytes".to_string());
    }
    let mut blk = [0u8; 64];
    blk.copy_from_slice(&block_in[..64]);
    let (mut a, mut b, mut c, mut d) = (key_words[0], key_words[1], key_words[2], key_words[3]);

    for (i, (&shift, &k)) in MD5_SHIFT.iter().zip(MD5_K.iter()).enumerate() {
        let j = match i {
            0..=15 => i,
            16..=31 => (5 * i + 1) % 16,
            32..=47 => (3 * i + 5) % 16,
            _ => (7 * i) % 16,
        };
        let inp = u32::from_be_bytes([blk[4 * j], blk[4 * j + 1], blk[4 * j + 2], blk[4 * j + 3]]);
        let z = a.wrapping_add(inp).wrapping_add(k);
        let f = match i {
            0..=15 => (b & c) | ((!b) & d),
            16..=31 => (b & d) | (c & (!d)),
            32..=47 => b ^ c ^ d,
            _ => c ^ (b | (!d)),
        };
        let z = z.wrapping_add(f).rotate_left(shift).wrapping_add(b);
        (a, b, c, d) = (d, z, b, c);
        if i == 31 {
            let pairs = [
                (a & 15, b & 15),
                (c & 15, d & 15),
                ((a >> 4) & 15, (b >> 4) & 15),
                ((a >> 8) & 15, (b >> 8) & 15),
                ((a >> 12) & 15, (b >> 12) & 15),
            ];
            for (x, y) in pairs {
                let ix = (x as usize) * 4;
                let iy = (y as usize) * 4;
                for off in 0..4 {
                    blk.swap(ix + off, iy + off);
                }
            }
        }
    }
    let mut out = [0u8; 16];
    let sums = [
        key_words[0].wrapping_add(a),
        key_words[1].wrapping_add(b),
        key_words[2].wrapping_add(c),
        key_words[3].wrapping_add(d),
    ];
    for (idx, word) in sums.iter().enumerate() {
        out[4 * idx..4 * idx + 4].copy_from_slice(&word.to_le_bytes());
    }
    Ok(out)
}

fn sap_hash_core(block_in: &[u8]) -> Result<[u8; 16], String> {
    if block_in.len() < 64 {
        return Err("IndexError: block_in index out of range".to_string());
    }
    let mut buffer0 = *tables::SAP_BUFFER0;
    let mut buffer1 = [0u8; 210];
    let mut buffer2 = *tables::SAP_BUFFER2;
    let mut buffer3 = [0u8; 132];
    let mut buffer4 = *tables::SAP_BUFFER4;

    for (i, slot) in buffer1.iter_mut().enumerate() {
        let w = (i % 64) >> 2;
        *slot = block_in[4 * w + 3 - (i % 4)];
    }
    for i in 0..840usize {
        let x = buffer1[(i.wrapping_sub(155) as u32 as usize) % 210];
        let y = buffer1[(i.wrapping_sub(57) as u32 as usize) % 210];
        let z = buffer1[(i.wrapping_sub(13) as u32 as usize) % 210];
        let w = buffer1[i % 210];
        buffer1[i % 210] = y
            .rotate_left(5)
            .wrapping_add(z.rotate_left(3) ^ w)
            .wrapping_sub(x.rotate_left(7));
    }
    garble::garble(
        &mut buffer0,
        &mut buffer1,
        &mut buffer2,
        &mut buffer3,
        &mut buffer4,
    )?;

    let mut key = [0xE1u8; 16];
    for (i, slot) in key.iter_mut().take(11).enumerate() {
        if i == 3 {
            *slot = 0x3D;
        } else {
            *slot = slot.wrapping_add(buffer3[tables::sap_i0_index(i) * 4]);
        }
    }
    for (i, &b) in buffer0.iter().enumerate() {
        key[i % 16] ^= b;
    }
    for (i, &b) in buffer2.iter().enumerate() {
        key[i % 16] ^= b;
    }
    for (i, &b) in buffer1.iter().enumerate() {
        key[i % 16] ^= b;
    }
    for _ in 0..16 {
        for i in 0..16usize {
            let x = key[(i.wrapping_sub(7) as u32 as usize) % 16];
            let y = key[i % 16];
            let z = key[(i.wrapping_sub(37) as u32 as usize) % 16];
            let w = key[(i.wrapping_sub(177) as u32 as usize) % 16];
            key[i] = x.rotate_left(1) ^ y ^ z.rotate_left(6) ^ w.rotate_left(5);
        }
    }
    Ok(key)
}

fn generate_session_key_core(old_sap: &[u8], message_in: &[u8]) -> Result<[u8; 16], String> {
    let dm = decrypt_message_core(message_in)?;
    if old_sap.len() < 0x100 {
        return Err("ValueError: old_sap buffer too short".to_string());
    }
    let mut new_sap = [0u8; 320];
    new_sap[0x000..0x011].copy_from_slice(tables::STATIC_SOURCE_1);
    new_sap[0x011..0x091].copy_from_slice(&dm);
    new_sap[0x091..0x111].copy_from_slice(&old_sap[0x80..0x100]);
    new_sap[0x111..0x140].copy_from_slice(tables::STATIC_SOURCE_2);

    let mut session_key = *tables::INITIAL_SESSION_KEY;
    for rnd in 0..5 {
        let base = &new_sap[rnd * 64..rnd * 64 + 64];
        let md5 = modified_md5_core(base, &session_key)?;
        let sk = sap_hash_core(base)?;
        let skw = read_le_words(&sk)?;
        let mdw = read_le_words(&md5)?;
        for k in 0..4 {
            write_le_word(&mut session_key, k, skw[k].wrapping_add(mdw[k]));
        }
    }
    for chunk in session_key.as_chunks_mut::<4>().0 {
        chunk.swap(0, 3);
        chunk.swap(1, 2);
    }
    for b in &mut session_key {
        *b ^= 121;
    }
    Ok(session_key)
}

/// Port of `z_xor` (`iphone_mirror/fairplay/playfair.py:23`).
pub fn z_xor(block: Value) -> Result<Value, String> {
    let raw = extract_seq_prefix(&block, 16, true)?;
    let out: Vec<u8> = raw
        .iter()
        .zip(tables::Z_KEY.iter())
        .map(|(a, b)| a ^ b)
        .collect();
    Ok(bytes_val(&out))
}

/// Port of `x_xor` (`iphone_mirror/fairplay/playfair.py:27`).
pub fn x_xor(block: Value) -> Result<Value, String> {
    let raw = extract_seq_prefix(&block, 16, true)?;
    let out: Vec<u8> = raw
        .iter()
        .zip(tables::X_KEY.iter())
        .map(|(a, b)| a ^ b)
        .collect();
    Ok(bytes_val(&out))
}

/// Port of `generate_key_schedule` (`iphone_mirror/fairplay/playfair.py:108`).
pub fn generate_key_schedule(key_material: Value) -> Result<Value, String> {
    let raw = extract_seq_prefix(&key_material, 16, true)?;
    let sched = key_schedule_core(&raw)?;
    Ok(Value::Array(
        sched
            .iter()
            .map(|row| Value::Array(row.iter().map(|&w| json!(w)).collect()))
            .collect(),
    ))
}

/// Port of `decrypt_message` (`iphone_mirror/fairplay/playfair.py:161`).
pub fn decrypt_message(message_in: Value) -> Result<Value, String> {
    let raw = extract_bytes_arg(&message_in)?;
    let out = decrypt_message_core(&raw)?;
    Ok(bytes_val(&out))
}

/// Port of `modified_md5` (`iphone_mirror/fairplay/playfair.py:243`).
pub fn modified_md5(block_in: Value, key_in: Value) -> Result<Value, String> {
    let blk = extract_seq_prefix(&block_in, 64, true)?;
    let key = extract_seq_prefix(&key_in, 16, true)?;
    let out = modified_md5_core(&blk, &key)?;
    Ok(bytes_val(&out))
}

/// Port of `sap_hash` (`iphone_mirror/fairplay/playfair.py:289`).
pub fn sap_hash(block_in: Value) -> Result<Value, String> {
    let blk = extract_bytes_arg(&block_in)?;
    let out = sap_hash_core(&blk)?;
    Ok(bytes_val(&out))
}

/// Port of `generate_session_key` (`iphone_mirror/fairplay/playfair.py:333`).
pub fn generate_session_key(old_sap: Value, message_in: Value) -> Result<Value, String> {
    let msg = extract_bytes_arg(&message_in)?;
    let _dm = decrypt_message_core(&msg)?;
    let sap = extract_bytes_arg(&old_sap)?;
    let out = generate_session_key_core(&sap, &msg)?;
    Ok(bytes_val(&out))
}

/// Port of `playfair_decrypt` (`iphone_mirror/fairplay/playfair.py:355`).
pub fn playfair_decrypt(message3: Vec<u8>, cipher_text: Vec<u8>) -> Result<Vec<u8>, String> {
    if message3.len() != 164 || cipher_text.len() != 72 {
        return Err("ValueError: bad FairPlay input sizes".to_string());
    }
    let chunk1 = &cipher_text[16..32];
    let chunk2 = &cipher_text[56..72];
    let sap_key = generate_session_key_core(tables::DEFAULT_SAP, &message3)?;
    let sched = key_schedule_core(&sap_key)?;
    let mut block = xor16(chunk2, tables::Z_KEY);
    cycle_core(&mut block, &sched);
    let key = xor16(&block, chunk1);
    let tmp = xor16(&key, tables::X_KEY);
    Ok(xor16(&tmp, tables::Z_KEY).to_vec())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn rejects_invalid_sizes_and_modes() {
        assert!(playfair_decrypt(vec![0; 10], vec![0; 72]).is_err());
        assert!(playfair_decrypt(vec![0; 164], vec![0; 10]).is_err());
        let mut msg = vec![0u8; 164];
        msg[12] = 4;
        let err = decrypt_message_core(&msg).unwrap_err();
        assert!(err.contains("unsupported FairPlay mode 4"));
    }

    #[test]
    fn decrypts_modes_zero_to_three() {
        for mode in 0u8..=3 {
            let mut msg = vec![0x42u8; 164];
            msg[12] = mode;
            let ekey = vec![0x11u8; 72];
            let res = playfair_decrypt(msg, ekey);
            assert!(res.is_ok());
            assert_eq!(res.map(|v| v.len()), Ok(16));
        }
    }
}
