import json
from pathlib import Path

from kalshi_weather_hitbot.cli import _maybe_calibrated_p_yes, sync_settlements
from kalshi_weather_hitbot.config import AppConfig
from kalshi_weather_hitbot.db import DB
from kalshi_weather_hitbot.strategy.calibration import beta_posterior_mean


def test_beta_calibration_posterior_mean():
    assert beta_posterior_mean(1, 1, 0, 0) == 0.5
    assert beta_posterior_mean(1, 1, 3, 1) == 4 / 6


def test_settlement_ingest_writes_rows(monkeypatch, tmp_path: Path):
    db_path = tmp_path / "test.db"
    cfg = AppConfig(db_path=str(db_path))

    class FakeClient:
        def __init__(self, _cfg):
            pass

        def get_settlements(self, limit=200, cursor=None):
            _ = limit, cursor
            return {
                "settlements": [
                    {
                        "ticker": "KXHIGHCHI-TEST",
                        "market_result": "YES",
                        "revenue_cents": 123,
                        "fee_cost_dollars": "0.01",
                        "settled_time": "2026-02-25T00:00:00Z",
                    }
                ],
                "cursor": None,
            }

    monkeypatch.setattr("kalshi_weather_hitbot.cli._load_cfg", lambda: cfg)
    monkeypatch.setattr("kalshi_weather_hitbot.cli.KalshiClient", FakeClient)

    sync_settlements(max_pages=1, limit=50)

    db = DB(str(db_path))
    with db.connect() as con:
        row = con.execute("SELECT ticker, market_result, revenue_cents, fee_cost_dollars_str FROM settlements").fetchone()
    assert row == ("KXHIGHCHI-TEST", "YES", 123, "0.01")


def test_probability_override_only_when_enabled():
    cfg_disabled = AppConfig()
    cfg_disabled.calibration.enabled = False
    out_disabled = _maybe_calibrated_p_yes(
        cfg=cfg_disabled,
        base_p_yes=0.99,
        city_key="chicago",
        hours_to_close=2.0,
        lock_status="LOCKED_YES",
        calibration_lookup=lambda *_args: 0.61,
    )
    assert out_disabled == 0.99

    cfg_enabled = AppConfig()
    cfg_enabled.calibration.enabled = True
    out_enabled = _maybe_calibrated_p_yes(
        cfg=cfg_enabled,
        base_p_yes=0.99,
        city_key="chicago",
        hours_to_close=2.0,
        lock_status="LOCKED_YES",
        calibration_lookup=lambda *_args: 0.61,
    )
    assert out_enabled == 0.61
