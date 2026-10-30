"""Tests for pipeline/grid.py — nearest-index behaviour on a synthetic tree."""

from __future__ import annotations

import numpy as np
import pytest
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


class _Resp:
    def __init__(self, status: int, content: bytes = b""):
        self.ok = status == 200
        self.content = content


def _stub_feed(monkeypatch, tmp_path, responses):
    monkeypatch.setattr(grid.config, "GRID_DIR", tmp_path)
    monkeypatch.setattr(grid.config, "ensure_dirs", lambda: None)
    monkeypatch.setattr(
        grid.discover, "list_remote_runs", lambda var, limit: ["2026-10-30T1800", "2026-10-30T1500"]
    )
    monkeypatch.setattr(grid.discover, "list_remote_ensembles", lambda var, run: ["01"])
    monkeypatch.setattr(
        grid.discover, "build_url", lambda var, run, ens, step: f"{var}/{run}/{ens}/{step}"
    )
    urls = []

    def fake_get(url, **_):
        urls.append(url)
        return responses.pop(0)

    monkeypatch.setattr(grid.requests, "get", fake_get)
    return urls


def test_fetch_mesh_downloads_analysis_step_once(monkeypatch, tmp_path):
    urls = _stub_feed(monkeypatch, tmp_path, [_Resp(200, b"GRIB")])

    path = grid._fetch_mesh("CLAT")
    assert path == tmp_path / "CLAT.grib2"
    assert path.read_bytes() == b"GRIB"
    assert urls == ["CLAT/2026-10-30T1800/01/PT000H00M"]

    grid._fetch_mesh("CLAT")
    assert len(urls) == 1  # cached, no second request


def test_fetch_mesh_falls_back_to_previous_run(monkeypatch, tmp_path):
    urls = _stub_feed(monkeypatch, tmp_path, [_Resp(404), _Resp(200, b"GRIB")])

    grid._fetch_mesh("CLON")
    assert urls == ["CLON/2026-10-30T1800/01/PT000H00M", "CLON/2026-10-30T1500/01/PT000H00M"]


def test_fetch_mesh_raises_when_no_run_has_the_file(monkeypatch, tmp_path):
    _stub_feed(monkeypatch, tmp_path, [_Resp(404), _Resp(404)])

    with pytest.raises(RuntimeError, match="CLAT"):
        grid._fetch_mesh("CLAT")
    assert not (tmp_path / "CLAT.grib2").exists()
