#!/usr/bin/env python3
"""Flask API + static dashboard server."""
from __future__ import annotations

import json
import time
from pathlib import Path

from flask import Flask, abort, jsonify, redirect, send_from_directory
from flask_cors import CORS

from pipeline import config

app = Flask(__name__, static_folder=None)
CORS(app)

_RUN_LIST_CACHE: tuple[float, list[str]] = (0.0, [])
_RUN_LIST_TTL = 60.0

BASE_DIR = Path(__file__).resolve().parent


def _list_runs() -> list[str]:
    global _RUN_LIST_CACHE
    now = time.time()
    if now - _RUN_LIST_CACHE[0] < _RUN_LIST_TTL and _RUN_LIST_CACHE[1]:
        return _RUN_LIST_CACHE[1]
    # Deduplicate: stem may be "{run_id}_{location_id}" or legacy "{run_id}".
    # run_id is always the first 15 chars (YYYY-MM-DDTHHMM).
    ids = sorted(
        {p.stem[:15] for p in config.FORECAST_DIR.glob("*.json")
         if p.stem != "index" and len(p.stem) >= 15},
        reverse=True,
    )
    _RUN_LIST_CACHE = (now, ids)
    return ids


@app.route("/")
def root():
    return send_from_directory(BASE_DIR, "index.html")


@app.route("/data/forecasts/<path:name>")
def forecast_static(name: str):
    """Serve forecast JSONs at the same path the static deploy uses.

    Lets the dashboard use one fetch path (`./data/forecasts/...`) in both
    local dev and GitHub Pages — no fallback needed.
    """
    return send_from_directory(config.FORECAST_DIR, name)


@app.route("/api/runs")
def api_runs():
    return jsonify(_list_runs())


@app.route("/api/runs/latest")
def api_latest():
    runs = _list_runs()
    if not runs:
        abort(404, description="no forecasts available")
    return redirect(f"/api/runs/{runs[0]}", code=302)


@app.route("/api/locations")
def api_locations():
    return jsonify(config.LOCATIONS)


@app.route("/api/runs/<run_id>/<location_id>")
def api_run_location(run_id: str, location_id: str):
    path = config.FORECAST_DIR / f"{run_id}_{location_id}.json"
    if not path.exists():
        abort(404, description=f"run {run_id} location {location_id} not found")
    with open(path) as f:
        return jsonify(json.load(f))


@app.route("/api/runs/<run_id>")
def api_run(run_id: str):
    # Serve the default (first) location; fall back to legacy single-location file.
    default_loc = next(iter(config.LOCATIONS))
    for path in (
        config.FORECAST_DIR / f"{run_id}_{default_loc}.json",
        config.FORECAST_DIR / f"{run_id}.json",
    ):
        if path.exists():
            with open(path) as f:
                return jsonify(json.load(f))
    abort(404, description=f"run {run_id} not found")


def main() -> None:
    import argparse
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=5000)
    p.add_argument("--debug", action="store_true")
    args = p.parse_args()
    app.run(host=args.host, port=args.port, debug=args.debug)


if __name__ == "__main__":
    main()
