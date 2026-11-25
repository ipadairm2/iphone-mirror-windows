//! Python bindings for `iphone_mirror/stream_ops/`: generated from the signatures in `port.rs` by rust-anything.
//! Regenerate with `rust-anything refresh` after changing them.

#![allow(clippy::too_many_arguments)]

use pyo3::prelude::*;

pub mod js;
pub mod port;
pub mod pyconv;
pub mod pynum;

#[allow(unused_imports)]
use pynum::Num;

fn error(message: String) -> PyErr {
    use pyo3::exceptions as e;
    /// `Err("Kind: text")` for a `Kind` the match below does not know: a built-in exception's name or
    /// `package.module.Class`, called with the text. None when it names no `Exception` subclass or the
    /// class cannot be made from the text alone (its constructor takes more arguments).
    fn named_error(kind: &str, text: &str) -> Option<PyErr> {
        Python::attach(|py| {
            // Each dotted part must be a Python identifier, by Python's own rules (`str.isidentifier`).
            let identifier = |part: &str| {
                pyo3::types::PyString::new(py, part)
                    .call_method0("isidentifier")
                    .and_then(|ok| ok.extract::<bool>())
                    .unwrap_or(false)
            };
            if !kind.split('.').all(identifier) {
                return None;
            }
            let (module, name) = kind.rsplit_once('.').unwrap_or(("builtins", kind));
            let class = py.import(module).ok()?.getattr(name).ok()?;
            let class = class.cast_into::<pyo3::types::PyType>().ok()?;
            if !class
                .is_subclass_of::<pyo3::exceptions::PyException>()
                .ok()?
            {
                return None;
            }
            let value = class.call1((text,)).ok()?;
            if !value.is_instance(&class).ok()? {
                return None;
            }
            Some(PyErr::from_value(value))
        })
    }
    let (kind, text) = message.split_once(": ").unwrap_or(("", message.as_str()));
    let text = text.to_string();
    match kind {
        "TypeError" => e::PyTypeError::new_err(text),
        "KeyError" => e::PyKeyError::new_err(text),
        "IndexError" => e::PyIndexError::new_err(text),
        "OverflowError" => e::PyOverflowError::new_err(text),
        "ZeroDivisionError" => e::PyZeroDivisionError::new_err(text),
        "AttributeError" => e::PyAttributeError::new_err(text),
        "RuntimeError" => e::PyRuntimeError::new_err(text),
        "NotImplementedError" => e::PyNotImplementedError::new_err(text),
        "LookupError" => e::PyLookupError::new_err(text),
        "ArithmeticError" => e::PyArithmeticError::new_err(text),
        "UnicodeError" => e::PyUnicodeError::new_err(text),
        "ValueError" => e::PyValueError::new_err(text),
        _ => named_error(kind, &text).unwrap_or_else(|| e::PyValueError::new_err(message)),
    }
}

fn avcc_to_annexb_inner(data: Bound<'_, PyAny>) -> Result<Option<Vec<u8>>, String> {
    let data: Vec<u8> = crate::pyconv::FromPy::from_py(&data)?;
    let out = port::avcc_to_annexb(data)?;
    Ok(out)
}

/// `avcc_to_annexb`.
#[pyfunction]
#[pyo3(name = "avcc_to_annexb", signature = (data))]
fn avcc_to_annexb(py: Python<'_>, data: Bound<'_, PyAny>) -> PyResult<Py<PyAny>> {
    avcc_to_annexb_inner(data)
        .map_err(error)
        .and_then(|v| crate::pyconv::ToPy::to_py(&v, py))
}

fn decrypt_mirror_nal_inner(
    key: Bound<'_, PyAny>,
    iv: Bound<'_, PyAny>,
    offset: i64,
    payload: Bound<'_, PyAny>,
) -> Result<Option<Vec<u8>>, String> {
    let key: Vec<u8> = crate::pyconv::FromPy::from_py(&key)?;
    let iv: Vec<u8> = crate::pyconv::FromPy::from_py(&iv)?;
    let payload: Vec<u8> = crate::pyconv::FromPy::from_py(&payload)?;
    let out = port::decrypt_mirror_nal(key, iv, offset, payload)?;
    Ok(out)
}

/// `decrypt_mirror_nal`.
#[pyfunction]
#[pyo3(name = "decrypt_mirror_nal", signature = (key, iv, offset, payload))]
fn decrypt_mirror_nal(
    py: Python<'_>,
    key: Bound<'_, PyAny>,
    iv: Bound<'_, PyAny>,
    offset: i64,
    payload: Bound<'_, PyAny>,
) -> PyResult<Py<PyAny>> {
    decrypt_mirror_nal_inner(key, iv, offset, payload)
        .map_err(error)
        .and_then(|v| crate::pyconv::ToPy::to_py(&v, py))
}

fn parse_avcc_config_inner(payload: Bound<'_, PyAny>) -> Result<Option<Vec<u8>>, String> {
    let payload: Vec<u8> = crate::pyconv::FromPy::from_py(&payload)?;
    let out = port::parse_avcc_config(payload)?;
    Ok(out)
}

/// `parse_avcc_config`.
#[pyfunction]
#[pyo3(name = "parse_avcc_config", signature = (payload))]
fn parse_avcc_config(py: Python<'_>, payload: Bound<'_, PyAny>) -> PyResult<Py<PyAny>> {
    parse_avcc_config_inner(payload)
        .map_err(error)
        .and_then(|v| crate::pyconv::ToPy::to_py(&v, py))
}

fn decrypt_audio_rtp_inner(
    key: Bound<'_, PyAny>,
    iv: Bound<'_, PyAny>,
    pkt: Bound<'_, PyAny>,
    last_seq: i64,
) -> Result<Option<(i64, Vec<u8>)>, String> {
    let key: Vec<u8> = crate::pyconv::FromPy::from_py(&key)?;
    let iv: Vec<u8> = crate::pyconv::FromPy::from_py(&iv)?;
    let pkt: Vec<u8> = crate::pyconv::FromPy::from_py(&pkt)?;
    let out = port::decrypt_audio_rtp(key, iv, pkt, last_seq)?;
    Ok(out)
}

/// `decrypt_audio_rtp`.
#[pyfunction]
#[pyo3(name = "decrypt_audio_rtp", signature = (key, iv, pkt, last_seq))]
fn decrypt_audio_rtp(
    py: Python<'_>,
    key: Bound<'_, PyAny>,
    iv: Bound<'_, PyAny>,
    pkt: Bound<'_, PyAny>,
    last_seq: i64,
) -> PyResult<Py<PyAny>> {
    decrypt_audio_rtp_inner(key, iv, pkt, last_seq)
        .map_err(error)
        .and_then(|v| crate::pyconv::ToPy::to_py(&v, py))
}

fn scale_pcm_i16_inner(pcm: Bound<'_, PyAny>, gain: f64) -> Result<Vec<u8>, String> {
    let pcm: Vec<u8> = crate::pyconv::FromPy::from_py(&pcm)?;
    let out = port::scale_pcm_i16(pcm, gain)?;
    Ok(out)
}

/// `scale_pcm_i16`.
#[pyfunction]
#[pyo3(name = "scale_pcm_i16", signature = (pcm, gain))]
fn scale_pcm_i16(py: Python<'_>, pcm: Bound<'_, PyAny>, gain: f64) -> PyResult<Py<PyAny>> {
    scale_pcm_i16_inner(pcm, gain)
        .map_err(error)
        .and_then(|v| crate::pyconv::ToPy::to_py(&v, py))
}

fn visible_size_inner(
    frame_w: i64,
    frame_h: i64,
    vis_w: i64,
    vis_h: i64,
) -> Result<(i64, i64), String> {
    let out = port::visible_size(frame_w, frame_h, vis_w, vis_h)?;
    Ok(out)
}

/// `visible_size`.
#[pyfunction]
#[pyo3(name = "visible_size", signature = (frame_w, frame_h, vis_w, vis_h))]
fn visible_size(
    py: Python<'_>,
    frame_w: i64,
    frame_h: i64,
    vis_w: i64,
    vis_h: i64,
) -> PyResult<Py<PyAny>> {
    visible_size_inner(frame_w, frame_h, vis_w, vis_h)
        .map_err(error)
        .and_then(|v| crate::pyconv::ToPy::to_py(&v, py))
}

fn encode_txt_records_inner(keys: Vec<String>, values: Vec<String>) -> Result<Vec<u8>, String> {
    let out = port::encode_txt_records(keys, values)?;
    Ok(out)
}

/// `encode_txt_records`.
#[pyfunction]
#[pyo3(name = "encode_txt_records", signature = (keys, values))]
fn encode_txt_records(
    py: Python<'_>,
    keys: Vec<String>,
    values: Vec<String>,
) -> PyResult<Py<PyAny>> {
    encode_txt_records_inner(keys, values)
        .map_err(error)
        .and_then(|v| crate::pyconv::ToPy::to_py(&v, py))
}

#[pymodule]
#[pyo3(name = "_native")]
fn native_module(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(avcc_to_annexb, m)?)?;
    m.add_function(wrap_pyfunction!(decrypt_mirror_nal, m)?)?;
    m.add_function(wrap_pyfunction!(parse_avcc_config, m)?)?;
    m.add_function(wrap_pyfunction!(decrypt_audio_rtp, m)?)?;
    m.add_function(wrap_pyfunction!(scale_pcm_i16, m)?)?;
    m.add_function(wrap_pyfunction!(visible_size, m)?)?;
    m.add_function(wrap_pyfunction!(encode_txt_records, m)?)?;
    Ok(())
}
