"""Retention: raw GRIBs are pruned to config.RAW_RETAIN runs while forecast
JSONs are kept to config.FORECAST_RETAIN — the two windows are independent so
data/raw stays bounded on the persistent self-hosted runner without shrinking
the dashboard history backfill relies on.
"""
from __future__ import annotations

from pipeline import config, discover, run

# 5 runs, ascending; "2026-05-29T1200" is newest.
RUN_IDS = [
    "2026-05-29T0800", "2026-05-29T0900", "2026-05-29T1000",
    "2026-05-29T1100", "2026-05-29T1200",
]


def _touch_raw(raw_dir, run_id):
    for suffix in (".grib2", ".grib2.idx"):
        (raw_dir / f"icon_d2_ruc_eps_TOT_PREC_{run_id}_e01_PT000H00M{suffix}").write_bytes(b"x")


def _touch_jsons(fc_dir, run_id):
    for loc_id in config.LOCATIONS:
        (fc_dir / f"{run_id}_{loc_id}.json").write_text("{}")


def _seed(tmp_path, monkeypatch, raw_keep, forecast_keep):
    raw, fc = tmp_path / "raw", tmp_path / "forecasts"
    raw.mkdir()
    fc.mkdir()
    monkeypatch.setattr(config, "RAW_DIR", raw)
    monkeypatch.setattr(config, "FORECAST_DIR", fc)
    monkeypatch.setattr(config, "RAW_RETAIN", raw_keep)
    monkeypatch.setattr(config, "FORECAST_RETAIN", forecast_keep)
    for rid in RUN_IDS:
        _touch_raw(raw, rid)
        _touch_jsons(fc, rid)
    return raw, fc


def _raw_runs(raw):
    return list(discover.scan_local_runs(raw).keys())  # newest-first


def _forecast_runs(fc):
    return sorted({p.stem[:15] for p in fc.glob("*.json")}, reverse=True)


def test_raw_pruned_to_one_forecasts_kept(tmp_path, monkeypatch):
    raw, fc = _seed(tmp_path, monkeypatch, raw_keep=1, forecast_keep=3)

    run._prune_old_runs()

    # Raw: only the newest run survives — grib2 AND its .idx — while every
    # stale run's grib2 and .idx sidecar are removed.
    assert _raw_runs(raw) == ["2026-05-29T1200"]
    assert sorted(p.name for p in raw.iterdir()) == [
        "icon_d2_ruc_eps_TOT_PREC_2026-05-29T1200_e01_PT000H00M.grib2",
        "icon_d2_ruc_eps_TOT_PREC_2026-05-29T1200_e01_PT000H00M.grib2.idx",
    ]
    # Forecasts: the newest 3 runs (all locations) survive independently.
    assert _forecast_runs(fc) == [
        "2026-05-29T1200", "2026-05-29T1100", "2026-05-29T1000",
    ]
    assert len(list(fc.glob("*.json"))) == 3 * len(config.LOCATIONS)


def test_raw_retain_of_one_survives_a_multi_run_backfill(tmp_path, monkeypatch):
    # Even when the forecast window is wide (backfill kept many JSONs), raw is
    # capped at a single run so a long-gap backfill can't fill the disk.
    raw, fc = _seed(tmp_path, monkeypatch, raw_keep=1, forecast_keep=12)

    run._prune_old_runs()

    assert _raw_runs(raw) == ["2026-05-29T1200"]
    assert _forecast_runs(fc) == list(reversed(RUN_IDS))  # all 5 kept (< 12)
