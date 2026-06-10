"""Pipeline orchestrator: discover -> download -> extract -> stats -> write JSON."""
from __future__ import annotations

import asyncio
import json
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import config, discover, download, extract, grid, stats

# Variable used to judge whether a cached run is "fully uploaded". TOT_PREC is
# the densest (5-min steps) and the last to finish publishing on DWD, so it is
# a safe gate even if other variables lag or are absent.
GATE_VARIABLE = "TOT_PREC"


def _stem_to_run_id(stem: str) -> str:
    """Extract run_id from a forecast JSON stem.

    '2026-06-10T1200_bratislava' -> '2026-06-10T1200'
    '2026-06-10T1200'            -> '2026-06-10T1200'  (legacy single-location)
    """
    return stem[:15]


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


async def process_run(run_id: str, offline: bool = False) -> list[Path]:
    """Process one run across all configured locations.

    Downloads each variable's GRIB files once, then extracts the target cell
    for every location from the same files — no extra downloads per location.
    Writes one JSON per location: data/forecasts/{run_id}_{location_id}.json
    """
    print(f"\n── run {run_id} ──")
    tree, lats, _ = grid.load_or_build_index()

    # Download (or load from cache) each variable once — same files for all locations.
    var_paths: dict[str, list[Path]] = {}
    for var_name in config.VARIABLES:
        var_paths[var_name] = await _download_run(var_name, run_id, offline)

    if not any(var_paths.values()):
        print(f"  ✗ no data for {run_id}")
        return []

    generated_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    config.ensure_dirs()
    outputs = []

    for loc_id, loc_cfg in config.LOCATIONS.items():
        cell_index, distance_km = grid.nearest_index(
            tree, loc_cfg["lat"], loc_cfg["lon"]
        )
        print(f"  [{loc_id}] nearest grid cell: idx={cell_index} ({distance_km:.2f} km)")

        loc_output = {
            "run_id": run_id,
            "location_id": loc_id,
            "location": loc_cfg,
            "generated_at": generated_at,
            "grid_distance_km": round(distance_km, 3),
            "variables": {},
        }
        for var_name, paths in var_paths.items():
            if not paths:
                print(f"  [{loc_id}] {var_name}: skipped (no files)")
                continue
            print(f"  [{loc_id}] {var_name}: extracting from {len(paths)} files...")
            series = extract.extract_variable(paths, var_name, cell_index)
            loc_output["variables"][var_name] = stats.build_variable_output(series, var_name)
            print(f"  [{loc_id}] {var_name}: {len(series)} members, "
                  f"{len(loc_output['variables'][var_name]['times'])} timestamps")

        if not loc_output["variables"]:
            print(f"  [{loc_id}] ✗ no data")
            continue

        out_path = config.FORECAST_DIR / f"{run_id}_{loc_id}.json"
        with open(out_path, "w") as f:
            json.dump(loc_output, f, separators=(",", ":"))
        print(f"  [{loc_id}] ✓ wrote {out_path.name}")
        outputs.append(out_path)

    if outputs:
        _prune_old_runs(config.FORECAST_RETAIN)
        _write_index()

    return outputs


def _prune_old_runs(keep: int) -> None:
    """Keep only the newest `keep` run_ids; delete older JSONs + their GRIBs."""
    if keep <= 0:
        return
    by_run: dict[str, list[Path]] = defaultdict(list)
    for p in config.FORECAST_DIR.glob("*.json"):
        if p.stem == "index":
            continue
        by_run[_stem_to_run_id(p.stem)].append(p)

    sorted_runs = sorted(by_run.keys(), reverse=True)
    stale = sorted_runs[keep:]
    if not stale:
        return
    for run_id in stale:
        for grib in config.RAW_DIR.glob(f"icon_d2_ruc_eps_*_{run_id}_*"):
            try:
                grib.unlink()
            except OSError as e:
                print(f"  ⚠ failed to remove {grib.name}: {e}")
        for jp in by_run[run_id]:
            try:
                jp.unlink()
            except OSError as e:
                print(f"  ⚠ failed to remove {jp.name}: {e}")
        print(f"  ✂ pruned old run {run_id}")


def _write_index() -> None:
    """Emit data/forecasts/index.json — the static catalog the dashboard reads."""
    by_run: dict[str, list[str]] = defaultdict(list)
    for p in config.FORECAST_DIR.glob("*.json"):
        if p.stem == "index":
            continue
        by_run[_stem_to_run_id(p.stem)].append(p.stem)
    run_ids = sorted(by_run.keys(), reverse=True)
    idx_path = config.FORECAST_DIR / "index.json"
    with open(idx_path, "w") as f:
        json.dump({
            "locations": config.LOCATIONS,
            "runs": run_ids,
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }, f, separators=(",", ":"))


def _local_run_horizon(run_id: str) -> datetime | None:
    """Last valid-time stored in the cached JSON for the gate variable.

    Tries the new multi-location filename first; falls back to the legacy
    single-location file so the transition period doesn't break backfill.
    """
    gate_loc = next(iter(config.LOCATIONS))
    candidates = [
        config.FORECAST_DIR / f"{run_id}_{gate_loc}.json",
        config.FORECAST_DIR / f"{run_id}.json",   # legacy
    ]
    for path in candidates:
        if not path.exists():
            continue
        try:
            with open(path) as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError):
            continue
        times = data.get("variables", {}).get(GATE_VARIABLE, {}).get("times", [])
        if times:
            return datetime.fromisoformat(times[-1].replace("Z", "+00:00"))
    return None


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


async def _wait_for_run_upload(
    run_id: str,
    poll_interval: int = 60,
    stable_polls: int = 3,
    max_wait: int = 1800,
) -> None:
    """Poll DWD until `run_id`'s available horizon stops growing.

    Exits immediately if the horizon already covers EXPECTED_FORECAST_MINUTES.
    Declares the run complete after `stable_polls` consecutive checks with no
    new files. Gives up after `max_wait` seconds and lets the pipeline run with
    whatever is available, printing a warning.
    """
    base = datetime.strptime(run_id, "%Y-%m-%dT%H%M").replace(tzinfo=timezone.utc)
    full_horizon = base + timedelta(minutes=config.EXPECTED_FORECAST_MINUTES)

    prev: datetime | None = None
    stable = 0
    elapsed = 0

    while elapsed < max_wait:
        horizon = discover.remote_run_horizon(GATE_VARIABLE, run_id)
        if horizon is None:
            print(f"  ⚠ can't read remote horizon for {run_id}; skipping upload wait")
            return

        if horizon >= full_horizon:
            print(f"  ✓ {run_id}: fully uploaded (horizon {horizon.isoformat()})")
            return

        if prev is not None:
            if horizon <= prev:
                stable += 1
                print(f"  ⏳ {run_id}: horizon stable at {horizon.isoformat()} "
                      f"({stable}/{stable_polls})")
                if stable >= stable_polls:
                    print(f"  ✓ {run_id}: upload stable — proceeding")
                    return
            else:
                stable = 0
                print(f"  ⏳ {run_id}: horizon grew → {horizon.isoformat()}, "
                      f"full expected {full_horizon.isoformat()}")
        else:
            print(f"  ⏳ {run_id}: upload in progress "
                  f"(horizon {horizon.isoformat()}, "
                  f"expecting {full_horizon.isoformat()})")

        prev = horizon
        await asyncio.sleep(poll_interval)
        elapsed += poll_interval

    print(f"  ⚠ {run_id}: gave up waiting after {max_wait}s, processing what's available")


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
                       skip_complete: bool = False,
                       wait_for_upload: bool = True) -> list[Path]:
    """Process each run; with skip_complete, skip runs already fully cached.

    skip_complete makes backfill cheap and self-healing: missing hours (dropped
    by the scheduler) and runs captured mid-upload get (re)fetched, while runs
    already covering DWD's full horizon are left untouched.

    wait_for_upload (default True): before processing the most-recent run in
    online mode, poll DWD until its upload is complete so we never write a
    forecast truncated to the first few minutes of the model run.
    """
    outputs: list[Path] = []
    for i, run_id in enumerate(run_ids):
        if skip_complete and not offline and _is_run_complete(run_id):
            print(f"\n── run {run_id} ── already complete, skipping")
            continue
        if i == 0 and not offline and wait_for_upload:
            await _wait_for_run_upload(run_id)
        outs = await process_run(run_id, offline=offline)
        # outs is list[Path]; guard against legacy mocks that return a single Path
        if isinstance(outs, list):
            outputs.extend(outs)
        elif outs is not None:
            outputs.append(outs)
    return outputs
