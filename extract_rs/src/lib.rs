//! Fast parallel single-point extraction from GRIB2 files for icon-ruc.
//!
//! Exposes one Python function: `extract_points(paths, cell_index, grib_var)`.

use eccodes::{CodesFile, FallibleIterator, KeyRead, ProductKind};
use pyo3::prelude::*;
use rayon::prelude::*;
use std::path::Path;

/// Read one (timestamp_seconds, value) for the named variable at `cell_index`.
/// Returns None on any failure, out-of-bounds, or NaN/missing value.
///
/// Files are pre-filtered by filename so each contains exactly one message
/// for the right variable. We extract the first message without checking
/// shortName — DWD-specific variables (e.g. max_i10fg, paramId 237318) resolve
/// to "unknown" on systems without DWD's eccodes definition tables.
fn extract_one(path: &str, cell_index: usize, _grib_var: &str) -> Option<(i64, f64)> {
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
    if cell_index >= values.len() {
        return None;
    }
    let v = values[cell_index];
    if v.is_nan() {
        return None;
    }
    // DWD uses 9999.0 as a missing-value sentinel outside the model domain.
    let missing: f64 = msg.read_key("missingValue").unwrap_or(9999.0);
    if (v - missing).abs() < 1e-6 {
        return None;
    }
    Some((epoch, v))
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

/// Extract (timestamp_seconds, value) for `grib_var` at `cell_index` from each path.
/// Returns a list parallel to `paths`. Entries for failed/NaN/missing files are None.
#[pyfunction]
#[pyo3(signature = (paths, cell_index, grib_var))]
fn extract_points(
    py: Python<'_>,
    paths: Vec<String>,
    cell_index: usize,
    grib_var: String,
) -> PyResult<Vec<Option<(i64, f64)>>> {
    py.allow_threads(|| {
        let out: Vec<Option<(i64, f64)>> = paths
            .par_iter()
            .map(|p| extract_one(p, cell_index, &grib_var))
            .collect();
        Ok(out)
    })
}

#[pymodule]
fn extract_rs(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(extract_points, m)?)?;
    Ok(())
}
