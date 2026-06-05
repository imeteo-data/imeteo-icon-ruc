"""Single-point extraction from GRIB files.

Prefers the native `extract_rs` Rust extension (parallel, ~5-10× faster).
Falls back to a pure-Python xarray/cfgrib path if the extension is absent.
"""
from __future__ import annotations

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


def _read_point_python(path: Path, grib_var: str, cell_index: int
                       ) -> tuple[np.datetime64, float] | None:
    """Fallback: pure-Python per-file extract using xarray + cfgrib."""
    import xarray as xr  # local import so Rust users don't pay for it
    try:
        ds = xr.open_dataset(path, engine="cfgrib",
                             backend_kwargs={"indexpath": ""})
    except Exception as e:
        print(f"  open failed {path.name}: {e}")
        return None
    try:
        if grib_var not in ds.data_vars:
            grib_var = next(iter(ds.data_vars))
        arr = ds[grib_var].values
        value = float(arr.flat[cell_index])
        if np.isnan(value):
            return None
        # Use cfgrib's exact `valid_time` coordinate. Computing it as
        # `time + step` instead lands one nanosecond short for some sub-hourly
        # steps (cfgrib stores `step` as float hours), so a 13:05:00 frame
        # truncates to 13:04:59 — off the 5-minute grid, leaving gaps in the
        # dashboard's run-evolution chart.
        return ds.valid_time.values, value
    finally:
        ds.close()


def extract_variable(paths: list[Path], variable: str, cell_index: int
                     ) -> dict[str, list[tuple[np.datetime64, float]]]:
    """Extract point series per ensemble from local GRIB files.

    Returns {ensemble_id: [(time, value), ...]} sorted by time.
    Uses the Rust extension if available; otherwise falls back to xarray.
    """
    grib_var = config.VARIABLES[variable]["grib_var"]
    by_ens: dict[str, list[tuple[np.datetime64, float]]] = defaultdict(list)

    # Group paths by ensemble first so we can pair Rust results back to them.
    ens_paths: dict[str, list[Path]] = defaultdict(list)
    for path in paths:
        parsed = discover.parse_filename(path)
        if parsed is None or parsed[0] != variable:
            continue
        _, _, ensemble, _ = parsed
        ens_paths[ensemble].append(path)

    if _RUST_AVAILABLE:
        # One parallel Rust call per variable — rayon scales across cores.
        flat = [(ens, p) for ens, ps in ens_paths.items() for p in ps]
        if not flat:
            return {}
        results = extract_rs.extract_points(
            [str(p) for _, p in flat], cell_index, grib_var
        )
        for (ensemble, _path), result in zip(flat, results):
            if result is None:
                continue
            epoch_s, value = result
            t = np.datetime64(int(epoch_s), "s")
            by_ens[ensemble].append((t, value))
    else:
        for ensemble, ps in ens_paths.items():
            for path in ps:
                result = _read_point_python(path, grib_var, cell_index)
                if result is None:
                    continue
                by_ens[ensemble].append(result)

    return {ens: sorted(items, key=lambda x: x[0]) for ens, items in by_ens.items()}
