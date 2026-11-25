//! Binary lookup tables for FairPlay SAP decryption, embedded at compile time.

pub const MESSAGE_KEY: &[u8; 576] = include_bytes!("../../data/message_key.bin");
pub const MESSAGE_IV: &[u8; 64] = include_bytes!("../../data/message_iv.bin");
pub const Z_KEY: &[u8; 16] = include_bytes!("../../data/z_key.bin");
pub const X_KEY: &[u8; 16] = include_bytes!("../../data/x_key.bin");
pub const T_KEY: &[u8; 16] = include_bytes!("../../data/t_key.bin");
pub const TABLE_S1: &[u8; 10240] = include_bytes!("../../data/table_s1.bin");
pub const TABLE_S2: &[u8; 36864] = include_bytes!("../../data/table_s2.bin");
pub const TABLE_S3: &[u8; 4096] = include_bytes!("../../data/table_s3.bin");
pub const TABLE_S4: &[u8; 36864] = include_bytes!("../../data/table_s4.bin");
pub const TABLE_S10: &[u8; 4096] = include_bytes!("../../data/table_s10.bin");
pub const INDEX_MANGLE: &[u8; 11] = include_bytes!("../../data/index_mangle.bin");
pub const INITIAL_SESSION_KEY: &[u8; 16] = include_bytes!("../../data/initial_session_key.bin");
pub const STATIC_SOURCE_1: &[u8; 17] = include_bytes!("../../data/static_source_1.bin");
pub const STATIC_SOURCE_2: &[u8; 47] = include_bytes!("../../data/static_source_2.bin");
pub const DEFAULT_SAP: &[u8; 276] = include_bytes!("../../data/default_sap.bin");
pub const SAP_BUFFER0: &[u8; 20] = include_bytes!("../../data/sap_buffer0.bin");
pub const SAP_BUFFER2: &[u8; 35] = include_bytes!("../../data/sap_buffer2.bin");
pub const SAP_BUFFER4: &[u8; 21] = include_bytes!("../../data/sap_buffer4.bin");

const TABLE_S5_BYTES: &[u8; 1024] = include_bytes!("../../data/table_s5.bin");
const TABLE_S6_BYTES: &[u8; 1024] = include_bytes!("../../data/table_s6.bin");
const TABLE_S7_BYTES: &[u8; 1024] = include_bytes!("../../data/table_s7.bin");
const TABLE_S8_BYTES: &[u8; 1024] = include_bytes!("../../data/table_s8.bin");
const TABLE_S9_BYTES: &[u8; 4096] = include_bytes!("../../data/table_s9.bin");
const SAP_I0_BYTES: &[u8; 44] = include_bytes!("../../data/sap_i0_index.bin");

#[inline]
fn read_u32(bytes: &[u8], idx: usize) -> u32 {
    let off = idx * 4;
    u32::from_le_bytes([bytes[off], bytes[off + 1], bytes[off + 2], bytes[off + 3]])
}

#[inline]
pub fn table_s5(idx: usize) -> u32 {
    read_u32(TABLE_S5_BYTES, idx)
}

#[inline]
pub fn table_s6(idx: usize) -> u32 {
    read_u32(TABLE_S6_BYTES, idx)
}

#[inline]
pub fn table_s7(idx: usize) -> u32 {
    read_u32(TABLE_S7_BYTES, idx)
}

#[inline]
pub fn table_s8(idx: usize) -> u32 {
    read_u32(TABLE_S8_BYTES, idx)
}

#[inline]
pub fn table_s9(idx: usize) -> u32 {
    read_u32(TABLE_S9_BYTES, idx)
}

#[inline]
pub fn sap_i0_index(idx: usize) -> usize {
    read_u32(SAP_I0_BYTES, idx) as usize
}
