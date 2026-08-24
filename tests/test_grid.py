"""Tests for pipeline/grid.py — nearest-index behaviour on a synthetic tree."""

from __future__ import annotations

import numpy as np
from scipy.spatial import cKDTree

from pipeline import grid


def test_nearest_index_returns_closest_cell():
    # 4-cell grid around a rough Slovakia/Austria region
    coords = np.array(
        [
            [48.0, 17.0],
            [48.1486, 17.1077],  # Bratislava
            [49.0, 17.0],
            [47.0, 16.0],
        ]
    )
    tree = cKDTree(coords)

    idx, distance_km = grid.nearest_index(tree, 48.1486, 17.1077)
    assert idx == 1
    assert distance_km < 0.01  # essentially zero


def test_nearest_index_picks_closest_when_target_off_grid():
    coords = np.array([[50.0, 10.0], [40.0, 10.0]])
    tree = cKDTree(coords)
    idx, _ = grid.nearest_index(tree, 48.0, 10.0)
    assert idx == 0
