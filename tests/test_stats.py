"""Tests for pipeline/stats.py."""
from __future__ import annotations

import numpy as np

from pipeline import stats


def _series(ens_id: str, starts: list[float]) -> list[tuple[np.datetime64, float]]:
    t0 = np.datetime64("2025-01-01T00:00:00")
    # 5-minute spacing matches TOT_PREC's native cadence (config.step_minutes).
    return [(t0 + np.timedelta64(i * 5, "m"), v) for i, v in enumerate(starts)]


def test_align_keeps_shared_timestamps_only():
    s = {
        "01": _series("01", [0.0, 1.0, 2.0]),
        "02": _series("02", [0.0, 1.0, 2.0, 3.0]),
    }
    times, matrix, ens_ids = stats._align_ensembles(s)
    assert list(ens_ids) == ["01", "02"]
    assert times.shape == (3,)
    assert matrix.shape == (2, 3)
    assert matrix[1, 2] == 2.0


def test_deaccumulate_converts_cumulative_to_hourly_rate():
    matrix = np.array([[0.0, 0.5, 1.0, 2.0]])
    rates = stats._deaccumulate(matrix, step_minutes=15)
    # diffs: [0, 0.5, 0.5, 1.0] * (60/15) = [0, 2, 2, 4]
    np.testing.assert_allclose(rates[0], [0.0, 2.0, 2.0, 4.0])


def test_deaccumulate_clips_negative_to_zero():
    matrix = np.array([[5.0, 3.0, 8.0]])
    rates = stats._deaccumulate(matrix, step_minutes=60)
    # diffs: [0, -2, 5] clipped to [0, 0, 5] * 1.0
    np.testing.assert_allclose(rates[0], [0.0, 0.0, 5.0])


def test_build_variable_output_instantaneous_var():
    # VMAX_10M has skip_first_step=True — first timestamp is dropped.
    series = {
        "01": _series("01", [5.0, 6.0, 7.0]),
        "02": _series("02", [10.0, 12.0, 14.0]),
    }
    out = stats.build_variable_output(series, "VMAX_10M")
    assert out["unit"] == "m/s"
    assert len(out["times"]) == 2  # step 0 dropped
    # After dropping t0: values at remaining t0 are [6,12] → median 9.0
    assert out["percentiles"]["p50"][0] == 9.0
    # Both still >= 5
    assert out["probability_exceeds"]["5.0"][0] == 1.0


def test_build_variable_output_accumulated_deaccumulated():
    # Accumulated TOT_PREC in mm; 5-minute steps => rates in mm/h = diff * 12
    series = {
        "01": _series("01", [0.0, 0.25, 0.5, 0.75]),
        "02": _series("02", [0.0, 0.0, 0.0, 1.0]),
    }
    out = stats.build_variable_output(series, "TOT_PREC")
    # ensemble 01: rates [0, 3, 3, 3] mm/h; ensemble 02: [0, 0, 0, 12] mm/h
    # At t3: values [3.0, 12.0], median=7.5
    assert out["percentiles"]["p50"][3] == 7.5
    # At t3: prob(>=1 mm/h) = 1.0 (both >= 1); prob(>=5) = 0.5 (only 12 >= 5)
    assert out["probability_exceeds"]["1.0"][3] == 1.0
    assert out["probability_exceeds"]["5.0"][3] == 0.5


def test_empty_input_returns_empty_shape():
    out = stats.build_variable_output({}, "TOT_PREC")
    assert out["times"] == []
    assert out["ensemble_members"] == []
    assert out["percentiles"]["p50"] == []
