# ICON-D2-RUC-EPS · Bratislava

## Purpose

Ensemble precipitation and wind-gust forecasts for Bratislava, Slovakia (48.1629°N, 17.1369°E), from DWD's ICON-D2-RUC-EPS model. The pipeline downloads GRIB2 ensemble files, extracts the single grid cell nearest to Bratislava, computes percentiles and exceedance probabilities across ensemble members, and writes one JSON file per forecast run. A Flask API serves the JSON to a static HTML/uPlot dashboard.

## Data source

- **Server:** `https://opendata.dwd.de/weather/nwp/v1/m/icon-d2-ruc-eps/`
- **Model:** ICON-D2-RUC-EPS (rapid-update-cycle ensemble, Germany + surrounding)
- **Grid:** unstructured triangular, 542,040 cells, ~2.5 km resolution
- **Variables currently processed:**
  - `TOT_PREC` (accumulated precipitation → deaccumulated to mm/h rate)
  - `VMAX_10M` (instantaneous 10 m max wind gust in m/s)
- **Ensembles:** 20 members per run
- **Forecast range:** ~14 h at 5 min steps for TOT_PREC, ~14 h at 1 h steps for VMAX_10M

## Layout

```
pipeline/
  config.py     variable specs, location, DWD URLs, percentiles, thresholds
  discover.py   DWD + local discovery, URL/filename helpers
  download.py   async aiohttp downloader, skips files already cached
  grid.py       ICON grid loader + KDTree index (pickled cache)
  extract.py    per-file point extraction — calls Rust ext if available, xarray fallback
  stats.py      deaccumulation, percentiles, exceedance probability
  run.py        orchestrator
extract_rs/     Rust extension (pyo3 + eccodes + rayon) — parallel GRIB decode
main.py         CLI entry point
api.py          Flask API + static dashboard server
cleanup.py      standalone GRIB cleanup by age
index.html  vanilla HTML + uPlot dashboard
tests/          pytest suite
data/
  raw/          GRIB downloads (preserved across runs)
  grid/         ICON grid NetCDF + pickled KDTree
  forecasts/    output JSON, one file per run_id
```

## Rust extraction extension (optional but strongly recommended)

`extract_rs/` is a small pyo3 crate that decodes GRIB messages in parallel via rayon. On a typical run it is **~11× faster** than the pure-Python path (full 20-ensemble × 169-step run: ~13 s vs ~2:30). The Python path still exists as a fallback if the extension isn't built.

Build and install:

```bash
uv run maturin develop --release --manifest-path extract_rs/Cargo.toml
```

Requires a Rust toolchain (`rustup` + `cargo ≥1.70`) and the eccodes C library (same lib cfgrib uses; Homebrew: `brew install eccodes`). The extension reads eccodes' `shortName` key directly — so `config.VARIABLES[...]["grib_var"]` must match the GRIB shortName (e.g. `max_i10fg`, not the xarray cfVarName `fg10`).

## Key commands

```bash
uv run python main.py                              # latest run
uv run python main.py --runs 3                     # 3 most recent runs
uv run python main.py --run-id 2025-10-28T0700     # specific run
uv run python main.py --run-id X --offline         # no network, use data/raw/ only
uv run python main.py --list-local                 # list cached runs

uv run python api.py                               # start dashboard server

uv run python cleanup.py --hours 12                # trim old GRIBs
uv run python cleanup.py --hours 24 --dry-run

uv run pytest tests/
```

## How the pipeline works

1. **discover** lists completed runs (remote DWD or local `data/raw/`).
2. **grid** loads the ICON grid once (cached as pickled KDTree on disk), finds the nearest cell to Bratislava.
3. **download** fetches (or reuses cached) GRIB files for every ensemble × step. Async, `Semaphore(20)`.
4. **extract** opens each GRIB lazily, reads only the single target cell, closes.
5. **stats** aligns ensembles on shared timestamps, deaccumulates accumulated variables, computes p10/p25/p50/p75/p90 and probability of exceeding per-variable thresholds.
6. Orchestrator writes `data/forecasts/<run_id>.json`.

## Adding a variable

One dict entry in `pipeline/config.py`:

```python
VARIABLES = {
    ...,
    "T_2M": {"grib_var": "t2m", "is_accumulated": False,
             "step_minutes": 60, "unit": "K",
             "thresholds": [273.15, 283.15, 293.15]},
}
```

No new class, no adapter. The rest of the pipeline handles it.

## Forecast JSON shape

```json
{
  "run_id": "2025-10-28T0700",
  "location": {"name": "Bratislava", "lat": 48.1486, "lon": 17.1077},
  "generated_at": "2025-10-28T10:00:00+00:00",
  "grid_distance_km": 1.071,
  "variables": {
    "TOT_PREC": {
      "unit": "mm/h",
      "times": ["..."],
      "ensemble_members": [[...], ...],
      "percentiles": {"p10": [...], "p25": [...], "p50": [...], "p75": [...], "p90": [...]},
      "probability_exceeds": {"0.1": [...], "1.0": [...], "5.0": [...], "10.0": [...]}
    },
    "VMAX_10M": { ... }
  }
}
```

## Dependencies

Managed by uv via `pyproject.toml` and `uv.lock`. Install with `uv sync --group dev`.

## Notes

- Files in `data/raw/` are never auto-deleted. Use `cleanup.py` explicitly.
- DWD URL encodes the run time as `YYYY-MM-DDTHH%3A00`; local filenames use the compact `YYYY-MM-DDTHHMM` form. `pipeline/discover.py` handles the conversion.
- The pipeline runs fully offline from `data/raw/` with `--offline` — no DWD discovery, no downloads. Useful on slow connections.
