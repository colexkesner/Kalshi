from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

import streamlit as st

from kalshi_weather_hitbot.cli import _load_cfg
from kalshi_weather_hitbot.kalshi.client import APIError, KalshiClient
from kalshi_weather_hitbot.strategy.risk import compute_open_orders_exposure, compute_positions_exposure


DEFAULT_DB = Path("./kalshi_weather_hitbot.db")
DEFAULT_CITIES = Path("./configs/cities.yaml")


def _query_rows(db_path: Path, sql: str, params: tuple = ()) -> list[dict]:
    if not db_path.exists():
        return []
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    try:
        rows = con.execute(sql, params).fetchall()
        return [dict(r) for r in rows]
    finally:
        con.close()


def _scalar(db_path: Path, sql: str, params: tuple = ()) -> int:
    if not db_path.exists():
        return 0
    con = sqlite3.connect(db_path)
    try:
        row = con.execute(sql, params).fetchone()
        return int(row[0] or 0) if row else 0
    finally:
        con.close()


def _safe_json(value: str | None) -> dict | list | str | None:
    if not value:
        return None
    try:
        return json.loads(value)
    except Exception:
        return value


def _load_city_health(cities_path: Path) -> tuple[int, int, int]:
    if not cities_path.exists():
        return (0, 0, 0)
    try:
        import yaml

        payload = yaml.safe_load(cities_path.read_text()) or {}
        if not isinstance(payload, dict):
            return (0, 0, 0)
        total = len(payload)
        usable = sum(
            1
            for city in payload.values()
            if isinstance(city, dict)
            and city.get("icao_station")
            and city.get("lat") is not None
            and city.get("lon") is not None
            and city.get("tz")
        )
        return (total, usable, total - usable)
    except Exception:
        return (0, 0, 0)


def _cents_to_dollars(value: Any) -> float:
    try:
        return float(value) / 100.0
    except Exception:
        return 0.0


def _live_account_snapshot() -> dict[str, Any]:
    cfg = _load_cfg()
    client = KalshiClient(cfg)
    balance = client.get_balance() if cfg.api_key_id else {"balance": 0}
    positions = client.get_positions() if cfg.api_key_id else []
    open_orders = client.list_orders(status="open") if cfg.api_key_id else []
    try:
        resting_orders = client.list_orders(status="resting") if cfg.api_key_id else []
    except Exception:
        resting_orders = []
    try:
        filled_orders = client.list_orders(status="filled") if cfg.api_key_id else []
    except Exception:
        filled_orders = []
    try:
        canceled_orders = client.list_orders(status="canceled") if cfg.api_key_id else []
    except Exception:
        canceled_orders = []

    # Some environments treat "open" and "resting" similarly; dedupe by order id.
    seen_order_ids: set[str] = set()
    merged_open: list[dict[str, Any]] = []
    for order in [*open_orders, *resting_orders]:
        oid = str(order.get("order_id") or order.get("id") or "")
        if oid and oid in seen_order_ids:
            continue
        if oid:
            seen_order_ids.add(oid)
        merged_open.append(order)

    out = {
        "cfg_env": cfg.env,
        "cfg_base_url": cfg.base_url,
        "balance_raw": balance,
        "positions": positions,
        "open_orders": merged_open,
        "filled_orders": filled_orders,
        "canceled_orders": canceled_orders,
        "available_balance_dollars": _cents_to_dollars(balance.get("balance")),
        "portfolio_value_dollars": _cents_to_dollars(balance.get("portfolio_value")),
        "positions_exposure_dollars": compute_positions_exposure(positions),
        "open_orders_exposure_dollars": compute_open_orders_exposure(merged_open),
    }
    return out


def _strategy_hint(eval_row: dict[str, Any], positions_by_ticker: dict[str, dict[str, Any]], open_by_ticker: dict[str, list[dict[str, Any]]]) -> str:
    ticker = str(eval_row.get("market_ticker") or "")
    lock_status = str(eval_row.get("lock_status") or "")
    pos = positions_by_ticker.get(ticker)
    open_orders = open_by_ticker.get(ticker, [])

    if pos:
        side = str(pos.get("side") or pos.get("position_side") or "").upper()
        qty = pos.get("contracts") or pos.get("position") or 0
        if lock_status == "LOCKED_NO" and side == "NO":
            return f"HOLD/WAIT EXIT (long NO x{qty})"
        if lock_status == "LOCKED_YES" and side == "YES":
            return f"HOLD/WAIT EXIT (long YES x{qty})"
        return f"POSITION EXISTS ({side} x{qty}) - review"

    if open_orders:
        return f"WAIT (open order {len(open_orders)})"

    if lock_status == "LOCKED_NO":
        return "BUY NO candidate"
    if lock_status == "LOCKED_YES":
        return "BUY YES candidate"
    return "HOLD (unlocked)"


def _positions_table_rows(positions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for p in positions:
        exposure = p.get("market_exposure_dollars")
        if exposure is None:
            raw_exposure = p.get("market_exposure")
            exposure = f"{_cents_to_dollars(raw_exposure):.2f}" if raw_exposure is not None else None
        rows.append(
            {
                "ticker": p.get("ticker") or p.get("market_ticker"),
                "side": p.get("side") or p.get("position_side"),
                "contracts": p.get("contracts") or p.get("position") or p.get("count"),
                "avg_price": p.get("avg_price") or p.get("average_price"),
                "market_exposure": exposure,
                "realized_pnl": p.get("realized_pnl") or p.get("realized_pnl_dollars"),
                "unrealized_pnl": p.get("unrealized_pnl") or p.get("unrealized_pnl_dollars"),
            }
        )
    return rows


def _to_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except Exception:
        return None


def _position_settlement_estimates(positions: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, float]]:
    rows: list[dict[str, Any]] = []
    total_cost = 0.0
    total_max_profit = 0.0
    total_max_loss = 0.0

    for p in positions:
        ticker = str(p.get("ticker") or p.get("market_ticker") or "")
        side = str(p.get("side") or p.get("position_side") or "").upper()
        contracts_val = _to_float(p.get("contracts") or p.get("position") or p.get("count")) or 0.0
        contracts = abs(contracts_val)
        avg_price_cents = _to_float(p.get("avg_price") or p.get("average_price") or p.get("cost_basis"))

        if contracts <= 0 or side not in {"YES", "NO"}:
            continue
        if avg_price_cents is None:
            # Fall back to zero if missing; show blanks rather than crash.
            avg_price_cents = 0.0

        cost_per_contract = avg_price_cents / 100.0
        total_cost_dollars = contracts * cost_per_contract
        max_payout_if_correct = contracts * 1.0
        max_profit_if_correct = max_payout_if_correct - total_cost_dollars
        max_loss_if_wrong = total_cost_dollars

        total_cost += total_cost_dollars
        total_max_profit += max_profit_if_correct
        total_max_loss += max_loss_if_wrong

        rows.append(
            {
                "ticker": ticker,
                "side": side,
                "contracts": contracts,
                "avg_price_paid": round(cost_per_contract, 4),
                "cost_total": round(total_cost_dollars, 4),
                "max_payout_if_correct": round(max_payout_if_correct, 4),
                "max_profit_if_correct": round(max_profit_if_correct, 4),
                "max_loss_if_wrong": round(max_loss_if_wrong, 4),
                "note": "Settlement estimate before fees",
            }
        )

    totals = {
        "cost_total": round(total_cost, 4),
        "max_profit_if_all_correct": round(total_max_profit, 4),
        "max_loss_if_all_wrong": round(total_max_loss, 4),
    }
    return rows, totals


def _orders_table_rows(orders: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for o in orders:
        rows.append(
            {
                "ticker": o.get("ticker") or o.get("market_ticker"),
                "status": o.get("status"),
                "side": o.get("side"),
                "action": o.get("action"),
                "count": o.get("remaining_count") or o.get("count") or o.get("count_fp"),
                "yes_price": o.get("yes_price_dollars") or o.get("yes_price"),
                "no_price": o.get("no_price_dollars") or o.get("no_price"),
                "client_order_id": o.get("client_order_id"),
                "order_id": o.get("order_id") or o.get("id"),
                "created_time": o.get("created_time"),
            }
        )
    return rows


def main() -> None:
    st.set_page_config(page_title="Kalshi Hitbot Monitor", layout="wide")
    st.title("Kalshi Hitbot Monitor")
    st.caption("Read-only local dashboard for bot state + live Kalshi portfolio/order visibility.")

    with st.sidebar:
        db_path = Path(st.text_input("SQLite DB Path", str(DEFAULT_DB)))
        cities_path = Path(st.text_input("Cities YAML Path", str(DEFAULT_CITIES)))
        refresh = st.number_input("Refresh every N seconds (0 = manual)", min_value=0, max_value=300, value=60, step=5)
        row_limit = st.number_input("Rows per table", min_value=10, max_value=500, value=100, step=10)
        include_live = st.checkbox("Fetch live Kalshi account data", value=True)
        st.button("Refresh now", use_container_width=True)

    if refresh > 0:
        st.markdown(f"<meta http-equiv='refresh' content='{int(refresh)}'>", unsafe_allow_html=True)

    total_cities, usable_cities, skipped_cities = _load_city_health(cities_path)
    total_orders = _scalar(db_path, "SELECT COUNT(*) FROM orders")
    submitted_orders = _scalar(db_path, "SELECT COUNT(*) FROM orders WHERE status = 'SUBMITTED'")
    dry_run_orders = _scalar(db_path, "SELECT COUNT(*) FROM orders WHERE status = 'DRY_RUN'")
    total_evals = _scalar(db_path, "SELECT COUNT(*) FROM run_evaluations")
    total_submitted_buy = _scalar(db_path, "SELECT COUNT(*) FROM orders WHERE status='SUBMITTED' AND lower(json_extract(request_json, '$.action'))='buy'")
    total_submitted_sell = _scalar(db_path, "SELECT COUNT(*) FROM orders WHERE status='SUBMITTED' AND lower(json_extract(request_json, '$.action'))='sell'")

    live: dict[str, Any] | None = None
    live_error: str | None = None
    if include_live:
        try:
            live = _live_account_snapshot()
        except (APIError, Exception) as exc:
            live_error = str(exc)

    # Top summary row
    c1, c2, c3, c4, c5, c6 = st.columns(6)
    c1.metric("Cities", total_cities)
    c2.metric("Usable Cities", usable_cities)
    c3.metric("Skipped Cities", skipped_cities)
    c4.metric("DB Submitted Orders", submitted_orders)
    c5.metric("DB Dry-Run Orders", dry_run_orders)
    c6.metric("DB Evaluations", total_evals)
    st.caption(
        f"DB totals: orders={total_orders} | submitted_buys={total_submitted_buy} | submitted_sells={total_submitted_sell}"
    )

    if live_error:
        st.warning(f"Live account data unavailable: {live_error}")

    if live:
        st.subheader("Live Kalshi Account (Read-Only)")
        h1, h2, h3, h4, h5, h6 = st.columns(6)
        h1.metric("Env", str(live["cfg_env"]))
        h2.metric("Cash Balance", f"${live['available_balance_dollars']:.2f}")
        h3.metric("Portfolio Value", f"${live['portfolio_value_dollars']:.2f}")
        h4.metric("Position Exposure", f"${live['positions_exposure_dollars']:.2f}")
        h5.metric("Open Order Exposure", f"${live['open_orders_exposure_dollars']:.2f}")
        h6.metric("Open Orders", str(len(live["open_orders"])))
        st.caption(
            f"Positions={len(live['positions'])} | Filled orders={len(live['filled_orders'])} | "
            f"Canceled orders={len(live['canceled_orders'])} | Base URL={live['cfg_base_url']}"
        )

        pcol, ocol = st.columns(2)
        with pcol:
            st.markdown("**Current Positions**")
            pos_rows = _positions_table_rows(live["positions"])
            if pos_rows:
                st.dataframe(pos_rows, use_container_width=True, height=320)
            else:
                st.info("No current positions.")
        with ocol:
            st.markdown("**Open / Resting Orders**")
            open_rows = _orders_table_rows(live["open_orders"])
            if open_rows:
                st.dataframe(open_rows, use_container_width=True, height=320)
            else:
                st.info("No open/resting orders.")

        fcol, ccol = st.columns(2)
        with fcol:
            st.markdown("**Recent Filled Orders (API)**")
            filled_rows = _orders_table_rows(live["filled_orders"][: int(row_limit)])
            if filled_rows:
                st.dataframe(filled_rows, use_container_width=True, height=260)
            else:
                st.info("No filled orders returned.")
        with ccol:
            st.markdown("**Recent Canceled Orders (API)**")
            canceled_rows = _orders_table_rows(live["canceled_orders"][: int(row_limit)])
            if canceled_rows:
                st.dataframe(canceled_rows, use_container_width=True, height=260)
            else:
                st.info("No canceled orders returned.")

        st.markdown("**Settlement P/L Estimator (Current Positions)**")
        est_rows, est_totals = _position_settlement_estimates(live["positions"])
        e1, e2, e3 = st.columns(3)
        e1.metric("Position Cost Basis (Est.)", f"${est_totals['cost_total']:.2f}")
        e2.metric("Max Profit If All Correct", f"${est_totals['max_profit_if_all_correct']:.2f}")
        e3.metric("Max Loss If All Wrong", f"${est_totals['max_loss_if_all_wrong']:.2f}")
        if est_rows:
            st.dataframe(est_rows, use_container_width=True, height=260)
            st.caption(
                "Estimator assumes binary settlement ($1 winner / $0 loser) and uses current position average price fields. "
                "Fees and partial fills can change realized results."
            )
        else:
            st.info("No live positions to estimate settlement P/L.")

    recent_orders = _query_rows(
        db_path,
        "SELECT id, ts, market_ticker, client_order_id, status, request_json, response_json "
        "FROM orders ORDER BY id DESC LIMIT ?",
        (int(row_limit),),
    )
    recent_evals = _query_rows(
        db_path,
        "SELECT id, ts, market_ticker, city_key, lock_status, p_yes, observed_max, forecast_max_remaining, min_possible, max_possible "
        "FROM run_evaluations ORDER BY id DESC LIMIT ?",
        (int(row_limit),),
    )

    st.subheader("Strategy View (Latest Evaluations + Live State)")
    positions_by_ticker: dict[str, dict[str, Any]] = {}
    open_by_ticker: dict[str, list[dict[str, Any]]] = {}
    if live:
        positions_by_ticker = {
            str(p.get("ticker") or p.get("market_ticker") or ""): p
            for p in live["positions"]
            if p.get("ticker") or p.get("market_ticker")
        }
        for order in live["open_orders"]:
            t = str(order.get("ticker") or order.get("market_ticker") or "")
            if not t:
                continue
            open_by_ticker.setdefault(t, []).append(order)

    strategy_rows: list[dict[str, Any]] = []
    for row in recent_evals[: min(len(recent_evals), int(row_limit))]:
        strategy_rows.append(
            {
                "ts": row.get("ts"),
                "ticker": row.get("market_ticker"),
                "city": row.get("city_key"),
                "lock": row.get("lock_status"),
                "p_yes": row.get("p_yes"),
                "obs_max": row.get("observed_max"),
                "fc_max": row.get("forecast_max_remaining"),
                "strategy_hint": _strategy_hint(row, positions_by_ticker, open_by_ticker),
            }
        )
    if strategy_rows:
        st.dataframe(strategy_rows, use_container_width=True, height=320)
        st.caption(
            "Strategy hints are read-only heuristics from latest lock evaluations + current open orders/positions. "
            "They are not direct trading instructions."
        )
    else:
        st.info("No evaluations yet for strategy view.")

    left, right = st.columns(2)
    with left:
        st.subheader("Recent Orders (Bot DB)")
        if not recent_orders:
            st.info("No orders recorded yet.")
        else:
            preview_rows: list[dict[str, Any]] = []
            for row in recent_orders:
                req = _safe_json(row.get("request_json"))
                resp = _safe_json(row.get("response_json"))
                preview_rows.append(
                    {
                        "id": row.get("id"),
                        "ts": row.get("ts"),
                        "ticker": row.get("market_ticker"),
                        "status": row.get("status"),
                        "side": (req or {}).get("side") if isinstance(req, dict) else None,
                        "action": (req or {}).get("action") if isinstance(req, dict) else None,
                        "count": (req or {}).get("count") if isinstance(req, dict) else None,
                        "yes_price": (
                            (req or {}).get("yes_price_dollars") or (req or {}).get("yes_price")
                        )
                        if isinstance(req, dict)
                        else None,
                        "no_price": (
                            (req or {}).get("no_price_dollars") or (req or {}).get("no_price")
                        )
                        if isinstance(req, dict)
                        else None,
                        "client_order_id": row.get("client_order_id"),
                        "response": resp if isinstance(resp, (dict, list)) else str(resp),
                    }
                )
            st.dataframe(preview_rows, use_container_width=True, height=420)

    with right:
        st.subheader("Recent Evaluations (Bot DB)")
        if not recent_evals:
            st.info("No evaluations recorded yet.")
        else:
            st.dataframe(recent_evals, use_container_width=True, height=420)

    latest_snapshots = _query_rows(
        db_path,
        "SELECT id, ts, source FROM city_mapping_snapshots ORDER BY id DESC LIMIT 10",
    )
    st.subheader("City Mapping Snapshots")
    if latest_snapshots:
        st.dataframe(latest_snapshots, use_container_width=True, height=220)
    else:
        st.info("No city mapping snapshots recorded yet.")

    st.subheader("How To Use")
    st.code("streamlit run src/kalshi_weather_hitbot/monitor_dashboard.py", language="bash")
    st.caption("Install monitor dependencies first: pip install -e .[monitor]  (or .[dev,monitor])")


if __name__ == "__main__":
    main()
