from __future__ import annotations

import signal
import time
from datetime import datetime, timezone
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from kalshi_weather_hitbot.config import AppConfig, EnvSettings, load_yaml_config, save_yaml_config
from kalshi_weather_hitbot.data.city_bootstrap import build_city_mapping, dump_city_mapping_yaml
from kalshi_weather_hitbot.data.city_mapping import load_city_mapping
from kalshi_weather_hitbot.data.metar import MetarClient, max_observed_temp_f
from kalshi_weather_hitbot.data.nws import NWSClient, max_forecast_temp_f
from kalshi_weather_hitbot.db import DB
from kalshi_weather_hitbot.kalshi.client import APIError, KalshiClient
from kalshi_weather_hitbot.kalshi.models import normalize_orderbook
from kalshi_weather_hitbot.strategy.execution import build_client_order_id_deterministic, select_exit_order, select_order
from kalshi_weather_hitbot.strategy.maker import maker_first_entry_price
from kalshi_weather_hitbot.strategy.model import evaluate_lock
from kalshi_weather_hitbot.strategy.risk import (
    compute_cap_dollars,
    compute_open_orders_exposure,
    compute_positions_exposure,
    enforce_cap,
)
from kalshi_weather_hitbot.strategy.screener import climate_window_start, parse_temperature_market

app = typer.Typer(
    help="Kalshi weather hit-rate bot. Environment via KALSHI_ENV=demo|production (demo default)."
)
console = Console()
RUNNING = True


def _signal_handler(_sig, _frame):
    global RUNNING
    RUNNING = False


signal.signal(signal.SIGINT, _signal_handler)


def _load_cfg() -> AppConfig:
    env = EnvSettings.load()
    cfg = load_yaml_config(Path(env.kalshi_config_path))
    if env.kalshi_api_key_id:
        cfg.api_key_id = env.kalshi_api_key_id
    if env.kalshi_private_key_path:
        cfg.private_key_path = env.kalshi_private_key_path
    cfg.trading_enabled = env.kalshi_trading_enabled or cfg.trading_enabled
    cfg.db_path = env.kalshi_db_path
    cfg.env = env.kalshi_env
    cfg.base_url = _choose_base(cfg.env)
    return cfg


def _choose_base(env: str) -> str:
    return "https://api.elections.kalshi.com" if env == "production" else "https://demo-api.kalshi.co"


def _available_dollars(balance_data: dict) -> float:
    return float(balance_data.get("balance") or 0) / 100.0


def _parse_cap_override(cap: str | None, available_dollars: float, cfg: AppConfig) -> float:
    if not cap:
        return compute_cap_dollars(available_dollars, cfg.capital.cap_mode, cfg.capital.cap_value)
    if cap.strip().endswith("%"):
        val = float(cap.strip().replace("%", ""))
        return compute_cap_dollars(available_dollars, "percent", val)
    return compute_cap_dollars(available_dollars, "dollars", float(cap.strip()))


def _cents_to_dollar_str(price_cents: int) -> str:
    return f"{(price_cents / 100.0):.2f}"


def _order_payload(
    cfg: AppConfig,
    ticker: str,
    decision,
    count: int,
    tif: str,
    post_only: bool,
    strategy_mode: str,
    cycle_key: str,
) -> dict:
    payload = {
        "ticker": ticker,
        "side": decision.side.lower(),
        "action": decision.action.lower(),
        "count": count,
        "count_fp": f"{count:.2f}",
        "time_in_force": tif,
        "post_only": post_only,
        "client_order_id": build_client_order_id_deterministic(
            market_ticker=ticker,
            side=decision.side,
            action=decision.action,
            price_cents=int(decision.price_cents),
            count=count,
            strategy_mode=strategy_mode,
            cycle_key=cycle_key,
        ),
    }

    if cfg.risk.send_price_in_dollars:
        if decision.side == "YES":
            payload["yes_price_dollars"] = _cents_to_dollar_str(int(decision.price_cents))
        else:
            payload["no_price_dollars"] = _cents_to_dollar_str(int(decision.price_cents))
    else:
        if decision.side == "YES":
            payload["yes_price"] = decision.price_cents
        else:
            payload["no_price"] = decision.price_cents

    if decision.action == "SELL":
        payload["reduce_only"] = True
    return payload


def _is_high_temp_series(series_ticker: str) -> bool:
    return "HIGHTEMP" in series_ticker.upper() or "HIGH-TEMP" in series_ticker.upper()


@app.command("bootstrap-cities")
def bootstrap_cities(
    overwrite: bool = typer.Option(False, "--overwrite", help="Overwrite output file if it exists."),
    out: str = typer.Option("configs/cities.yaml", "--out", help="Destination YAML file."),
    category: str = typer.Option("Climate", "--category", help="Kalshi series category filter."),
) -> None:
    cfg = _load_cfg()
    client = KalshiClient(cfg)
    try:
        series = client.list_series(tags=None, category=category)
    except Exception as exc:
        raise typer.Exit(f"bootstrap-cities failed: {exc}")
    mapping = build_city_mapping(series)
    yaml_text = dump_city_mapping_yaml(mapping)

    out_path = Path(out)
    if out_path.exists() and not overwrite:
        raise typer.Exit(f"{out_path} exists. Re-run with --overwrite.")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(yaml_text)

    DB(cfg.db_path).save_city_mapping_snapshot(yaml_text=yaml_text, source="bootstrap-cities")
    console.print(f"Wrote {len(mapping)} city mappings to {out_path}")


@app.command()
def init() -> None:
    """Interactive first-run setup."""
    env = typer.prompt("Environment (demo|production)", default="demo")
    api_key_id = typer.prompt("Kalshi API key id", default="")
    private_key_path = typer.prompt("Kalshi private key path", default="./secrets/kalshi.key")

    cfg = AppConfig(env=env, base_url=_choose_base(env), api_key_id=api_key_id, private_key_path=private_key_path)
    client = KalshiClient(cfg)

    balance_data = client.get_balance() if api_key_id else {"balance": 0}
    available = _available_dollars(balance_data)
    console.print(f"Available balance: ${available:.2f}")

    cap_input = typer.prompt("Enter max starting capital to allocate (e.g., 100 OR 20%)")
    if cap_input.strip().endswith("%"):
        cap_mode = "percent"
        cap_value = float(cap_input.strip().replace("%", ""))
    else:
        cap_mode = "dollars"
        cap_value = float(cap_input.strip())
    derived = compute_cap_dollars(available, cap_mode, cap_value)
    console.print(f"Computed capital cap: ${derived:.2f}")

    cfg.capital.cap_mode = cap_mode
    cfg.capital.cap_value = cap_value
    cfg.trading_enabled = False

    config_path = Path("./configs/config.yaml")
    save_yaml_config(config_path, cfg)
    DB(cfg.db_path).save_capital(cap_mode, cap_value, derived)
    console.print(f"Wrote config to {config_path}.")


def _scan_once(cfg: AppConfig) -> list[dict]:
    db = DB(cfg.db_path)
    client = KalshiClient(cfg)
    metar = MetarClient(cfg.data.aviationweather_base_url, cfg.user_agent, cfg.data.cache_ttl_seconds)
    nws = NWSClient(cfg.data.nws_base_url, cfg.user_agent, cfg.data.cache_ttl_seconds)

    cities = load_city_mapping(Path("./configs/cities.yaml"))
    if not cities:
        cities = load_city_mapping(Path("./configs/cities.example.yaml"))

    out = []
    for city_key, city in cities.items():
        if city.get("lat") is None or city.get("lon") is None or not city.get("tz"):
            continue
        if not city.get("icao_station"):
            continue

        series_tickers = city.get("kalshi_series_tickers") or []
        for series_ticker in series_tickers:
            if not _is_high_temp_series(series_ticker):
                continue
            markets = client.list_markets(series_ticker=series_ticker, limit=cfg.scan.limit_markets)
            for m in markets:
                parsed = parse_temperature_market(m)
                if not parsed:
                    continue
                db.insert_market_snapshot(m)
                now_utc = datetime.now(timezone.utc)
                close_ts = parsed.close_ts
                hours_to_close = (close_ts - now_utc).total_seconds() / 3600
                if hours_to_close < cfg.risk.min_hours_to_close or hours_to_close > cfg.risk.max_hours_to_close:
                    continue
                start_ts = climate_window_start(close_ts, city["tz"])
                metars = metar.fetch_metar(city["icao_station"])
                obs_max = max_observed_temp_f(metars, start_ts, now_utc)
                if obs_max is None:
                    continue
                periods = nws.hourly_forecast(float(city["lat"]), float(city["lon"]))
                fc_max = max_forecast_temp_f(periods, now_utc, close_ts) or obs_max
                lock = evaluate_lock(
                    parsed.bracket_low,
                    parsed.bracket_high,
                    obs_max,
                    fc_max,
                    cfg.risk.safety_bias_f,
                    cfg.risk.lock_yes_probability,
                    cfg.risk.lock_no_probability,
                )
                rec = {
                    "market_ticker": m.get("ticker"),
                    "city_key": city_key,
                    "observed_max": obs_max,
                    "forecast_max_remaining": fc_max,
                    "min_possible": lock.min_possible,
                    "max_possible": lock.max_possible,
                    "lock_status": lock.lock_status,
                    "p_yes": lock.p_yes,
                    "reason": "lock-eval",
                    "hours_to_close": hours_to_close,
                    "close_ts": close_ts.isoformat(),
                }
                db.insert_evaluation(rec)
                out.append(rec)
    return out


@app.command()
def scan() -> None:
    """Scan weather markets and report locked candidates."""
    cfg = _load_cfg()
    try:
        candidates = _scan_once(cfg)
    except Exception as exc:
        console.print(f"Scan failed gracefully: {exc}")
        return
    table = Table(title="Locked Trade Candidates")
    for col in ["ticker", "city", "lock", "p_yes", "obs_max", "fc_max"]:
        table.add_column(col)
    for c in candidates:
        table.add_row(
            c["market_ticker"] or "",
            c["city_key"] or "",
            c["lock_status"],
            f"{c['p_yes']:.2f}",
            f"{c['observed_max']:.1f}",
            f"{c['forecast_max_remaining']:.1f}",
        )
    console.print(table)


@app.command()
def run(
    enable_trading: bool = typer.Option(False, help="Actually submit orders"),
    interval_seconds: int = 300,
    cap: str | None = typer.Option(None, help="Temporary capital cap override (e.g. 150 or 20%)"),
) -> None:
    """Run main loop; defaults to dry-run."""
    cfg = _load_cfg()
    db = DB(cfg.db_path)
    client = KalshiClient(cfg)

    if enable_trading and cfg.env == "production":
        typed = typer.prompt("Type I_UNDERSTAND_THIS_WILL_TRADE_REAL_MONEY to continue")
        if typed.strip() != "I_UNDERSTAND_THIS_WILL_TRADE_REAL_MONEY":
            raise typer.Exit("Confirmation mismatch; aborting.")

    if cap:
        console.print(f"Using run-time capital cap override: {cap} (config file unchanged).")

    console.print("DRY-RUN mode" if not enable_trading else "TRADING ENABLED")
    while RUNNING:
        try:
            balance = client.get_balance() if cfg.api_key_id else {"balance": 0}
            available = _available_dollars(balance)
            cap_dollars = _parse_cap_override(cap, available, cfg)

            positions = client.get_positions() if cfg.api_key_id else []
            open_orders = client.list_orders(status="open") if cfg.api_key_id else []
            current_exposure = compute_positions_exposure(positions) + compute_open_orders_exposure(open_orders)

            candidates = _scan_once(cfg)

            if cfg.risk.strategy_mode == "MAX_CYCLES" and cfg.risk.enable_exit_sells:
                for position in positions:
                    ticker = position.get("ticker") or position.get("market_ticker")
                    if not ticker:
                        continue
                    candidate = next((c for c in candidates if c.get("market_ticker") == ticker), None)
                    if not candidate:
                        continue
                    if candidate["hours_to_close"] > cfg.risk.max_exit_hours_to_close:
                        continue
                    if (candidate["lock_status"] == "LOCKED_YES" and str(position.get("side", "")).upper() != "YES") or (
                        candidate["lock_status"] == "LOCKED_NO" and str(position.get("side", "")).upper() != "NO"
                    ):
                        continue
                    book = normalize_orderbook(client.get_orderbook(ticker))
                    exit_decision = select_exit_order(position, book, cfg.risk)
                    if not exit_decision.should_trade:
                        continue
                    cycle_key = f"EXIT-{datetime.now(timezone.utc).strftime('%Y%m%d')}"
                    exit_order = _order_payload(
                        cfg=cfg,
                        ticker=ticker,
                        decision=exit_decision,
                        count=int(position.get("contracts") or position.get("position") or 1),
                        tif=cfg.risk.taker_time_in_force,
                        post_only=False,
                        strategy_mode=cfg.risk.strategy_mode,
                        cycle_key=cycle_key,
                    )
                    if not enable_trading:
                        console.print(f"[DRY-RUN EXIT] {exit_order}")
                        db.insert_order(ticker, exit_order["client_order_id"], exit_order, {"dry_run": True}, "DRY_RUN")
                        continue
                    resp = client.place_order(exit_order)
                    console.print(resp)
                    db.insert_order(ticker, exit_order["client_order_id"], exit_order, resp, "SUBMITTED")

            if cfg.risk.strategy_mode == "MAX_CYCLES" and current_exposure > cap_dollars:
                console.print("MAX_CYCLES: skipping new entries because current exposure exceeds cap.")
                time.sleep(int(interval_seconds))
                continue

            for c in candidates:
                if c["lock_status"] == "UNLOCKED":
                    continue
                if cfg.risk.strategy_mode == "MAX_CYCLES" and c["hours_to_close"] > cfg.risk.max_exit_hours_to_close:
                    continue
                book = normalize_orderbook(client.get_orderbook(c["market_ticker"]))
                decision = select_order(c["lock_status"], c["p_yes"], book, cfg.risk)
                if not decision.should_trade:
                    continue

                target_side = decision.side
                max_allowed = int((c["p_yes"] - cfg.risk.edge_buffer) * 100) if target_side == "YES" else int(((1 - c["p_yes"]) - cfg.risk.edge_buffer) * 100)
                maker = maker_first_entry_price(target_side, book, max_allowed, cfg.risk)
                if maker.should_place and maker.price_cents is not None:
                    decision.price_cents = maker.price_cents

                order_notional = decision.price_cents / 100
                if not enforce_cap(current_exposure, order_notional, cap_dollars):
                    continue

                close_key = datetime.fromisoformat(c["close_ts"]).strftime("%Y%m%d")
                order = _order_payload(
                    cfg=cfg,
                    ticker=c["market_ticker"],
                    decision=decision,
                    count=1,
                    tif=cfg.risk.maker_time_in_force,
                    post_only=True,
                    strategy_mode=cfg.risk.strategy_mode,
                    cycle_key=f"ENTRY-{close_key}",
                )
                if not enable_trading:
                    console.print(f"[DRY-RUN] {order}")
                    db.insert_order(c["market_ticker"], order["client_order_id"], order, {"dry_run": True}, "DRY_RUN")
                    current_exposure += order_notional
                    continue
                resp = client.place_order(order)
                console.print(resp)
                db.insert_order(c["market_ticker"], order["client_order_id"], order, resp, "SUBMITTED")
                current_exposure += order_notional
        except APIError as exc:
            console.print(f"Run loop API error: {exc}")
        except Exception as exc:
            console.print(f"Run loop failed gracefully: {exc}")

        if not RUNNING:
            break
        time.sleep(int(interval_seconds))


@app.command()
def positions() -> None:
    cfg = _load_cfg()
    client = KalshiClient(cfg)
    balance = client.get_balance()
    console.print(balance)


@app.command()
def orders(status: str = "open") -> None:
    cfg = _load_cfg()
    client = KalshiClient(cfg)
    for o in client.list_orders(status=status):
        console.print(o)


@app.command("cancel-all")
def cancel_all(confirm: bool = typer.Option(False, "--confirm", help="Required confirmation switch")) -> None:
    if not confirm:
        raise typer.Exit("Use --confirm to cancel all open orders.")
    cfg = _load_cfg()
    client = KalshiClient(cfg)
    for o in client.list_orders(status="open"):
        oid = o.get("order_id") or o.get("id")
        if oid:
            console.print(client.cancel_order(oid))


if __name__ == "__main__":
    app()
