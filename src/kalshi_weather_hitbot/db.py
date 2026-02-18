from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCHEMA = """
CREATE TABLE IF NOT EXISTS run_evaluations (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts TEXT NOT NULL,
  market_ticker TEXT NOT NULL,
  city_key TEXT,
  observed_max REAL,
  forecast_max_remaining REAL,
  min_possible REAL,
  max_possible REAL,
  lock_status TEXT,
  p_yes REAL,
  chosen_side TEXT,
  chosen_price_cents INTEGER,
  reason TEXT,
  raw_payload TEXT
);
CREATE TABLE IF NOT EXISTS orders (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts TEXT NOT NULL,
  market_ticker TEXT,
  client_order_id TEXT,
  request_json TEXT,
  response_json TEXT,
  status TEXT
);
CREATE TABLE IF NOT EXISTS market_snapshots (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts TEXT NOT NULL,
  market_ticker TEXT NOT NULL,
  title TEXT,
  subtitle TEXT,
  rules_primary TEXT,
  payload TEXT
);
CREATE TABLE IF NOT EXISTS capital_config (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts TEXT NOT NULL,
  cap_mode TEXT,
  cap_value REAL,
  derived_cap_dollars REAL
);
CREATE TABLE IF NOT EXISTS city_mapping_snapshots (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts TEXT NOT NULL,
  yaml_text TEXT NOT NULL,
  source TEXT NOT NULL
);
"""


class DB:
    def __init__(self, db_path: str) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as con:
            con.executescript(SCHEMA)

    @contextmanager
    def connect(self):
        con = sqlite3.connect(self.db_path)
        try:
            yield con
            con.commit()
        finally:
            con.close()

    def _ts(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    def insert_market_snapshot(self, market: dict[str, Any]) -> None:
        with self.connect() as con:
            con.execute(
                "INSERT INTO market_snapshots(ts, market_ticker, title, subtitle, rules_primary, payload) VALUES (?, ?, ?, ?, ?, ?)",
                (
                    self._ts(),
                    market.get("ticker"),
                    market.get("title"),
                    market.get("subtitle"),
                    market.get("rules_primary") or market.get("rules"),
                    json.dumps(market),
                ),
            )

    def insert_evaluation(self, payload: dict[str, Any]) -> None:
        with self.connect() as con:
            con.execute(
                """INSERT INTO run_evaluations(
                ts, market_ticker, city_key, observed_max, forecast_max_remaining,
                min_possible, max_possible, lock_status, p_yes, chosen_side,
                chosen_price_cents, reason, raw_payload
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    self._ts(),
                    payload.get("market_ticker"),
                    payload.get("city_key"),
                    payload.get("observed_max"),
                    payload.get("forecast_max_remaining"),
                    payload.get("min_possible"),
                    payload.get("max_possible"),
                    payload.get("lock_status"),
                    payload.get("p_yes"),
                    payload.get("chosen_side"),
                    payload.get("chosen_price_cents"),
                    payload.get("reason"),
                    json.dumps(payload),
                ),
            )

    def insert_order(self, market_ticker: str, client_order_id: str, request_json: dict[str, Any], response_json: dict[str, Any], status: str) -> None:
        with self.connect() as con:
            con.execute(
                "INSERT INTO orders(ts, market_ticker, client_order_id, request_json, response_json, status) VALUES (?, ?, ?, ?, ?, ?)",
                (self._ts(), market_ticker, client_order_id, json.dumps(request_json), json.dumps(response_json), status),
            )

    def save_capital(self, cap_mode: str, cap_value: float, derived_cap_dollars: float) -> None:
        with self.connect() as con:
            con.execute(
                "INSERT INTO capital_config(ts, cap_mode, cap_value, derived_cap_dollars) VALUES (?, ?, ?, ?)",
                (self._ts(), cap_mode, cap_value, derived_cap_dollars),
            )


    def save_city_mapping_snapshot(self, yaml_text: str, source: str = "bootstrap-cities") -> None:
        with self.connect() as con:
            con.execute(
                "INSERT INTO city_mapping_snapshots(ts, yaml_text, source) VALUES (?, ?, ?)",
                (self._ts(), yaml_text, source),
            )
