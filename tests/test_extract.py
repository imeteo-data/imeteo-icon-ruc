"""Tests for pipeline/extract.py.

The synthetic-GRIB tests build small GRIB2 files with known values via the
eccodes Python bindings, so they run everywhere — including CI, where they
exercise whichever backend is active (the Rust extension when built, the
xarray fallback otherwise) against exact expected values.

The tests below them use real cached GRIBs from data/raw/ and skip when none
are available.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from pipeline import discover, extract

# ── synthetic GRIB fixtures (run everywhere) ───────────────
N_CELLS = 16 * 31  # GRIB2 sample grid


def _write_grib(path: Path, values: list[float], date: int, time: int) -> None:
    import eccodes

    h = eccodes.codes_grib_new_from_samples("GRIB2")
    try:
        eccodes.codes_set(h, "dataDate", date)
        eccodes.codes_set(h, "dataTime", time)
        eccodes.codes_set(h, "stepUnits", "m")
        eccodes.codes_set(h, "forecastTime", 0)
        eccodes.codes_set(h, "bitsPerValue", 24)  # integers must roundtrip exactly
        eccodes.codes_set_values(h, np.array(values, dtype=float))
        with open(path, "wb") as f:
            eccodes.codes_write(h, f)
    finally:
        eccodes.codes_release(h)


@pytest.fixture
def synthetic_run(tmp_path):
    """Two members × two steps of a fake TOT_PREC run with known values."""
    run_id = "2026-07-04T1200"
    for ens in ("01", "02"):
        for step, (date, time) in (
            ("PT000H05M", (20260704, 1205)),
            ("PT000H10M", (20260704, 1210)),
        ):
            values = [float(f"{ens}{step[-3:-1]}") + i for i in range(N_CELLS)]
            name = discover.local_filename("TOT_PREC", run_id, ens, step)
            _write_grib(tmp_path / name, values, date, time)
    return tmp_path


def test_multi_cell_extraction_values_and_times(synthetic_run):
    paths = sorted(synthetic_run.glob("*.grib2"))
    cells = [0, 7]
    per_cell = extract.extract_variable(paths, "TOT_PREC", cells)
    assert len(per_cell) == len(cells)
    for pos, cell in enumerate(cells):
        series = per_cell[pos]
        assert sorted(series) == ["01", "02"]
        for ens, items in series.items():
            times = [t for t, _ in items]
            assert times == [
                np.datetime64("2026-07-04T12:05:00"),
                np.datetime64("2026-07-04T12:10:00"),
            ]
            # value encodes member+step: e.g. member 01, step 05 → 105.0 + cell
            assert [v for _, v in items] == [float(f"{ens}05") + cell, float(f"{ens}10") + cell]


def test_out_of_bounds_cell_is_dropped_without_hurting_others(synthetic_run):
    paths = sorted(synthetic_run.glob("*.grib2"))
    per_cell = extract.extract_variable(paths, "TOT_PREC", [N_CELLS + 5, 3])
    assert per_cell[0] == {}  # out of bounds → empty series
    assert len(per_cell[1]["01"]) == 2  # neighbour cell unaffected


def test_no_matching_files_returns_empty_series_per_cell(tmp_path):
    per_cell = extract.extract_variable([], "TOT_PREC", [0, 1])
    assert per_cell == [{}, {}]


# ── real cached GRIBs (skip when data/raw/ is empty) ───────
def _sample_paths(variable: str, limit: int = 4) -> list[Path]:
    """Pick a handful of real local GRIB files (any run, single ensemble)."""
    local = discover.scan_local_runs()
    for _run_id, by_var in local.items():
        files = by_var.get(variable, [])
        # Keep only ensemble "01" to stay fast
        ens01 = [f for f in files if "_e01_" in f.name]
        if len(ens01) >= limit:
            return ens01[:limit]
    return []


# Use a cell_index known to be inside the ICON-D2 domain (Bratislava area).
# Cell 0 is outside the domain (returns NaN) — that's not what we want to test here.
_VALID_CELL = 100_000


@pytest.mark.skipif(not _sample_paths("TOT_PREC"), reason="no local TOT_PREC GRIB files available")
def test_extract_tot_prec_returns_values_for_valid_cell():
    paths = _sample_paths("TOT_PREC", limit=4)
    result = extract.extract_variable(paths, "TOT_PREC", [_VALID_CELL])[0]
    assert "01" in result
    assert len(result["01"]) == len(paths)
    for _, v in result["01"]:
        assert v >= 0.0


@pytest.mark.skipif(not _sample_paths("VMAX_10M"), reason="no local VMAX_10M GRIB files available")
def test_extract_vmax_returns_values():
    paths = _sample_paths("VMAX_10M", limit=4)
    result = extract.extract_variable(paths, "VMAX_10M", [_VALID_CELL])[0]
    assert "01" in result
    assert len(result["01"]) == len(paths)


def test_extract_skips_files_with_nan_at_cell():
    """Cells outside the ICON domain return NaN and should be silently skipped."""
    paths = _sample_paths("TOT_PREC", limit=2)
    if not paths:
        pytest.skip("no local GRIBs")
    result = extract.extract_variable(paths, "TOT_PREC", [0])[0]
    # Cell 0 is outside the domain -> no values extracted
    assert result == {} or all(len(v) == 0 for v in result.values())


def _all_ens01_paths(variable: str) -> list[Path]:
    local = discover.scan_local_runs()
    for _run_id, by_var in local.items():
        ens01 = [f for f in by_var.get(variable, []) if "_e01_" in f.name]
        if ens01:
            return ens01
    return []


def test_extract_timestamps_land_on_whole_minutes():
    """Valid times must land on whole-minute boundaries (no :59 artifacts).

    cfgrib stores `step` as float hours, so `time + step` for some 5-minute
    steps lands one nanosecond short of the mark (e.g. 13:04:59.999...), which
    truncates to 13:04:59 — one second off the 5-minute grid. That knocks runs
    off the shared time axis and leaves gaps in the dashboard's run-evolution
    chart. Extraction must use cfgrib's exact `valid_time` instead.
    """
    paths = _all_ens01_paths("TOT_PREC")
    if not paths:
        pytest.skip("no local TOT_PREC GRIB files available")
    result = extract.extract_variable(paths, "TOT_PREC", [_VALID_CELL])[0]
    times = [t for series in result.values() for t, _ in series]
    assert times, "expected at least one extracted timestamp"
    off_grid = [str(t) for t in times if int(t.astype("datetime64[s]").astype("int64") % 60) != 0]
    assert not off_grid, f"timestamps not on whole-minute boundary: {off_grid}"
