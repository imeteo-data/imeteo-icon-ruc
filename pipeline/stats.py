"""Deaccumulation, percentiles, exceedance probabilities — vectorized."""

from __future__ import annotations

import numpy as np

from . import config


def _align_ensembles(
    series: dict[str, list[tuple[np.datetime64, float]]],
) -> tuple[np.ndarray, np.ndarray, list[str]]:
    """Align ensembles on shared timestamps.

    Returns (times [T], matrix [E,T], ensemble_ids [E]).
    Keeps only timestamps present in every ensemble.
    """
    if not series:
        return np.array([], dtype="datetime64[ns]"), np.zeros((0, 0)), []
    ens_ids = sorted(series.keys(), key=int)
    time_sets = [set(t.astype("datetime64[ns]") for t, _ in series[e]) for e in ens_ids]
    shared = sorted(set.intersection(*time_sets)) if time_sets else []
    if not shared:
        return np.array([], dtype="datetime64[ns]"), np.zeros((len(ens_ids), 0)), ens_ids
    shared_arr = np.array(shared, dtype="datetime64[ns]")
    matrix = np.full((len(ens_ids), len(shared_arr)), np.nan, dtype=np.float64)
    for i, ens in enumerate(ens_ids):
        lookup = {t.astype("datetime64[ns]"): v for t, v in series[ens]}
        for j, t in enumerate(shared_arr):
            if t in lookup:
                matrix[i, j] = lookup[t]
    return shared_arr, matrix, ens_ids


def _deaccumulate(matrix: np.ndarray, step_minutes: int) -> np.ndarray:
    """Convert accumulated values to rates (unit per hour), vectorized per ensemble.

    The first timestep has no prior frame to diff against, so its rate is 0.
    """
    diffs = np.diff(matrix, axis=1, prepend=matrix[:, :1])
    diffs = np.clip(diffs, 0.0, None)
    return diffs * (60.0 / step_minutes)


def build_variable_output(
    series: dict[str, list[tuple[np.datetime64, float]]], variable: str
) -> dict:
    """Produce the final per-variable JSON block."""
    var_cfg = config.VARIABLES.get(variable) or config.DERIVED_VARIABLES[variable]
    times, matrix, _ens_ids = _align_ensembles(series)
    if times.size == 0 or matrix.size == 0:
        return {
            "unit": var_cfg["unit"],
            "times": [],
            "ensemble_members": [],
            "percentiles": {f"p{p}": [] for p in config.PERCENTILES},
            "probability_exceeds": {str(t): [] for t in var_cfg["thresholds"]},
        }

    if var_cfg["is_accumulated"]:
        matrix = _deaccumulate(matrix, var_cfg["step_minutes"])

    if var_cfg.get("skip_first_step", False) and times.size > 1:
        times = times[1:]
        matrix = matrix[:, 1:]

    # Optional unit shift (e.g. Kelvin → Celsius for T_2M)
    offset = var_cfg.get("offset")
    if offset is not None:
        matrix = matrix + float(offset)

    percentiles = {
        f"p{p}": np.nanpercentile(matrix, p, axis=0).tolist() for p in config.PERCENTILES
    }
    prob_exceeds = {str(t): ((matrix >= t).mean(axis=0)).tolist() for t in var_cfg["thresholds"]}

    return {
        "unit": var_cfg["unit"],
        "times": [np.datetime_as_string(t, unit="s") + "Z" for t in times],
        "ensemble_members": matrix.round(4).tolist(),
        "percentiles": {k: [round(x, 4) for x in v] for k, v in percentiles.items()},
        "probability_exceeds": {k: [round(x, 4) for x in v] for k, v in prob_exceeds.items()},
    }
