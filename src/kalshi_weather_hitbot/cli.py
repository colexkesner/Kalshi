from __future__ import annotations

import signal
import time
from datetime import datetime, timezone
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from kalshi_weather_hitbot.config import AppConfig, EnvSettings, load_yaml_config, save_yaml_config
from kalshi_weather_hitbot.data.city_mapping import load_city_mapping
from kalshi_weather_hitbot.data.metar import MetarClient, max_observed_temp_f
from kalshi_weather_hitbot.data.nws import NWSClient, max_forecast_temp_f
from kalshi_weather_hitbot.db import DB
from kalshi_weather_hitbot.kalshi.client import KalshiClient
from kalshi_weather_hitbot.kalshi.models import normalize_orderbook
from kalshi_weather_hitbot.strategy.execution import build_client_order_id, select_order
from kalshi_weather_hitbot.strategy.model import evaluate_lock
from kalshi_weather_hitbot.strategy.risk import compute_cap_dollars, enforce_cap
from kalshi_weather_hitbot.strategy.screener import climate_window_start, parse_temperature_market

app = typer.Typer(help="Kalshi weather hit-rate bot (safe by default)")
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
    return cfg


def _choose_base(env: str) -> str:
    return "https://api.elections.kalshi.com" if env == "production" else "https://demo-api.kalshi.co"


@app.command()
def init() -> None:
    """Interactive first-run setup."""
    env = typer.prompt("Environment", default="demo")
    api_key_id = typer.prompt("Kalshi API key id", default="")
    private_key_path = typer.prompt("Kalshi private key path", default="./secrets/kalshi.key")
    _ = typer.prompt("Optional OpenAI API key (press enter to skip)", default="", show_default=False)

    cfg = AppConfig(env=env, base_url=_choose_base(env), api_key_id=api_key_id, private_key_path=private_key_path)
    client = KalshiClient(cfg)

    balance_data = client.get_balance() if api_key_id else {"available_balance": 0}
    available = float(balance_data.get("available_balance_dollars") or balance_data.get("available_balance") or 0)
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
    console.print(f"Wrote config to {config_path}. Copy to ~/.kalshi_weather_hitbot/config.yaml if desired.")


def _scan_once(cfg: AppConfig, auth_required: bool = False) -> list[dict]:
    db = DB(cfg.db_path)
    client = KalshiClient(cfg)
    metar = MetarClient(cfg.data.aviationweather_base_url, cfg.user_agent, cfg.data.cache_ttl_seconds)
    nws = NWSClient(cfg.data.nws_base_url, cfg.user_agent, cfg.data.cache_ttl_seconds)

    cities = load_city_mapping(Path("./configs/cities.yaml"))
    if not cities:
        cities = load_city_mapping(Path("./configs/cities.example.yaml"))

    series = client.list_series(tags=cfg.scan.tags)
    out = []
    for s in series[: cfg.scan.limit_series]:
        for m in client.list_markets(s.get("ticker", ""), limit=cfg.scan.limit_markets):
            parsed = parse_temperature_market(m)
            if not parsed:
                continue
            city = cities.get(parsed.city_key or "")
            if not city:
                continue
            db.insert_market_snapshot(m)
            now_utc = datetime.now(timezone.utc)
            close_ts = parsed.close_ts
            hours_to_close = (close_ts - now_utc).total_seconds() / 3600
            if hours_to_close < cfg.risk.min_hours_to_close or hours_to_close > cfg.risk.max_hours_to_close:
                continue
            start_ts = climate_window_start(close_ts)
            metars = metar.fetch_metar(city["icao_station"]) 
            obs_max = max_observed_temp_f(metars, start_ts, now_utc)
            if obs_max is None:
                continue
            periods = nws.hourly_forecast(city["lat"], city["lon"])
            fc_max = max_forecast_temp_f(periods, now_utc, close_ts) or obs_max
            lock = evaluate_lock(parsed.bracket_low, parsed.bracket_high, obs_max, fc_max, cfg.risk.safety_bias_f, cfg.risk.lock_yes_probability, cfg.risk.lock_no_probability)
            rec = {
                "market_ticker": m.get("ticker"),
                "city_key": parsed.city_key,
                "observed_max": obs_max,
                "forecast_max_remaining": fc_max,
                "min_possible": lock.min_possible,
                "max_possible": lock.max_possible,
                "lock_status": lock.lock_status,
                "p_yes": lock.p_yes,
                "reason": "lock-eval",
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
def run(enable_trading: bool = typer.Option(False, help="Actually submit orders"), interval_seconds: int = 300) -> None:
    """Run main loop; defaults to dry-run."""
    cfg = _load_cfg()
    db = DB(cfg.db_path)
    client = KalshiClient(cfg)

    if enable_trading and cfg.env == "production":
        typed = typer.prompt("Type I_UNDERSTAND_THIS_WILL_TRADE_REAL_MONEY to continue")
        if typed.strip() != "I_UNDERSTAND_THIS_WILL_TRADE_REAL_MONEY":
            raise typer.Exit("Confirmation mismatch; aborting.")

    console.print("DRY-RUN mode" if not enable_trading else "TRADING ENABLED")
    while RUNNING:
        candidates = _scan_once(cfg)
        for c in candidates:
            if c["lock_status"] == "UNLOCKED":
                continue
            book = normalize_orderbook(client.get_orderbook(c["market_ticker"]))
            decision = select_order(c["lock_status"], c["p_yes"], book, cfg.risk)
            if not decision.should_trade:
                continue

            balance = client.get_balance() if cfg.api_key_id else {"available_balance": 0}
            available = float(balance.get("available_balance_dollars") or balance.get("available_balance") or 0)
            cap_dollars = compute_cap_dollars(available, cfg.capital.cap_mode, cfg.capital.cap_value)
            order_notional = decision.price_cents / 100
            if not enforce_cap(0, order_notional, cap_dollars):
                continue

            order = {
                "ticker": c["market_ticker"],
                "side": decision.side,
                "action": decision.action,
                "type": "limit",
                "price": decision.price_cents,
                "count": 1,
                "post_only": True,
                "client_order_id": build_client_order_id(c["market_ticker"]),
            }
            if not enable_trading:
                console.print(f"[DRY-RUN] {order}")
                db.insert_order(c["market_ticker"], order["client_order_id"], order, {"dry_run": True}, "DRY_RUN")
                continue
            resp = client.place_order(order)
            console.print(resp)
            db.insert_order(c["market_ticker"], order["client_order_id"], order, resp, "SUBMITTED")

        if not RUNNING:
            break
        time.sleep(interval_seconds)


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
