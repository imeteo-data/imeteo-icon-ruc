"""Tests for DWD source resolution and URL building in pipeline/discover.py.

The pipeline must run on icon-d2-ruc-eps (20-member ensemble) and fall back
to its deterministic sibling icon-d2-ruc automatically when the ensemble
source is down — the behaviour that kept the dashboard publishing through
the 2026-07-02 → 2026-07-04 DWD outage, now without a manual config flip.
"""
from __future__ import annotations

import pytest
import requests

from pipeline import config, discover

EPS_BASE = config.DWD_SOURCES[0]["base"]
DET_BASE = config.DWD_SOURCES[1]["base"]

RUN_INDEX_HTML = b'<html><a href="2026-07-04T14%3A00/">x</a></html>'
EMPTY_HTML = b"<html>no runs here</html>"


class _FakeResponse:
    def __init__(self, content: bytes = RUN_INDEX_HTML, status: int = 200):
        self.content = content
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code}")


@pytest.fixture(autouse=True)
def _reset_active_source():
    discover._active_source = None
    yield
    discover._active_source = None


def _fake_get(responses_by_prefix):
    """requests.get stub routing by URL prefix. Unmatched URLs → 404."""
    def get(url, **kwargs):
        for prefix, resp in responses_by_prefix.items():
            if url.startswith(prefix):
                return resp() if callable(resp) else resp
        return _FakeResponse(b"", 404)
    return get


# ── active_source ──────────────────────────────────────────
def test_primary_source_wins_when_up(monkeypatch):
    monkeypatch.setattr(requests, "get", _fake_get({EPS_BASE: _FakeResponse()}))
    src = discover.active_source()
    assert src["name"] == "icon-d2-ruc-eps"
    assert src["has_ensemble"] is True


def test_falls_back_when_primary_404s(monkeypatch):
    monkeypatch.setattr(requests, "get", _fake_get({
        EPS_BASE: _FakeResponse(b"", 404),
        DET_BASE: _FakeResponse(),
    }))
    src = discover.active_source()
    assert src["name"] == "icon-d2-ruc"
    assert src["has_ensemble"] is False


def test_falls_back_when_primary_index_is_empty(monkeypatch):
    monkeypatch.setattr(requests, "get", _fake_get({
        EPS_BASE: _FakeResponse(EMPTY_HTML),
        DET_BASE: _FakeResponse(),
    }))
    assert discover.active_source()["name"] == "icon-d2-ruc"


def test_raises_when_all_sources_down(monkeypatch):
    monkeypatch.setattr(requests, "get", _fake_get({}))
    with pytest.raises(requests.RequestException):
        discover.active_source()


def test_source_is_memoized_until_refresh(monkeypatch):
    calls = []

    def counting_get(url, **kwargs):
        calls.append(url)
        return _FakeResponse()

    monkeypatch.setattr(requests, "get", counting_get)
    discover.active_source()
    discover.active_source()
    assert len(calls) == 1
    discover.active_source(refresh=True)
    assert len(calls) == 2


# ── URL building per source ────────────────────────────────
def test_build_url_ensemble_layout(monkeypatch):
    monkeypatch.setattr(requests, "get", _fake_get({EPS_BASE: _FakeResponse()}))
    url = discover.build_url("TOT_PREC", "2026-07-04T1400", "01", "PT000H05M")
    assert url == (f"{EPS_BASE}/TOT_PREC/r/2026-07-04T14%3A00"
                   "/e/01/s/PT000H05M.grib2")


def test_build_url_deterministic_layout(monkeypatch):
    monkeypatch.setattr(requests, "get", _fake_get({DET_BASE: _FakeResponse()}))
    url = discover.build_url("TOT_PREC", "2026-07-04T1400", "00", "PT000H05M")
    assert url == f"{DET_BASE}/TOT_PREC/r/2026-07-04T14%3A00/s/PT000H05M.grib2"


def test_deterministic_source_reports_synthetic_member(monkeypatch):
    monkeypatch.setattr(requests, "get", _fake_get({DET_BASE: _FakeResponse()}))
    assert discover.list_remote_ensembles("TOT_PREC", "2026-07-04T1400") == ["00"]


def test_list_remote_runs_uses_active_source(monkeypatch):
    monkeypatch.setattr(requests, "get", _fake_get({
        EPS_BASE: _FakeResponse(b"", 404),
        DET_BASE: _FakeResponse(),
    }))
    assert discover.list_remote_runs(limit=5) == ["2026-07-04T1400"]
