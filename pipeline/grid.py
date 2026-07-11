"""ICON grid loader + KDTree index, cached on disk."""

from __future__ import annotations

import bz2
import pickle
import shutil
import tempfile
from pathlib import Path

import numpy as np
import requests
import xarray as xr
from scipy.spatial import cKDTree

from . import config


def _download_grid() -> Path:
    config.ensure_dirs()
    if config.GRID_FILE.exists():
        return config.GRID_FILE
    print(f"Downloading ICON grid from {config.GRID_URL}...")
    resp = requests.get(
        config.GRID_URL, stream=True, timeout=300, headers={"User-Agent": config.HTTP_USER_AGENT}
    )
    resp.raise_for_status()
    with tempfile.NamedTemporaryFile(delete=False, suffix=".nc.bz2") as tmp:
        shutil.copyfileobj(resp.raw, tmp)
        tmp_path = Path(tmp.name)
    with bz2.open(tmp_path, "rb") as src, open(config.GRID_FILE, "wb") as dst:
        shutil.copyfileobj(src, dst)
    tmp_path.unlink()
    return config.GRID_FILE


def load_grid() -> tuple[np.ndarray, np.ndarray]:
    """Return (lats_deg, lons_deg) as 1D arrays."""
    path = _download_grid()
    ds = xr.open_dataset(path)
    lats = np.asarray(ds.clat.values) * (180.0 / np.pi)
    lons = np.asarray(ds.clon.values) * (180.0 / np.pi)
    ds.close()
    return lats, lons


def build_index() -> tuple[cKDTree, np.ndarray, np.ndarray]:
    lats, lons = load_grid()
    tree = cKDTree(np.column_stack([lats, lons]))
    return tree, lats, lons


def load_or_build_index() -> tuple[cKDTree, np.ndarray, np.ndarray]:
    """Cached version: pickle the tree + arrays to disk and reuse on next run."""
    if config.KDTREE_CACHE.exists():
        try:
            with open(config.KDTREE_CACHE, "rb") as f:
                tree, lats, lons = pickle.load(f)
            if isinstance(tree, cKDTree) and lats.size == lons.size:
                return tree, lats, lons
        except Exception:
            pass
    tree, lats, lons = build_index()
    config.ensure_dirs()
    with open(config.KDTREE_CACHE, "wb") as f:
        pickle.dump((tree, lats, lons), f)
    return tree, lats, lons


def nearest_index(tree: cKDTree, lat: float, lon: float) -> tuple[int, float]:
    """Return (cell_index, distance_km)."""
    dist_deg, idx = tree.query([lat, lon])
    return int(idx), float(dist_deg * 111.0)
