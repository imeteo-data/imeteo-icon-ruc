# CLAUDE.md

Agent-operational reference. Purpose, pipeline overview, and quickstart live
in [README.md](README.md).

## Layout

```
pipeline/
  config.py     LOCATIONS, VARIABLES, PERCENTILES, DWD URLs, retention
  discover.py   DWD + local run discovery, URL/filename helpers
  download.py   async aiohttp downloader, skips files already cached
  grid.py       ICON grid loader + KDTree index (pickled to data/grid/)
  extract.py    per-file point extraction — Rust ext if built, xarray fallback
  stats.py      deaccumulation, percentiles, exceedance probability
  run.py        orchestrator, backfill/completeness logic, index.json writer
extract_rs/     Rust extension (pyo3 + eccodes + rayon) — parallel GRIB decode
main.py         CLI entry point
api.py          Flask API + local dashboard server
cleanup.py      standalone GRIB/JSON cleanup (by age or keep-last-N)
index.html      static uPlot dashboard (served as-is by GitHub Pages)
tests/          pytest suite
data/
  raw/          GRIB downloads (pruned only by cleanup.py / run pruning)
  grid/         ICON grid NetCDF + pickled KDTree
  forecasts/    {run_id}_{location_id}.json per run+location, plus index.json
```

## Commands

```bash
uv sync --group dev                                # install deps (Python >=3.12)

uv run python main.py                              # latest completed run
uv run python main.py --runs 12 --backfill         # what CI does: skip complete runs
uv run python main.py --run-id 2025-10-28T0700     # one specific run
uv run python main.py --run-id X --offline         # no network, data/raw/ only
uv run python main.py --no-wait                    # don't poll DWD for upload completion
uv run python main.py --list-local                 # list cached runs

uv run python api.py                               # dashboard at http://127.0.0.1:5000/

uv run python cleanup.py --keep-last 12            # keep newest 12 runs (CI uses this)
uv run python cleanup.py --hours 12 --dry-run      # age-based, preview only
uv run python cleanup.py --list                    # local runs with sizes

uv run pytest tests/                               # test suite
```

### Rust extraction extension (optional, ~5–10× faster)

```bash
uv run maturin develop --release --manifest-path extract_rs/Cargo.toml
```

Requires a Rust toolchain (`rustup`) and the eccodes C library (macOS:
`brew install eccodes`; Debian/Ubuntu: `apt install libeccodes-dev`). If the
extension isn't importable, `pipeline/extract.py` falls back to xarray/cfgrib
automatically (it prints which backend it picked at import time).

## Data source

- Base URL: `https://opendata.dwd.de/weather/nwp/v1/m/icon-d2-ruc-eps/p`
  (`config.DWD_BASE`), file URLs `{base}/{VAR}/r/{run}/e/{ens}/s/{step}.grib2`.
- 20 ensemble members per run; hourly model runs. A run is treated as fully
  uploaded once its horizon reaches `EXPECTED_FORECAST_MINUTES` (800).
- DWD URLs encode the run time as `YYYY-MM-DDTHH%3A00`; local filenames use
  the compact `YYYY-MM-DDTHHMM` run_id. `pipeline/discover.py` converts.
- Grid: `icon_grid_0047_R19B07_L.nc`, downloaded and KDTree-indexed once,
  cached in `data/grid/`.

## Output JSON

One file per run and location: `data/forecasts/{run_id}_{location_id}.json`
(legacy pre-multi-location deploys used `{run_id}.json`; readers still fall
back to it). `data/forecasts/index.json` is the static catalog
(`{locations, runs, generated_at}`) the dashboard loads first.

```json
{
  "run_id": "2026-07-01T0000",
  "location_id": "bratislava",
  "location": {"name": "Bratislava", "lat": 48.1629, "lon": 17.1369},
  "generated_at": "2026-07-01T01:04:00+00:00",
  "grid_distance_km": 1.362,
  "variables": {
    "TOT_PREC": {
      "unit": "mm/h",
      "times": ["2026-07-01T00:05:00Z", "..."],
      "ensemble_members": [[...], ...],
      "percentiles": {"p10": [...], "p25": [...], "p50": [...], "p75": [...], "p90": [...]},
      "probability_exceeds": {"0.1": [...], "1.0": [...], "5.0": [...], "10.0": [...]}
    },
    "VMAX_10M": { "...": "same shape, m/s" },
    "T_2M": { "...": "same shape, °C" }
  }
}
```

## Adding a variable / location

Both are single dict entries in `pipeline/config.py` (`VARIABLES` /
`LOCATIONS`); the rest of the pipeline handles them. Variable options:
`grib_var`, `is_accumulated`, `step_minutes`, `unit`, `thresholds`, plus
optional `skip_first_step` (drop bogus t=0, see VMAX_10M) and `offset`
(unit shift, see T_2M's Kelvin→Celsius).

## Gotchas

- **The scheduled workflow commits to `main` every 15 minutes**
  (`.github/workflows/forecast.yml`, cron `*/15 * * * *`, auto-commits
  `data/forecasts/`). Always `git pull` before working, and expect
  `git push` races on `main`.
- `choose-runner.yml` selects the Actions runner: self-hosted `mac-mini-m2`
  when online, `ubuntu-latest` otherwise. CI installs `libeccodes-dev` only
  on Linux — the mac runner must have eccodes installed already.
- `grib_var` must be the **eccodes shortName** (e.g. `max_i10fg`, `2t`), not
  the xarray cfVarName (`fg10`, `t2m`) — the Rust extension reads the
  shortName key directly.
- eccodes/cfgrib are native deps: without the eccodes C library neither the
  Python fallback nor the Rust extension can decode GRIBs.
- `config.FORECAST_RETAIN` (12) must stay ≥ the workflow's `--runs` backfill
  window and `cleanup.py --keep-last` value, or backfilled runs get pruned
  and re-downloaded every cycle.
- Files in `data/raw/` are only deleted by `cleanup.py` or the automatic
  pruning of runs older than the newest `FORECAST_RETAIN`.
- Fully offline operation: `--offline` uses `data/raw/` only — no DWD
  discovery, no downloads.
