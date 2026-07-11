"""Multi-point extraction from GRIB files.

Prefers the native `extract_rs` Rust extension (parallel, ~5-10× faster).
Falls back to a pure-Python xarray/cfgrib path if the extension is absent.
Either way each GRIB is decoded once and sampled at every requested cell,
so extraction cost does not grow with the number of dashboard locations.
"""

from __future__ import annotations

import math
from collections import defaultdict
from pathlib import Path

import numpy as np

from . import config, discover

try:
    import extract_rs  # type: ignore

    # The extract_rs/ source directory can be discovered as an empty
    # namespace package (PEP 420) when the compiled wheel isn't installed
    # — e.g. on CI runners. A plain `import` succeeds but the Rust symbols
    # aren't present. Verify the real function exists before using it.
    _RUST_AVAILABLE = hasattr(extract_rs, "extract_points")
except ImportError:
    _RUST_AVAILABLE = False

print(
    f"  extract backend: {'Rust (extract_rs)' if _RUST_AVAILABLE else 'Python (xarray fallback)'}"
)

# One extracted time series per ensemble member: {member_id: [(time, value)]}
Series = dict[str, list[tuple[np.datetime64, float]]]


def _read_points_python(
    path: Path, grib_var: str, cell_indices: list[int]
) -> tuple[np.datetime64, list[float]] | None:
    """Fallback: pure-Python per-file extract using xarray + cfgrib.

    Mirrors the Rust extension's semantics: None for an unreadable file,
    NaN for individual bad cells.
    """
    import xarray as xr  # local import so Rust users don't pay for it

    try:
        ds = xr.open_dataset(path, engine="cfgrib", backend_kwargs={"indexpath": ""})
    except Exception as e:
        print(f"  open failed {path.name}: {e}")
        return None
    try:
        if grib_var not in ds.data_vars:
            grib_var = next(iter(ds.data_vars))
        flat = ds[grib_var].values.flat
        n = ds[grib_var].size
        values = [float(flat[i]) if i < n else math.nan for i in cell_indices]
        # Use cfgrib's exact `valid_time` coordinate. Computing it as
        # `time + step` instead lands one nanosecond short for some sub-hourly
        # steps (cfgrib stores `step` as float hours), so a 13:05:00 frame
        # truncates to 13:04:59 — off the 5-minute grid, leaving gaps in the
        # dashboard's run-evolution chart.
        return ds.valid_time.values, values
    finally:
        ds.close()


def extract_variable(paths: list[Path], variable: str, cell_indices: list[int]) -> list[Series]:
    """Extract per-ensemble point series at each cell from local GRIB files.

    Returns one Series per entry in `cell_indices` (parallel lists), each
    sorted by time. NaN cells (outside the model domain / missing) are
    dropped from their series without affecting the other cells.
    """
    grib_var = config.VARIABLES[variable]["grib_var"]

    # Group paths by ensemble first so we can pair results back to them.
    ens_paths: dict[str, list[Path]] = defaultdict(list)
    for path in paths:
        parsed = discover.parse_filename(path)
        if parsed is None or parsed[0] != variable:
            continue
        _, _, ensemble, _ = parsed
        ens_paths[ensemble].append(path)

    flat = [(ens, p) for ens, ps in ens_paths.items() for p in ps]
    per_cell: list[Series] = [defaultdict(list) for _ in cell_indices]
    if not flat:
        return [dict(s) for s in per_cell]

    if _RUST_AVAILABLE:
        # One parallel Rust call per variable — rayon scales across cores.
        results = extract_rs.extract_points([str(p) for _, p in flat], cell_indices)
        results = ((np.datetime64(int(r[0]), "s"), r[1]) if r else None for r in results)
    else:
        results = (_read_points_python(p, grib_var, cell_indices) for _, p in flat)

    # strict=True is safe on both zips: results is produced 1:1 from `flat`
    # (extract_rs.extract_points returns a Vec parallel to its paths; the
    # Python generator maps over `flat` directly), and both backends return
    # exactly one value per requested cell index.
    for (ensemble, _path), result in zip(flat, results, strict=True):
        if result is None:
            continue
        t, values = result
        for series, value in zip(per_cell, values, strict=True):
            if not math.isnan(value):
                series[ensemble].append((t, value))

    return [{ens: sorted(items) for ens, items in s.items()} for s in per_cell]
