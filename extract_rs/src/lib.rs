//! Fast parallel multi-point extraction from GRIB2 files for icon-ruc.
//!
//! Exposes one Python function: `extract_points(paths, cell_indices)`.
//! Each file is decoded once and sampled at every requested cell, so adding
//! dashboard locations costs nothing beyond the array lookups.

use eccodes::{CodesFile, FallibleIterator, KeyRead, ProductKind};
use pyo3::prelude::*;
use rayon::prelude::*;
use std::path::Path;

/// Read (timestamp_seconds, values at `cell_indices`) from one GRIB file.
///
/// Returns None when the file can't be decoded. Per-cell failures
/// (out-of-bounds, NaN, DWD's missing-value sentinel) become NaN in the
/// returned vector so one bad cell doesn't discard the others.
///
/// Files are pre-filtered by filename so each contains exactly one message
/// for the right variable; shortName is never checked — DWD-specific
/// variables (e.g. max_i10fg, paramId 237318) resolve to "unknown" on
/// systems without DWD's eccodes definition tables.
fn extract_one(path: &str, cell_indices: &[usize]) -> Option<(i64, Vec<f64>)> {
    let mut handle = CodesFile::new_from_file(Path::new(path), ProductKind::GRIB).ok()?;
    let mut iter = handle.ref_message_iter();
    let msg = match iter.next() {
        Ok(Some(m)) => m,
        _ => return None,
    };

    let vdate: i64 = msg.read_key("validityDate").ok()?;
    let vtime: i64 = msg.read_key("validityTime").ok()?;
    let epoch = civil_to_unix(
        (vdate / 10000) as i32,
        ((vdate / 100) % 100) as u32,
        (vdate % 100) as u32,
        (vtime / 100) as u32,
        (vtime % 100) as u32,
    );

    let values: Vec<f64> = msg.read_key("values").ok()?;
    // DWD uses 9999.0 as a missing-value sentinel outside the model domain.
    let missing: f64 = msg.read_key("missingValue").unwrap_or(9999.0);
    let picked = cell_indices
        .iter()
        .map(|&i| match values.get(i) {
            Some(&v) if !v.is_nan() && (v - missing).abs() >= 1e-6 => v,
            _ => f64::NAN,
        })
        .collect();
    Some((epoch, picked))
}

/// Howard Hinnant's days_from_civil algorithm, to UNIX seconds.
fn civil_to_unix(y: i32, m: u32, d: u32, h: u32, mn: u32) -> i64 {
    let (y, m) = if m <= 2 { (y - 1, m + 12) } else { (y, m) };
    let era = if y >= 0 { y } else { y - 399 } / 400;
    let yoe = (y - era * 400) as i64;
    let m = m as i64;
    let d = d as i64;
    let doy = (153 * (m - 3) + 2) / 5 + d - 1;
    let doe = yoe * 365 + yoe / 4 - yoe / 100 + doy;
    let days = era as i64 * 146097 + doe - 719468;
    days * 86400 + (h as i64) * 3600 + (mn as i64) * 60
}

/// Extract (timestamp_seconds, [value at each cell_index]) from each path.
/// Returns a list parallel to `paths`; unreadable files are None, individual
/// bad cells are NaN.
#[pyfunction]
#[pyo3(signature = (paths, cell_indices))]
fn extract_points(
    py: Python<'_>,
    paths: Vec<String>,
    cell_indices: Vec<usize>,
) -> PyResult<Vec<Option<(i64, Vec<f64>)>>> {
    py.allow_threads(|| {
        let out: Vec<Option<(i64, Vec<f64>)>> = paths
            .par_iter()
            .map(|p| extract_one(p, &cell_indices))
            .collect();
        Ok(out)
    })
}

#[pymodule]
fn extract_rs(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(extract_points, m)?)?;
    Ok(())
}
