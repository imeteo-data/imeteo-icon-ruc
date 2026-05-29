#!/usr/bin/env python3
"""CLI entry for the ICON-D2-RUC-EPS Bratislava pipeline."""
from __future__ import annotations

import argparse
import asyncio

from pipeline import discover, run


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--runs", type=int, default=1,
                   help="Number of most-recent completed runs to process (default: 1)")
    p.add_argument("--run-id", type=str, default=None,
                   help="Specific run to process, e.g. 2025-10-28T0700")
    p.add_argument("--list-local", action="store_true",
                   help="List run_ids currently cached in data/raw/ and exit")
    p.add_argument("--offline", action="store_true",
                   help="Skip DWD discovery/downloads; use local files only")
    p.add_argument("--backfill", action="store_true",
                   help="Skip runs already complete locally; only (re)fetch missing "
                        "or partially-uploaded runs. Use with --runs N to backfill a "
                        "window of recent runs and recover hours the scheduler dropped")
    args = p.parse_args()

    if args.list_local:
        local = discover.scan_local_runs()
        if not local:
            print("no local runs found in data/raw/")
            return
        for rid, vars_ in local.items():
            summary = ", ".join(f"{v}:{len(paths)}" for v, paths in vars_.items())
            print(f"  {rid}  ({summary})")
        return

    run_ids = run.resolve_runs(run_id=args.run_id, runs=args.runs, offline=args.offline)
    if not run_ids:
        print("no runs to process")
        return
    print(f"processing runs: {run_ids}")
    asyncio.run(run.process_runs(run_ids, offline=args.offline,
                                 skip_complete=args.backfill))


if __name__ == "__main__":
    main()
