"""Tests for the derived WIND_10M variable (run._magnitude_series + the
DERIVED_VARIABLES config path through stats.build_variable_output)."""
from __future__ import annotations

import numpy as np

from pipeline import run, stats


def _series(values: list[float]) -> list[tuple[np.datetime64, float]]:
    t0 = np.datetime64("2025-01-01T00:00:00")
    return [(t0 + np.timedelta64(i * 60, "m"), v) for i, v in enumerate(values)]


def test_magnitude_series_is_per_member_hypot():
    u = {"01": _series([3.0, 0.0]), "02": _series([1.0, 5.0])}
    v = {"01": _series([4.0, 5.0]), "02": _series([0.0, 12.0])}
    out = run._magnitude_series(u, v)
    # hypot(3,4)=5, hypot(0,5)=5, hypot(1,0)=1, hypot(5,12)=13
    assert [val for _, val in out["01"]] == [5.0, 5.0]
    assert [val for _, val in out["02"]] == [1.0, 13.0]


def test_magnitude_series_keeps_only_shared_timestamps():
    u = {"01": _series([3.0, 3.0, 3.0])}      # t0, t1, t2
    v = {"01": _series([4.0, 4.0])}           # t0, t1 only
    out = run._magnitude_series(u, v)
    assert len(out["01"]) == 2  # t2 has no V component → dropped


def test_build_variable_output_resolves_derived_config():
    # WIND_10M lives in DERIVED_VARIABLES, not VARIABLES — build_variable_output
    # must still find its unit/thresholds.
    series = {"01": _series([3.0, 4.0]), "02": _series([6.0, 8.0])}
    out = stats.build_variable_output(series, "WIND_10M")
    assert out["unit"] == "m/s"
    # not accumulated, no skip_first_step → both timestamps kept
    assert len(out["times"]) == 2
    # p50 at t0 of [3, 6] = 4.5
    assert out["percentiles"]["p50"][0] == 4.5
    assert set(out["probability_exceeds"]) == {"3.0", "5.0", "8.0", "12.0"}
