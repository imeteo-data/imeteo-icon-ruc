"""ICON grid loader + KDTree index, cached on disk.

Cell centres come from the CLAT/CLON fields of the v1 feed the pipeline already
polls (DWD deleted the lib/cdo grid files after 2026-11-30). Same 542 040 cells
in the same order as icon_grid_0047_R19B07_L.nc, at GRIB packing precision
(<= 2.5e-4 deg).
"""

from __future__ import annotations

import pickle
from pathlib import Path

import numpy as np
import requests
import xarray as xr
from scipy.spatial import cKDTree

from . import config, discover


def _fetch_mesh(variable: str) -> Path:
    """Download the analysis-step GRIB of CLAT or CLON into GRID_DIR, once."""
    config.ensure_dirs()
    dest = config.GRID_DIR / f"{variable}.grib2"
    if dest.exists():
        return dest
    # The newest run directory can be listed before its files land; fall back
    # to the one before it.
    runs = discover.list_remote_runs(variable, limit=2)
    for run_id in runs:
        ensemble = discover.list_remote_ensembles(variable, run_id)[0]
        url = discover.build_url(variable, run_id, ensemble, "PT000H00M")
        print(f"Downloading ICON grid {variable} from {url}...")
        resp = requests.get(url, timeout=120, headers={"User-Agent": config.HTTP_USER_AGENT})
        if resp.ok:
            dest.write_bytes(resp.content)
            return dest
    raise RuntimeError(f"[grid] no {variable} analysis file in runs {runs}")


def _read_mesh(path: Path) -> np.ndarray:
    ds = xr.open_dataset(path, engine="cfgrib", backend_kwargs={"indexpath": ""})
    values = np.asarray(ds[next(iter(ds.data_vars))].values, dtype=np.float64).ravel()
    ds.close()
    return values


def load_grid() -> tuple[np.ndarray, np.ndarray]:
    """Return (lats_deg, lons_deg) as 1D arrays."""
    return _read_mesh(_fetch_mesh("CLAT")), _read_mesh(_fetch_mesh("CLON"))


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
