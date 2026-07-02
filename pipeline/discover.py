"""Run and file discovery — remote (DWD) and local (data/raw/)."""
from __future__ import annotations

import re
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable

import requests
from bs4 import BeautifulSoup

from . import config

_FILENAME_RE = re.compile(
    r"icon_d2_ruc_eps_(?P<var>[A-Z0-9_]+)_"
    r"(?P<date>\d{4}-\d{2}-\d{2})T(?P<hm>\d{4})_"
    r"e(?P<ens>\d{2})_"
    r"(?P<step>PT\d{3}H\d{2}M)\.grib2$"
)


def run_id_to_url(run_id: str) -> str:
    """'2025-10-28T0600' -> '2025-10-28T06%3A00' (DWD URL encoding)."""
    date, hm = run_id.split("T")
    return f"{date}T{hm[:2]}%3A{hm[2:]}"


def url_to_run_id(run_url: str) -> str:
    """'2025-10-28T06%3A00' -> '2025-10-28T0600'."""
    return run_url.replace("%3A", "")[:15]


def local_filename(variable: str, run_id: str, ensemble: str, step: str) -> str:
    return f"icon_d2_ruc_eps_{variable}_{run_id}_e{ensemble}_{step}.grib2"


def build_url(variable: str, run_id: str, ensemble: str, step: str) -> str:
    run_url = run_id_to_url(run_id)
    if not config.DWD_HAS_ENSEMBLE:
        return f"{config.DWD_BASE}/{variable}/r/{run_url}/s/{step}.grib2"
    return f"{config.DWD_BASE}/{variable}/r/{run_url}/e/{ensemble}/s/{step}.grib2"


def list_remote_runs(variable: str = "TOT_PREC", limit: int | None = None) -> list[str]:
    """Fetch DWD index for variable, return run_ids newest first."""
    url = f"{config.DWD_BASE}/{variable}/r/"
    resp = requests.get(url, timeout=30, headers={"User-Agent": config.HTTP_USER_AGENT})
    resp.raise_for_status()
    soup = BeautifulSoup(resp.content, "html.parser")
    pattern = re.compile(r"(\d{4}-\d{2}-\d{2}T\d{2}%3A\d{2})/")
    runs = sorted({pattern.search(a.get("href", "")).group(1)
                   for a in soup.find_all("a")
                   if pattern.search(a.get("href", ""))}, reverse=True)
    ids = [url_to_run_id(r) for r in runs]
    return ids[:limit] if limit else ids


def list_remote_ensembles(variable: str, run_id: str) -> list[str]:
    if not config.DWD_HAS_ENSEMBLE:
        # Deterministic source: no e/{ensemble}/ layer. Use a synthetic single
        # member id so the rest of the pipeline (filenames, extract, stats)
        # doesn't need to know the difference.
        return ["00"]
    url = f"{config.DWD_BASE}/{variable}/r/{run_id_to_url(run_id)}/e/"
    resp = requests.get(url, timeout=30, headers={"User-Agent": config.HTTP_USER_AGENT})
    resp.raise_for_status()
    soup = BeautifulSoup(resp.content, "html.parser")
    ens = sorted({a.get("href", "")[:-1] for a in soup.find_all("a")
                  if a.get("href", "").endswith("/") and a.get("href", "")[:-1].isdigit()},
                 key=int)
    return ens


def list_remote_steps(variable: str, run_id: str, ensemble: str) -> list[str]:
    if config.DWD_HAS_ENSEMBLE:
        url = f"{config.DWD_BASE}/{variable}/r/{run_id_to_url(run_id)}/e/{ensemble}/s/"
    else:
        url = f"{config.DWD_BASE}/{variable}/r/{run_id_to_url(run_id)}/s/"
    resp = requests.get(url, timeout=30, headers={"User-Agent": config.HTTP_USER_AGENT})
    resp.raise_for_status()
    soup = BeautifulSoup(resp.content, "html.parser")
    steps = sorted({a.get("href", "").replace(".grib2", "")
                    for a in soup.find_all("a")
                    if a.get("href", "").endswith(".grib2") and "PT" in a.get("href", "")})
    return _filter_by_step_minutes(steps, config.VARIABLES[variable]["step_minutes"])


def _step_to_minutes(step: str) -> int | None:
    """'PT003H15M' -> 195 lead-time minutes, or None if unparseable."""
    m = re.match(r"PT(\d{3})H(\d{2})M", step)
    if not m:
        return None
    return int(m.group(1)) * 60 + int(m.group(2))


def _filter_by_step_minutes(steps: Iterable[str], step_minutes: int) -> list[str]:
    out = []
    for s in steps:
        total = _step_to_minutes(s)
        if total is None:
            continue
        if total % step_minutes == 0:
            out.append(s)
    return out


def remote_run_horizon(variable: str, run_id: str) -> datetime | None:
    """Latest valid-time DWD currently offers for `variable` at `run_id`.

    Grows while DWD is still uploading a run, so callers compare it against a
    cached run's last timestamp to detect runs captured mid-upload. Returns
    None when the run/variable can't be listed (treated as "leave as-is").
    """
    try:
        ensembles = list_remote_ensembles(variable, run_id)
        if not ensembles:
            return None
        steps = list_remote_steps(variable, run_id, ensembles[0])
    except requests.RequestException:
        return None
    minutes = [m for m in (_step_to_minutes(s) for s in steps) if m is not None]
    if not minutes:
        return None
    base = datetime.strptime(run_id, "%Y-%m-%dT%H%M").replace(tzinfo=timezone.utc)
    return base + timedelta(minutes=max(minutes))


def scan_local_runs(raw_dir: Path | None = None) -> dict[str, dict[str, list[Path]]]:
    """Scan data/raw/ -> {run_id: {variable: [paths sorted by step]}}."""
    raw_dir = raw_dir or config.RAW_DIR
    if not raw_dir.exists():
        return {}
    groups: dict[str, dict[str, list[Path]]] = defaultdict(lambda: defaultdict(list))
    for f in raw_dir.glob("icon_d2_ruc_eps_*.grib2"):
        m = _FILENAME_RE.match(f.name)
        if not m:
            continue
        run_id = f"{m.group('date')}T{m.group('hm')}"
        groups[run_id][m.group("var")].append(f)
    return {run_id: {v: sorted(paths) for v, paths in vars_.items()}
            for run_id, vars_ in sorted(groups.items(), reverse=True)}


def local_run_ids() -> list[str]:
    return list(scan_local_runs().keys())


def files_for_run(run_id: str, variable: str) -> list[Path]:
    """Return local files for a run+variable (sorted by ensemble then step)."""
    return scan_local_runs().get(run_id, {}).get(variable, [])


def parse_filename(path: Path) -> tuple[str, str, str, str] | None:
    """-> (variable, run_id, ensemble, step) or None."""
    m = _FILENAME_RE.match(path.name)
    if not m:
        return None
    return m.group("var"), f"{m.group('date')}T{m.group('hm')}", m.group("ens"), m.group("step")
