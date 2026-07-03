# ICON-D2-RUC · Bratislava

Ensemble forecast dashboard for Bratislava (and Pohoda / Letisko Trenčín) built on DWD's
ICON-D2-RUC rapid-update-cycle model. The pipeline downloads GRIB2
files, extracts the single grid cell nearest each location, computes ensemble
percentiles and exceedance probabilities across the members, and writes one
JSON per run and location. A static HTML/uPlot dashboard renders them.

> **Stopgap notice:** DWD discontinued the ensemble source (ICON-D2-RUC-EPS,
> 20 members) in mid-2026; the pipeline currently runs on its deterministic
> sibling ICON-D2-RUC (1 member) so the dashboard keeps publishing.
> Percentiles/exceedance probabilities collapse to that single member's value
> until a real ensemble source is wired in. See CLAUDE.md's "Data source"
> section for the technical detail and migration path.

**Live dashboard:** https://imeteo-data.github.io/imeteo-icon-ruc/

**Where this fits:** Standalone satellite of the imeteo-data org — no shared
data flows; org registry:
https://github.com/imeteo-data/meta/blob/main/docs/system-architecture.md

## How it works

1. **Discover** — list completed runs on DWD open data (or in the local cache).
2. **Download** — async fetch of every ensemble × step GRIB, cache-aware
   (files already in `data/raw/` are never re-fetched).
3. **Extract** — read only the target grid cell from each GRIB (Rust/pyo3
   extension if built, xarray/cfgrib fallback otherwise).
4. **Stats** — align ensembles, deaccumulate precipitation, compute
   p10/p25/p50/p75/p90 and per-threshold exceedance probabilities.
5. **Write** — `data/forecasts/{run_id}_{location}.json` plus an `index.json`
   catalog the dashboard reads.

Variables processed: `TOT_PREC` (5-min precipitation rate, mm/h),
`VMAX_10M` (hourly max 10 m gust, m/s), `T_2M` (hourly 2 m temperature, °C).

## Automation

`.github/workflows/forecast.yml` fires **every 15 minutes** (plus manual
`workflow_dispatch`). Each fire backfills the 12 most recent runs
(`main.py --runs 12 --backfill` — already-complete runs are skipped, so a
no-op fire is cheap), trims to the newest 12 runs, and commits changed JSONs
back to `main`. When forecasts changed, a second job deploys the repo root to
GitHub Pages via `actions/deploy-pages`. `choose-runner.yml` runs the job on
the self-hosted `mac-mini-m2` runner when it is online, `ubuntu-latest`
otherwise.

## Quickstart

Needs Python ≥3.12, [uv](https://docs.astral.sh/uv/), and the eccodes C
library (macOS: `brew install eccodes`; Debian/Ubuntu: `apt install
libeccodes-dev`).

```bash
uv sync --group dev            # install dependencies
uv run python main.py          # process the most recent completed DWD run
uv run python api.py           # dashboard at http://127.0.0.1:5000/
uv run pytest tests/           # test suite
```

An optional Rust extension speeds up GRIB extraction ~5–10×; see
[CLAUDE.md](CLAUDE.md) for the build command, the full CLI reference, the
output JSON shape, and operational gotchas.
