//! Python bindings for `iphone_mirror/fairplay/`: generated from the signatures in `port.rs` by rust-anything.
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

fn z_xor_inner(block: Bound<'_, PyAny>) -> Result<serde_json::Value, String> {
    let block: serde_json::Value = crate::pyconv::FromPy::from_py(&block)?;
    let out = port::z_xor(block)?;
    Ok(out)
}

/// `z_xor`.
#[pyfunction]
#[pyo3(name = "z_xor", signature = (block))]
fn z_xor(py: Python<'_>, block: Bound<'_, PyAny>) -> PyResult<Py<PyAny>> {
    z_xor_inner(block)
        .map_err(error)
        .and_then(|v| crate::pyconv::ToPy::to_py(&v, py))
}

fn x_xor_inner(block: Bound<'_, PyAny>) -> Result<serde_json::Value, String> {
    let block: serde_json::Value = crate::pyconv::FromPy::from_py(&block)?;
    let out = port::x_xor(block)?;
    Ok(out)
}

/// `x_xor`.
#[pyfunction]
#[pyo3(name = "x_xor", signature = (block))]
fn x_xor(py: Python<'_>, block: Bound<'_, PyAny>) -> PyResult<Py<PyAny>> {
    x_xor_inner(block)
        .map_err(error)
        .and_then(|v| crate::pyconv::ToPy::to_py(&v, py))
}

fn generate_key_schedule_inner(
    key_material: Bound<'_, PyAny>,
) -> Result<serde_json::Value, String> {
    let key_material: serde_json::Value = crate::pyconv::FromPy::from_py(&key_material)?;
    let out = port::generate_key_schedule(key_material)?;
    Ok(out)
}

/// `generate_key_schedule`.
#[pyfunction]
#[pyo3(name = "generate_key_schedule", signature = (key_material))]
fn generate_key_schedule(py: Python<'_>, key_material: Bound<'_, PyAny>) -> PyResult<Py<PyAny>> {
    generate_key_schedule_inner(key_material)
        .map_err(error)
        .and_then(|v| crate::pyconv::ToPy::to_py(&v, py))
}

fn decrypt_message_inner(message_in: Bound<'_, PyAny>) -> Result<serde_json::Value, String> {
    let message_in: serde_json::Value = crate::pyconv::FromPy::from_py(&message_in)?;
    let out = port::decrypt_message(message_in)?;
    Ok(out)
}

/// `decrypt_message`.
#[pyfunction]
#[pyo3(name = "decrypt_message", signature = (message_in))]
fn decrypt_message(py: Python<'_>, message_in: Bound<'_, PyAny>) -> PyResult<Py<PyAny>> {
    decrypt_message_inner(message_in)
        .map_err(error)
        .and_then(|v| crate::pyconv::ToPy::to_py(&v, py))
}

fn modified_md5_inner(
    block_in: Bound<'_, PyAny>,
    key_in: Bound<'_, PyAny>,
) -> Result<serde_json::Value, String> {
    let block_in: serde_json::Value = crate::pyconv::FromPy::from_py(&block_in)?;
    let key_in: serde_json::Value = crate::pyconv::FromPy::from_py(&key_in)?;
    let out = port::modified_md5(block_in, key_in)?;
    Ok(out)
}

/// `modified_md5`.
#[pyfunction]
#[pyo3(name = "modified_md5", signature = (block_in, key_in))]
fn modified_md5(
    py: Python<'_>,
    block_in: Bound<'_, PyAny>,
    key_in: Bound<'_, PyAny>,
) -> PyResult<Py<PyAny>> {
    modified_md5_inner(block_in, key_in)
        .map_err(error)
        .and_then(|v| crate::pyconv::ToPy::to_py(&v, py))
}

fn sap_hash_inner(block_in: Bound<'_, PyAny>) -> Result<serde_json::Value, String> {
    let block_in: serde_json::Value = crate::pyconv::FromPy::from_py(&block_in)?;
    let out = port::sap_hash(block_in)?;
    Ok(out)
}

/// `sap_hash`.
#[pyfunction]
#[pyo3(name = "sap_hash", signature = (block_in))]
fn sap_hash(py: Python<'_>, block_in: Bound<'_, PyAny>) -> PyResult<Py<PyAny>> {
    sap_hash_inner(block_in)
        .map_err(error)
        .and_then(|v| crate::pyconv::ToPy::to_py(&v, py))
}

fn generate_session_key_inner(
    old_sap: Bound<'_, PyAny>,
    message_in: Bound<'_, PyAny>,
) -> Result<serde_json::Value, String> {
    let old_sap: serde_json::Value = crate::pyconv::FromPy::from_py(&old_sap)?;
    let message_in: serde_json::Value = crate::pyconv::FromPy::from_py(&message_in)?;
    let out = port::generate_session_key(old_sap, message_in)?;
    Ok(out)
}

/// `generate_session_key`.
#[pyfunction]
#[pyo3(name = "generate_session_key", signature = (old_sap, message_in))]
fn generate_session_key(
    py: Python<'_>,
    old_sap: Bound<'_, PyAny>,
    message_in: Bound<'_, PyAny>,
) -> PyResult<Py<PyAny>> {
    generate_session_key_inner(old_sap, message_in)
        .map_err(error)
        .and_then(|v| crate::pyconv::ToPy::to_py(&v, py))
}

fn playfair_decrypt_inner(
    message3: Bound<'_, PyAny>,
    cipher_text: Bound<'_, PyAny>,
) -> Result<Vec<u8>, String> {
    let message3: Vec<u8> = crate::pyconv::FromPy::from_py(&message3)?;
    let cipher_text: Vec<u8> = crate::pyconv::FromPy::from_py(&cipher_text)?;
    let out = port::playfair_decrypt(message3, cipher_text)?;
    Ok(out)
}

/// `playfair_decrypt`.
#[pyfunction]
#[pyo3(name = "playfair_decrypt", signature = (message3, cipher_text))]
fn playfair_decrypt(
    py: Python<'_>,
    message3: Bound<'_, PyAny>,
    cipher_text: Bound<'_, PyAny>,
) -> PyResult<Py<PyAny>> {
    playfair_decrypt_inner(message3, cipher_text)
        .map_err(error)
        .and_then(|v| crate::pyconv::ToPy::to_py(&v, py))
}

#[pymodule]
#[pyo3(name = "_native")]
fn native_module(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(z_xor, m)?)?;
    m.add_function(wrap_pyfunction!(x_xor, m)?)?;
    m.add_function(wrap_pyfunction!(generate_key_schedule, m)?)?;
    m.add_function(wrap_pyfunction!(decrypt_message, m)?)?;
    m.add_function(wrap_pyfunction!(modified_md5, m)?)?;
    m.add_function(wrap_pyfunction!(sap_hash, m)?)?;
    m.add_function(wrap_pyfunction!(generate_session_key, m)?)?;
    m.add_function(wrap_pyfunction!(playfair_decrypt, m)?)?;
    Ok(())
}
