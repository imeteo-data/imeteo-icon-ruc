"""Pipeline orchestrator: discover -> download -> extract -> stats -> write JSON."""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path

from . import config, discover, download, extract, grid, stats

# Variable used to judge whether a cached run is "fully uploaded". TOT_PREC is
# the densest (15-min steps) and the last to finish publishing on DWD, so it is
# a safe gate even if other variables lag or are absent.
GATE_VARIABLE = "TOT_PREC"


async def _download_run(variable: str, run_id: str, offline: bool) -> list[Path]:
    """Return the GRIB file paths for a variable+run, fetching missing ones if online."""
    if offline:
        paths = discover.files_for_run(run_id, variable)
        if not paths:
            print(f"  ⚠ {variable} {run_id}: no local files found (offline mode)")
        return paths
    try:
        ensembles = discover.list_remote_ensembles(variable, run_id)
        steps = discover.list_remote_steps(variable, run_id, ensembles[0]) if ensembles else []
    except Exception as e:
        print(f"  ⚠ remote discovery failed for {variable} {run_id}: {e}")
        return discover.files_for_run(run_id, variable)
    if not ensembles or not steps:
        return discover.files_for_run(run_id, variable)
    return await download.fetch_variable(variable, run_id, ensembles, steps)


async def process_run(run_id: str, offline: bool = False) -> Path | None:
    """Process one run: download/load all variables, extract, compute stats, write JSON."""
    print(f"\n── run {run_id} ──")
    tree, lats, _ = grid.load_or_build_index()
    cell_index, distance_km = grid.nearest_index(
        tree, config.LOCATION["lat"], config.LOCATION["lon"]
    )
    print(f"  nearest grid cell: idx={cell_index} ({distance_km:.2f} km from target)")

    output = {
        "run_id": run_id,
        "location": config.LOCATION,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "grid_distance_km": round(distance_km, 3),
        "variables": {},
    }
    for var_name in config.VARIABLES:
        paths = await _download_run(var_name, run_id, offline)
        if not paths:
            print(f"  {var_name}: skipped (no files)")
            continue
        print(f"  {var_name}: extracting from {len(paths)} files...")
        series = extract.extract_variable(paths, var_name, cell_index)
        output["variables"][var_name] = stats.build_variable_output(series, var_name)
        print(f"  {var_name}: {len(series)} ensemble members, "
              f"{len(output['variables'][var_name]['times'])} timestamps")

    if not output["variables"]:
        print(f"  ✗ no data for {run_id}")
        return None

    config.ensure_dirs()
    out_path = config.FORECAST_DIR / f"{run_id}.json"
    with open(out_path, "w") as f:
        json.dump(output, f, separators=(",", ":"))
    print(f"  ✓ wrote {out_path}")
    _prune_old_runs(config.FORECAST_RETAIN)
    _write_index()
    return out_path


def _prune_old_runs(keep: int) -> None:
    """Keep only the newest `keep` forecast JSONs; delete older JSONs + their GRIBs."""
    if keep <= 0:
        return
    all_jsons = sorted(
        (p for p in config.FORECAST_DIR.glob("*.json") if p.stem != "index"),
        key=lambda p: p.stem,
        reverse=True,
    )
    stale = all_jsons[keep:]
    if not stale:
        return
    for jp in stale:
        run_id = jp.stem
        for grib in config.RAW_DIR.glob(f"icon_d2_ruc_eps_*_{run_id}_*"):
            try:
                grib.unlink()
            except OSError as e:
                print(f"  ⚠ failed to remove {grib.name}: {e}")
        try:
            jp.unlink()
            print(f"  ✂ pruned old run {run_id}")
        except OSError as e:
            print(f"  ⚠ failed to remove {jp.name}: {e}")


def _write_index() -> None:
    """Emit data/forecasts/index.json — the static catalog the dashboard reads."""
    run_ids = sorted(
        (p.stem for p in config.FORECAST_DIR.glob("*.json") if p.stem != "index"),
        reverse=True,
    )
    idx_path = config.FORECAST_DIR / "index.json"
    with open(idx_path, "w") as f:
        json.dump({"runs": run_ids, "generated_at":
                   datetime.now(timezone.utc).isoformat(timespec="seconds")},
                  f, separators=(",", ":"))


def _local_run_horizon(run_id: str, variable: str = GATE_VARIABLE) -> datetime | None:
    """Last valid-time stored in the cached JSON for `variable`, or None."""
    path = config.FORECAST_DIR / f"{run_id}.json"
    if not path.exists():
        return None
    try:
        with open(path) as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return None
    times = data.get("variables", {}).get(variable, {}).get("times", [])
    if not times:
        return None
    return datetime.fromisoformat(times[-1].replace("Z", "+00:00"))


def _is_run_complete(run_id: str) -> bool:
    """True when the cached JSON already covers DWD's full horizon for this run.

    A missing JSON, a missing gate variable, or a cached horizon shorter than
    DWD currently offers (the run was captured mid-upload) all count as
    incomplete and should be re-fetched. If DWD can't be listed we keep what we
    have rather than re-fetching forever.
    """
    local = _local_run_horizon(run_id)
    if local is None:
        return False
    remote = discover.remote_run_horizon(GATE_VARIABLE, run_id)
    if remote is None:
        return True
    return local >= remote


def resolve_runs(run_id: str | None = None, runs: int = 1,
                 offline: bool = False) -> list[str]:
    """Pick the runs to process based on CLI args."""
    if run_id:
        return [run_id]
    if offline:
        return discover.local_run_ids()[:runs]
    try:
        return discover.list_remote_runs(limit=runs)
    except Exception as e:
        print(f"remote discovery failed ({e}); falling back to local runs")
        return discover.local_run_ids()[:runs]


async def process_runs(run_ids: list[str], offline: bool = False,
                       skip_complete: bool = False) -> list[Path]:
    """Process each run; with skip_complete, skip runs already fully cached.

    skip_complete makes backfill cheap and self-healing: missing hours (dropped
    by the scheduler) and runs captured mid-upload get (re)fetched, while runs
    already covering DWD's full horizon are left untouched.
    """
    outputs = []
    for run_id in run_ids:
        if skip_complete and not offline and _is_run_complete(run_id):
            print(f"\n── run {run_id} ── already complete, skipping")
            continue
        out = await process_run(run_id, offline=offline)
        if out:
            outputs.append(out)
    return outputs
