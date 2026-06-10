#!/usr/bin/env python3
"""Trim old GRIB files from data/raw/. Either by age or by keeping last N runs."""
from __future__ import annotations

import argparse
import re
import time
from pathlib import Path

from pipeline import config, discover


def _targets_by_age(hours: float) -> list[Path]:
    cutoff = time.time() - hours * 3600
    return sorted(
        f for f in config.RAW_DIR.glob("icon_d2_ruc_eps_*")
        if f.stat().st_mtime < cutoff
    )


def _targets_by_keep_last(keep: int, keep_forecasts: bool
                          ) -> tuple[list[Path], list[str]]:
    """Return (files_to_delete, run_ids_to_delete)."""
    local = discover.scan_local_runs()   # already sorted newest-first
    all_ids = list(local.keys())
    to_keep = set(all_ids[:keep])
    to_delete_ids = [rid for rid in all_ids if rid not in to_keep]

    files: list[Path] = []
    for rid in to_delete_ids:
        # All GRIBs for this run + their .idx sidecars
        files.extend(config.RAW_DIR.glob(f"icon_d2_ruc_eps_*_{rid}_*"))
        # Forecast JSON (optional)
        if not keep_forecasts:
            # New format: {rid}_{location_id}.json per location.
            files.extend(config.FORECAST_DIR.glob(f"{rid}_*.json"))
            # Legacy single-location file (pre-multi-location deploys).
            jp = config.FORECAST_DIR / f"{rid}.json"
            if jp.exists():
                files.append(jp)
    # Dedup + sort for stable output
    return sorted(set(files)), to_delete_ids


def _delete(files: list[Path]) -> tuple[int, int]:
    ok = fail = 0
    for f in files:
        try:
            f.unlink()
            ok += 1
        except OSError as e:
            fail += 1
            print(f"  failed to delete {f.name}: {e}")
    return ok, fail


def main() -> None:
    p = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "examples:\n"
            "  cleanup.py --keep-last 5                  keep newest 5 runs, delete rest\n"
            "  cleanup.py --keep-last 3 --dry-run        preview only\n"
            "  cleanup.py --keep-last 3 --keep-forecasts delete GRIBs, keep JSON outputs\n"
            "  cleanup.py --hours 12                     delete files older than 12h\n"
            "  cleanup.py --list                         list local runs and sizes\n"
        ),
    )
    g = p.add_mutually_exclusive_group()
    g.add_argument("--keep-last", type=int, metavar="N",
                   help="Keep the newest N run_ids, delete everything older")
    g.add_argument("--hours", type=float, metavar="H",
                   help="Delete files older than H hours")
    g.add_argument("--list", action="store_true",
                   help="List local runs with file counts and sizes")
    p.add_argument("--keep-forecasts", action="store_true",
                   help="When using --keep-last, preserve forecast JSONs even for deleted runs")
    p.add_argument("--dry-run", action="store_true",
                   help="List files that would be deleted without removing them")
    args = p.parse_args()

    if args.list:
        local = discover.scan_local_runs()
        if not local:
            print("no local runs found in data/raw/")
            return
        for rid, by_var in local.items():
            total_bytes = 0
            for paths in by_var.values():
                total_bytes += sum(p.stat().st_size for p in paths)
            summary = ", ".join(f"{v}:{len(paths)}" for v, paths in by_var.items())
            print(f"  {rid}  ({summary})  {total_bytes / 1e9:.2f} GB")
        return

    if args.keep_last is not None:
        if args.keep_last < 0:
            p.error("--keep-last must be >= 0")
        targets, deleted_ids = _targets_by_keep_last(args.keep_last, args.keep_forecasts)
        total_bytes = sum(f.stat().st_size for f in targets)
        label = "would delete" if args.dry_run else "deleting"
        print(
            f"{label} {len(targets)} files "
            f"across {len(deleted_ids)} run(s) ({total_bytes / 1e9:.2f} GB)"
        )
        for rid in deleted_ids:
            print(f"  run {rid}")
        if args.dry_run:
            return
        ok, fail = _delete(targets)
        print(f"deleted {ok} files" + (f", {fail} failed" if fail else ""))
        return

    if args.hours is not None:
        targets = _targets_by_age(args.hours)
        total_bytes = sum(f.stat().st_size for f in targets)
        label = "would delete" if args.dry_run else "deleting"
        print(f"{label} {len(targets)} files ({total_bytes / 1e9:.2f} GB)")
        if args.dry_run:
            for f in targets[:10]:
                print(f"  {f.name}")
            if len(targets) > 10:
                print(f"  ... and {len(targets) - 10} more")
            return
        ok, fail = _delete(targets)
        print(f"deleted {ok} files" + (f", {fail} failed" if fail else ""))
        return

    p.print_help()


if __name__ == "__main__":
    main()
