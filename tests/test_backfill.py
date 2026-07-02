"""Tests for backfill + completeness logic in pipeline/run.py and discover.py.

These cover the self-healing behaviour that fills hours the scheduler dropped
and re-fetches runs that were captured mid-upload by DWD.
"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone

from pipeline import config, discover, run


def _write_run(dirpath, run_id: str, last_time_iso: str, var: str = "TOT_PREC"):
    """One forecast JSON per configured location ({run_id}_{location_id}.json),
    matching what run.process_run writes since the multi-location change."""
    paths = []
    for loc_id in config.LOCATIONS:
        p = dirpath / f"{run_id}_{loc_id}.json"
        p.write_text(json.dumps({
            "run_id": run_id,
            "location_id": loc_id,
            "variables": {var: {"times": ["2026-05-29T10:00:00Z", last_time_iso]}},
        }))
        paths.append(p)
    return paths


# ── discover._step_to_minutes ──────────────────────────────
def test_step_to_minutes_parses_hours_and_minutes():
    assert discover._step_to_minutes("PT003H15M") == 195
    assert discover._step_to_minutes("PT000H00M") == 0


def test_step_to_minutes_returns_none_on_garbage():
    assert discover._step_to_minutes("not-a-step") is None


# ── run._local_run_horizon ─────────────────────────────────
def test_local_run_horizon_none_when_json_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "FORECAST_DIR", tmp_path)
    assert run._local_run_horizon("2026-05-29T1000") is None


def test_local_run_horizon_reads_last_timestamp(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "FORECAST_DIR", tmp_path)
    _write_run(tmp_path, "2026-05-29T1000", "2026-05-29T14:00:00Z")
    assert run._local_run_horizon("2026-05-29T1000") == \
        datetime(2026, 5, 29, 14, 0, tzinfo=timezone.utc)


# ── run._is_run_complete ───────────────────────────────────
def test_is_run_complete_false_when_json_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "FORECAST_DIR", tmp_path)
    monkeypatch.setattr(discover, "remote_run_horizon",
                        lambda v, r: datetime(2026, 5, 29, 14, tzinfo=timezone.utc))
    assert run._is_run_complete("2026-05-29T1000") is False


def test_is_run_complete_false_when_local_shorter_than_remote(tmp_path, monkeypatch):
    # Captured mid-upload: local stops at 12:00 but DWD already offers 14:00.
    monkeypatch.setattr(config, "FORECAST_DIR", tmp_path)
    _write_run(tmp_path, "2026-05-29T1000", "2026-05-29T12:00:00Z")
    monkeypatch.setattr(discover, "remote_run_horizon",
                        lambda v, r: datetime(2026, 5, 29, 14, tzinfo=timezone.utc))
    assert run._is_run_complete("2026-05-29T1000") is False


def test_is_run_complete_true_when_local_reaches_remote(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "FORECAST_DIR", tmp_path)
    _write_run(tmp_path, "2026-05-29T1000", "2026-05-29T14:00:00Z")
    monkeypatch.setattr(discover, "remote_run_horizon",
                        lambda v, r: datetime(2026, 5, 29, 14, tzinfo=timezone.utc))
    assert run._is_run_complete("2026-05-29T1000") is True


def test_is_run_complete_true_when_remote_unreachable(tmp_path, monkeypatch):
    # If DWD listing fails, keep what we already have rather than re-fetching forever.
    monkeypatch.setattr(config, "FORECAST_DIR", tmp_path)
    _write_run(tmp_path, "2026-05-29T1000", "2026-05-29T14:00:00Z")
    monkeypatch.setattr(discover, "remote_run_horizon", lambda v, r: None)
    assert run._is_run_complete("2026-05-29T1000") is True


# ── run.process_runs backfill skipping ─────────────────────
def test_process_runs_skips_complete_processes_incomplete(monkeypatch):
    processed: list[str] = []

    async def fake_process_run(run_id, offline=False):
        processed.append(run_id)
        return [config.FORECAST_DIR / f"{run_id}_bratislava.json"]

    monkeypatch.setattr(run, "process_run", fake_process_run)
    monkeypatch.setattr(run, "_is_run_complete", lambda rid: rid == "2026-05-29T0900")

    out = asyncio.run(run.process_runs(
        ["2026-05-29T1000", "2026-05-29T0900", "2026-05-29T0800"],
        skip_complete=True,
        wait_for_upload=False,
    ))

    assert processed == ["2026-05-29T1000", "2026-05-29T0800"]
    assert len(out) == 2


def test_process_runs_without_skip_processes_everything(monkeypatch):
    processed: list[str] = []

    async def fake_process_run(run_id, offline=False):
        processed.append(run_id)
        return [config.FORECAST_DIR / f"{run_id}_bratislava.json"]

    monkeypatch.setattr(run, "process_run", fake_process_run)
    # Even if everything looks complete, default behaviour reprocesses.
    monkeypatch.setattr(run, "_is_run_complete", lambda rid: True)

    out = asyncio.run(run.process_runs(["a", "b"], wait_for_upload=False))

    assert processed == ["a", "b"]
    assert len(out) == 2
