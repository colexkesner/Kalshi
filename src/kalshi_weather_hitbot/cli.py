from __future__ import annotations

import signal
import time
from datetime import datetime, timezone
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from kalshi_weather_hitbot.config import AppConfig, EnvSettings, load_yaml_config, save_yaml_config
from kalshi_weather_hitbot.data.city_bootstrap import build_city_mapping, dump_city_mapping_yaml, is_daily_high_temp_series
from kalshi_weather_hitbot.data.city_mapping import load_city_mapping
from kalshi_weather_hitbot.data.metar import MetarClient, max_observed_temp_f
from kalshi_weather_hitbot.data.nws import NWSClient, max_forecast_temp_f
from kalshi_weather_hitbot.db import DB
from kalshi_weather_hitbot.kalshi.client import APIError, KalshiClient
from kalshi_weather_hitbot.kalshi.models import normalize_orderbook
from kalshi_weather_hitbot.strategy.calibration import build_lock_calibration
from kalshi_weather_hitbot.strategy.execution import build_client_order_id_deterministic, select_exit_order, select_order
from kalshi_weather_hitbot.strategy.fees import kalshi_fee_cents
from kalshi_weather_hitbot.strategy.maker import maker_first_entry_price
from kalshi_weather_hitbot.strategy.model import evaluate_lock
from kalshi_weather_hitbot.strategy.order_maintenance import (
    build_amend_payload,
    order_age_seconds,
    parse_order_price_cents,
    should_amend,
)
from kalshi_weather_hitbot.strategy.risk import (
    check_entry_risk_limits,
    compute_cap_dollars,
    compute_open_orders_exposure,
    compute_positions_exposure,
    enforce_cap,
)
from kalshi_weather_hitbot.strategy.sizing import compute_contracts
from kalshi_weather_hitbot.strategy.screener import climate_window_start, parse_temperature_market

app = typer.Typer(
    help="Kalshi weather hit-rate bot. Environment via KALSHI_ENV=demo|production (demo default)."
)
console = Console()
RUNNING = True


def _signal_handler(_sig, _frame):
    global RUNNING
    RUNNING = False


try:
    signal.signal(signal.SIGINT, _signal_handler)
except ValueError:
    # Streamlit and some embedded runtimes import this module outside the main thread.
    pass


def _load_cfg() -> AppConfig:
    env = EnvSettings.load()
    cfg = load_yaml_config(Path(env.kalshi_config_path))
    yaml_env = cfg.env
    yaml_base_url = cfg.base_url
    yaml_db_path = cfg.db_path
    chosen_env = env.kalshi_env
    chosen_base = _choose_base(chosen_env)
    if env.kalshi_api_key_id:
        cfg.api_key_id = env.kalshi_api_key_id
    if env.kalshi_private_key_path:
        cfg.private_key_path = env.kalshi_private_key_path
    cfg.trading_enabled = env.kalshi_trading_enabled or cfg.trading_enabled
    if cfg.runtime.warn_on_env_mismatch and str(yaml_env) != str(chosen_env):
        console.print(
            f"[bold yellow]CONFIG WARNING[/bold yellow] YAML env={yaml_env!r} but runtime KALSHI_ENV={chosen_env!r}. "
            f"Using runtime env."
        )
    if cfg.runtime.warn_on_env_mismatch and str(yaml_base_url or "") != str(chosen_base):
        console.print(
            f"[bold yellow]CONFIG WARNING[/bold yellow] YAML base_url={yaml_base_url!r} does not match env-selected "
            f"base_url={chosen_base!r}."
        )
    if cfg.runtime.warn_on_db_path_mismatch and str(yaml_db_path or "") != str(env.kalshi_db_path):
        console.print(
            f"[bold yellow]CONFIG WARNING[/bold yellow] YAML db_path={yaml_db_path!r} but runtime KALSHI_DB_PATH="
            f"{env.kalshi_db_path!r}. Using runtime db_path."
        )
    cfg.db_path = env.kalshi_db_path
    cfg.env = chosen_env
    if not (cfg.runtime.allow_yaml_base_url and str(cfg.base_url or "").strip()):
        cfg.base_url = chosen_base
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
    return f"{(price_cents / 100.0):.4f}"


def _build_calibration_lookup_if_enabled(cfg: AppConfig):
    if not cfg.calibration.enabled:
        return None
    return build_lock_calibration(
        db_path=cfg.db_path,
        by_city=cfg.calibration.by_city,
        buckets_hours_to_close=list(cfg.calibration.buckets_hours_to_close),
        prior_alpha=cfg.calibration.prior_alpha,
        prior_beta=cfg.calibration.prior_beta,
        min_samples_per_bucket=cfg.calibration.min_samples_per_bucket,
    )


def _maybe_calibrated_p_yes(
    *,
    cfg: AppConfig,
    base_p_yes: float,
    city_key: str | None,
    hours_to_close: float,
    lock_status: str,
    calibration_lookup,
) -> float:
    if not cfg.calibration.enabled or calibration_lookup is None:
        return base_p_yes
    try:
        return float(calibration_lookup(city_key, hours_to_close, lock_status, base_p_yes))
    except Exception:
        return base_p_yes


def resolve_trading_enabled(cli_flag: bool, cfg_flag: bool) -> bool:
    return cli_flag or cfg_flag


def order_aligned_with_lock(order_side: str, lock_status: str | None) -> bool:
    side = str(order_side).lower()
    if lock_status == "LOCKED_YES":
        return side == "yes"
    if lock_status == "LOCKED_NO":
        return side == "no"
    return False


def _entry_fee_total_cents(cfg: AppConfig, price_cents: int, count: int) -> int:
    if not cfg.fees.enabled or not cfg.fees.assume_maker_fee or count <= 0:
        return 0
    return kalshi_fee_cents(price_cents=price_cents, contracts=count, fee_kind="maker")


def _entry_total_cost_cents(cfg: AppConfig, price_cents: int, count: int) -> int:
    return (price_cents * count) + _entry_fee_total_cents(cfg, price_cents, count)


def _entry_priority_key(entry: dict) -> tuple[float, int, float]:
    decision = entry["decision"]
    book = entry["book"]
    close_ts = entry["close_ts"]
    net_ev_cents = int(getattr(decision, "expected_net_ev_cents", 0) or 0)
    price_cents = int(getattr(decision, "price_cents", 0) or 0)
    fee_cents = int(getattr(decision, "expected_fee_cents", 0) or 0)
    total_cost_cents = max(1, price_cents + fee_cents)
    liquidity_size = int(book.yes_ask_size if getattr(decision, "side", None) == "YES" else book.no_ask_size)
    return (net_ev_cents / total_cost_cents, liquidity_size, -close_ts.timestamp())


def _set_order_price_field(order: dict, side: str, price_cents: int, send_price_in_dollars: bool) -> None:
    if send_price_in_dollars:
        if str(side).upper() == "YES":
            order.pop("yes_price", None)
            order["yes_price_dollars"] = _cents_to_dollar_str(int(price_cents))
        else:
            order.pop("no_price", None)
            order["no_price_dollars"] = _cents_to_dollar_str(int(price_cents))
    else:
        if str(side).upper() == "YES":
            order.pop("yes_price_dollars", None)
            order["yes_price"] = int(price_cents)
        else:
            order.pop("no_price_dollars", None)
            order["no_price"] = int(price_cents)


def _place_entry_order_with_post_only_cross_fallback(
    client: KalshiClient,
    order: dict,
    *,
    ticker: str,
    side: str,
    cfg: AppConfig,
) -> dict | None:
    try:
        return client.place_order(order)
    except APIError as exc:
        message = str(exc).lower()
        if "order_already_exists" in message:
            raise
        if (not cfg.risk.post_only_cross_retry_once) or ("post" not in message or "cross" not in message):
            raise
        book = normalize_orderbook(client.get_orderbook(ticker))
        current_implied_ask = book.best_yes_ask_cents if str(side).upper() == "YES" else book.best_no_ask_cents
        previous_price_cents = parse_order_price_cents(order) or 1
        if current_implied_ask is None:
            console.print(f"[ORDER SKIP] ticker={ticker} post-only cross retry missing orderbook ask")
            return None
        retry_price_cents = max(1, min(int(current_implied_ask) - 1, int(previous_price_cents) - 1))
        if retry_price_cents >= previous_price_cents:
            console.print(f"[ORDER SKIP] ticker={ticker} post-only cross retry could not improve price")
            return None
        retry_order = dict(order)
        _set_order_price_field(retry_order, side=side, price_cents=retry_price_cents, send_price_in_dollars=cfg.risk.send_price_in_dollars)
        console.print(
            f"[ORDER RETRY] ticker={ticker} post-only cross fallback repricing {previous_price_cents}->{retry_price_cents}"
        )
        try:
            return client.place_order(retry_order)
        except APIError as retry_exc:
            console.print(f"[ORDER SKIP] ticker={ticker} post-only cross retry failed: {retry_exc}")
            return None


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
    t = series_ticker.upper()
    # Kalshi uses multiple historical naming schemes (e.g. KXHIGHTEMP-CHI, KXHIGHDEN, HIGHNY).
    if "LOW" in t or "SNOW" in t or "RAIN" in t:
        return False
    return ("HIGHTEMP" in t) or ("HIGH-TEMP" in t) or ("HIGH" in t)


def _city_mapping_counts(cities: dict) -> tuple[int, int, int]:
    total = len(cities)
    usable = sum(
        1
        for city in cities.values()
        if city.get("icao_station") and city.get("lat") is not None and city.get("lon") is not None and city.get("tz")
    )
    return total, usable, total - usable


def _bootstrap_enrich_series_with_market_terms(client: KalshiClient, series_list: list[dict]) -> list[dict]:
    enriched: list[dict] = []
    status_attempts = ["open", "closed", "settled"]
    for series in series_list:
        item = dict(series)
        series_ticker = str(item.get("ticker") or item.get("series_ticker") or "")
        if not series_ticker:
            enriched.append(item)
            continue

        markets: list[dict] = []
        if hasattr(client, "list_markets"):
            for status in status_attempts:
                try:
                    markets = client.list_markets(series_ticker=series_ticker, status=status, limit=20)
                except Exception:
                    markets = []
                if markets:
                    break

        for market in markets:
            if not item.get("contract_terms_url") and market.get("contract_terms_url"):
                item["contract_terms_url"] = market.get("contract_terms_url")
            if not item.get("contract_terms_text"):
                rules_text = " ".join(
                    str(market.get(k, ""))
                    for k in ["rules_primary", "rules", "title", "subtitle", "yes_sub_title", "no_sub_title"]
                    if market.get(k) is not None
                ).strip()
                if rules_text:
                    item["contract_terms_text"] = rules_text
            if item.get("contract_terms_url") or item.get("contract_terms_text"):
                break

        enriched.append(item)
    return enriched


@app.command("bootstrap-cities")
def bootstrap_cities(
    overwrite: bool = typer.Option(False, "--overwrite", help="Overwrite output file if it exists."),
    out: str = typer.Option("configs/cities.yaml", "--out", help="Destination YAML file."),
    category: str = typer.Option("Climate", "--category", help="Kalshi series category filter."),
    tags: str = typer.Option("Weather", "--tags", help="Kalshi series tags filter. Use empty string to fetch all tags."),
) -> None:
    cfg = _load_cfg()
    client = KalshiClient(cfg)
    tags_value = tags if isinstance(tags, str) else "Weather"
    tags_filter = tags_value.strip() or None
    query_attempts: list[tuple[str | None, str | None]] = []
    used_query: tuple[str | None, str | None] | None = None
    try:
        def _fetch_series(fetch_tags: str | None, fetch_category: str | None):
            query_attempts.append((fetch_tags, fetch_category))
            return client.list_series(tags=fetch_tags, category=fetch_category)

        series = _fetch_series(tags_filter, category)
        if series:
            used_query = (tags_filter, category)
        if not series and tags_filter is not None:
            series = _fetch_series(None, category)
            if series:
                used_query = (None, category)
        if not series and category:
            series = _fetch_series(tags_filter, None)
            if series:
                used_query = (tags_filter, None)
        if not series and category and tags_filter is not None:
            series = _fetch_series(None, None)
            if series:
                used_query = (None, None)
    except APIError as exc:
        typer.secho(f"bootstrap-cities failed: {exc}", err=True, fg=typer.colors.RED)
        raise typer.Exit(code=1)
    except Exception as exc:
        typer.secho(f"bootstrap-cities failed: {exc}", err=True, fg=typer.colors.RED)
        raise typer.Exit(code=1)
    total_series_seen = len(series)
    high_temp_series = [s for s in series if is_daily_high_temp_series(s)]
    high_temp_series = _bootstrap_enrich_series_with_market_terms(client, high_temp_series)
    mapping, needs_manual_override = build_city_mapping(
        high_temp_series,
        station_cache_url=cfg.data.awc_station_cache_url,
        station_cache_path=cfg.data.awc_station_cache_path,
        cache_ttl_seconds=cfg.data.cache_ttl_seconds,
        nws_base_url=cfg.data.nws_base_url,
    )
    yaml_text = dump_city_mapping_yaml(mapping)

    out_path = Path(out)
    if out_path.exists() and not overwrite:
        raise typer.Exit(f"{out_path} exists. Re-run with --overwrite.")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(yaml_text)

    DB(cfg.db_path).save_city_mapping_snapshot(yaml_text=yaml_text, source="bootstrap-cities")
    resolved_count = sum(1 for c in mapping.values() if c.get("icao_station") and c.get("lat") is not None and c.get("lon") is not None and c.get("tz"))
    unresolved_station_names = sorted(
        {
            str(c.get("resolution_location_name") or city_key)
            for city_key, c in mapping.items()
            if c.get("needs_manual_override")
        }
    )
    if used_query is None and query_attempts:
        used_query = query_attempts[-1]
    console.print(
        "Series query used: "
        f"category={repr(used_query[1]) if used_query else 'None'} "
        f"tags={repr(used_query[0]) if used_query else 'None'} "
        f"(attempts={len(query_attempts)})"
    )
    console.print(f"Series seen: {total_series_seen}")
    console.print(f"High-temp series used: {len(high_temp_series)}")
    if total_series_seen and not high_temp_series:
        sample = [
            f"{str(s.get('ticker') or s.get('series_ticker') or '<no-ticker>')} | {str(s.get('title') or s.get('name') or '')}"
            for s in series[:5]
        ]
        console.print("High-temp filter matched 0 series. Sample series:")
        for line in sample:
            console.print(f"  - {line}")
    console.print(f"Wrote {len(mapping)} city mappings to {out_path}")
    console.print(f"Resolved stations: {resolved_count}")
    console.print(f"Unresolved stations: {len(mapping) - resolved_count}")
    if needs_manual_override:
        console.print("Needs manual override: " + ", ".join(sorted(needs_manual_override)))
    if unresolved_station_names:
        console.print("Unresolved station names: " + ", ".join(unresolved_station_names))


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


def _scan_once(
    cfg: AppConfig,
    calibration_lookup=None,
    client: KalshiClient | None = None,
    metar: MetarClient | None = None,
    nws: NWSClient | None = None,
) -> list[dict]:
    db = DB(cfg.db_path)
    client = client or KalshiClient(cfg)
    metar = metar or MetarClient(
        cfg.data.aviationweather_base_url,
        cfg.user_agent,
        cfg.data.cache_ttl_seconds,
        cfg.data.metar_timeout_seconds,
        cfg.data.metar_station_cooldown_seconds,
    )
    nws = nws or NWSClient(cfg.data.nws_base_url, cfg.user_agent, cfg.data.cache_ttl_seconds, cfg.data.nws_timeout_seconds)

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
                primary_station = str(city["icao_station"])
                station_fallbacks = city.get("icao_station_fallbacks") or []
                if not isinstance(station_fallbacks, list):
                    station_fallbacks = []
                stations = [primary_station] + [str(s) for s in station_fallbacks if s][: cfg.data.metar_max_fallbacks]
                metars, used_station, metar_status = metar.fetch_metar_with_fallbacks(stations)
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
                    cfg.risk.station_uncertainty_f,
                )
                rec = {
                    "market_ticker": m.get("ticker"),
                    "city_key": city_key,
                    "observed_max": obs_max,
                    "forecast_max_remaining": fc_max,
                    "min_possible": lock.min_possible,
                    "max_possible": lock.max_possible,
                    "lock_status": lock.lock_status,
                    "p_yes": _maybe_calibrated_p_yes(
                        cfg=cfg,
                        base_p_yes=float(lock.p_yes),
                        city_key=str(city_key),
                        hours_to_close=float(hours_to_close),
                        lock_status=str(lock.lock_status),
                        calibration_lookup=calibration_lookup,
                    ),
                    "reason": "lock-eval",
                    "metar_station_primary": primary_station,
                    "metar_station_used": used_station,
                    "metar_status": metar_status,
                    "metar_station_candidates_count": len(stations),
                    "metar_station_list": stations,
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
    cities = load_city_mapping(Path("./configs/cities.yaml"))
    if not cities:
        cities = load_city_mapping(Path("./configs/cities.example.yaml"))
    total_cities, usable_cities, skipped_cities = _city_mapping_counts(cities)
    console.print(f"Cities loaded: total={total_cities} usable={usable_cities} skipped={skipped_cities}")
    try:
        candidates = _scan_once(cfg, calibration_lookup=_build_calibration_lookup_if_enabled(cfg))
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
def sync_settlements(
    max_pages: int = typer.Option(5, "--max-pages", min=1),
    limit: int = typer.Option(200, "--limit", min=1, max=500),
) -> None:
    """Fetch portfolio settlements and persist to SQLite."""
    cfg = _load_cfg()
    client = KalshiClient(cfg)
    db = DB(cfg.db_path)
    cursor: str | None = None
    pages = 0
    rows_inserted = 0
    while pages < max_pages:
        payload = client.get_settlements(limit=limit, cursor=cursor)
        settlements = payload.get("settlements") or []
        for settlement in settlements:
            if isinstance(settlement, dict):
                db.insert_settlement(settlement)
                rows_inserted += 1
        pages += 1
        next_cursor = payload.get("cursor")
        cursor = str(next_cursor) if next_cursor else None
        if not cursor:
            break
    console.print(f"Settlements sync complete: pages={pages} rows_inserted={rows_inserted} next_cursor={cursor or ''}")


@app.command()
def run(
    enable_trading: bool = typer.Option(False, help="Actually submit orders"),
    interval_seconds: int = 300,
    cap: str | None = typer.Option(None, help="Temporary capital cap override (e.g. 150 or 20%)"),
) -> None:
    """Run main loop; defaults to dry-run."""
    cfg = _load_cfg()
    effective_trading = resolve_trading_enabled(enable_trading, cfg.trading_enabled)
    db = DB(cfg.db_path)
    client = KalshiClient(cfg)
    metar = MetarClient(
        cfg.data.aviationweather_base_url,
        cfg.user_agent,
        cfg.data.cache_ttl_seconds,
        cfg.data.metar_timeout_seconds,
        cfg.data.metar_station_cooldown_seconds,
    )
    nws = NWSClient(cfg.data.nws_base_url, cfg.user_agent, cfg.data.cache_ttl_seconds, cfg.data.nws_timeout_seconds)

    if effective_trading and cfg.env == "production":
        typed = typer.prompt("Type I_UNDERSTAND_THIS_WILL_TRADE_REAL_MONEY to continue")
        if typed.strip() != "I_UNDERSTAND_THIS_WILL_TRADE_REAL_MONEY":
            raise typer.Exit("Confirmation mismatch; aborting.")

    if cap:
        console.print(f"Using run-time capital cap override: {cap} (config file unchanged).")

    cities = load_city_mapping(Path("./configs/cities.yaml"))
    if not cities:
        cities = load_city_mapping(Path("./configs/cities.example.yaml"))
    total_cities, usable_cities, skipped_cities = _city_mapping_counts(cities)
    console.print(f"Cities loaded: total={total_cities} usable={usable_cities} skipped={skipped_cities}")
    console.print("DRY-RUN mode" if not effective_trading else "TRADING ENABLED")
    session_start_available_cash: float | None = None
    calibration_lookup = _build_calibration_lookup_if_enabled(cfg)
    while RUNNING:
        try:
            cycle_counts: dict[str, int] = {
                "entry_unlocked": 0,
                "entry_outside_exit_window": 0,
                "orderbook_missing": 0,
                "spread_too_wide": 0,
                "liquidity_too_low": 0,
                "edge_failed": 0,
                "risk_positions_limit_failed": 0,
                "risk_orders_per_market_failed": 0,
                "risk_per_market_notional_failed": 0,
                "cap_failed": 0,
                "cash_failed": 0,
                "entry_submitted": 0,
                "entry_dry_run": 0,
                "stale_orders_canceled": 0,
                "stale_orders_cancel_failed": 0,
                "aged_orders_canceled": 0,
                "aged_orders_cancel_failed": 0,
                "orders_amended": 0,
                "orders_amend_failed": 0,
                "exit_considered": 0,
                "exit_not_eligible": 0,
                "exit_decision_blocked": 0,
                "exit_submitted": 0,
                "exit_dry_run": 0,
                "duplicate_order_skipped": 0,
                "ticker_side_guard_skipped": 0,
            }
            blocked_examples: dict[str, list[str]] = {
                "orderbook_missing": [],
                "edge_failed": [],
                "spread_too_wide": [],
                "liquidity_too_low": [],
            }
            balance = client.get_balance() if cfg.api_key_id else {"balance": 0}
            available = _available_dollars(balance)
            available_cash_dollars = available
            cap_dollars = _parse_cap_override(cap, available, cfg)

            positions = client.get_positions() if cfg.api_key_id else []
            open_orders = client.list_orders(status="open") if cfg.api_key_id else []
            resting_orders: list[dict] = []
            if cfg.api_key_id:
                try:
                    resting_orders = client.list_orders(status="resting")
                except APIError:
                    resting_orders = []
            active_orders_by_id: dict[str, dict] = {}
            for order in [*open_orders, *resting_orders]:
                oid = str(order.get("order_id") or order.get("id") or "")
                if oid:
                    active_orders_by_id[oid] = order
                else:
                    # Fallback key if order id is absent
                    fallback_key = str(order.get("client_order_id") or f"noid-{len(active_orders_by_id)}")
                    active_orders_by_id[fallback_key] = order
            active_orders = list(active_orders_by_id.values())
            existing_client_order_ids = {
                str(o.get("client_order_id") or "")
                for o in active_orders
                if o.get("client_order_id")
            }
            active_entry_orders_by_ticker_side = {
                (
                    str(o.get("ticker") or o.get("market_ticker") or ""),
                    str(o.get("side") or "").lower(),
                )
                for o in active_orders
                if str(o.get("action") or "").lower() == "buy"
            }
            current_exposure = compute_positions_exposure(positions) + compute_open_orders_exposure(active_orders)
            if session_start_available_cash is None:
                # Reconstruct a practical baseline so restarts with existing active orders
                # do not reset reserved-cap tracking to zero.
                session_start_available_cash = available_cash_dollars + current_exposure
            session_reserved_cash = max(0.0, (session_start_available_cash or 0.0) - available_cash_dollars)
            effective_exposure_for_cap = max(current_exposure, session_reserved_cash)
            cash_floor_dollars = max(0.0, (session_start_available_cash or 0.0) - cap_dollars)

            candidates = _scan_once(cfg, calibration_lookup=calibration_lookup, client=client, metar=metar, nws=nws)
            lock_by_ticker = {
                str(c.get("market_ticker")): str(c.get("lock_status") or "UNLOCKED")
                for c in candidates
                if c.get("market_ticker")
            }
            candidate_by_ticker = {
                str(c.get("market_ticker")): c
                for c in candidates
                if c.get("market_ticker")
            }
            cycle_orderbooks: dict[str, Any] = {}
            locked_yes = sum(1 for c in candidates if c.get("lock_status") == "LOCKED_YES")
            locked_no = sum(1 for c in candidates if c.get("lock_status") == "LOCKED_NO")
            console.print(
                "Cycle summary: "
                f"candidates={len(candidates)} "
                f"locked_yes={locked_yes} "
                f"locked_no={locked_no} "
                f"positions={len(positions)} "
                f"open_orders={len(active_orders)} "
                f"cash=${available_cash_dollars:.2f} "
                f"exposure=${current_exposure:.2f} "
                f"reserved=${session_reserved_cash:.2f} "
                f"cash_floor=${cash_floor_dollars:.2f} "
                f"cap=${cap_dollars:.2f}"
            )

            remaining_active_orders: list[dict] = []
            for order in active_orders:
                action = str(order.get("action") or "").lower()
                ticker = str(order.get("ticker") or order.get("market_ticker") or "")
                side = str(order.get("side") or "").lower()
                oid = str(order.get("order_id") or order.get("id") or "")
                if action != "buy" or not ticker or not side or not oid:
                    remaining_active_orders.append(order)
                    continue
                lock_status = lock_by_ticker.get(ticker)
                if order_aligned_with_lock(side, lock_status):
                    remaining_active_orders.append(order)
                    continue

                reason = f"Stale buy order: side={side} lock_status={lock_status or 'MISSING'}"
                request_json = {"order_id": oid, "ticker": ticker, "reason": reason}
                client_order_id = str(order.get("client_order_id") or f"cancel-{oid}")
                ticker_side_key = (ticker, side)
                if not effective_trading:
                    console.print(f"[DRY-RUN CANCEL] {request_json}")
                    db.insert_order(ticker, client_order_id, request_json, {"dry_run": True}, "CANCEL_DRY_RUN")
                    cycle_counts["stale_orders_canceled"] += 1
                    existing_client_order_ids.discard(client_order_id)
                    active_entry_orders_by_ticker_side.discard(ticker_side_key)
                    continue
                try:
                    cancel_resp = client.cancel_order(oid)
                    console.print(cancel_resp)
                    db.insert_order(ticker, client_order_id, request_json, cancel_resp, "CANCEL_SUBMITTED")
                    cycle_counts["stale_orders_canceled"] += 1
                    existing_client_order_ids.discard(client_order_id)
                    active_entry_orders_by_ticker_side.discard(ticker_side_key)
                except APIError as exc:
                    console.print(f"[CANCEL ERROR] ticker={ticker} order_id={oid} error={exc}")
                    cycle_counts["stale_orders_cancel_failed"] += 1
                    remaining_active_orders.append(order)
            active_orders = remaining_active_orders

            amend_attempts_this_cycle = 0
            if cfg.risk.order_maintenance_enabled or cfg.risk.cancel_unfilled_after_minutes is not None:
                now_utc = datetime.now(timezone.utc)
                for order in active_orders:
                    if str(order.get("action") or "").lower() != "buy":
                        continue
                    ticker = str(order.get("ticker") or order.get("market_ticker") or "")
                    side = str(order.get("side") or "").lower()
                    oid = str(order.get("order_id") or order.get("id") or "")
                    if not ticker or side not in {"yes", "no"} or not oid:
                        continue
                    lock_status = lock_by_ticker.get(ticker)
                    if not order_aligned_with_lock(side, lock_status):
                        continue

                    age_seconds = order_age_seconds(order, now_utc)
                    if cfg.risk.cancel_unfilled_after_minutes is not None and age_seconds >= (cfg.risk.cancel_unfilled_after_minutes * 60):
                        request_json = {"order_id": oid, "ticker": ticker, "reason": f"Age exceeded {cfg.risk.cancel_unfilled_after_minutes}m"}
                        client_order_id = str(order.get("client_order_id") or f"cancel-{oid}")
                        ticker_side_key = (ticker, side)
                        if not effective_trading:
                            console.print(f"[DRY-RUN CANCEL AGE] {request_json}")
                            db.insert_order(ticker, client_order_id, request_json, {"dry_run": True}, "CANCEL_AGE_DRY_RUN")
                            cycle_counts["aged_orders_canceled"] += 1
                            existing_client_order_ids.discard(client_order_id)
                            active_entry_orders_by_ticker_side.discard(ticker_side_key)
                            continue
                        try:
                            cancel_resp = client.cancel_order(oid)
                            console.print(cancel_resp)
                            db.insert_order(ticker, client_order_id, request_json, cancel_resp, "CANCEL_AGE_SUBMITTED")
                            cycle_counts["aged_orders_canceled"] += 1
                            existing_client_order_ids.discard(client_order_id)
                            active_entry_orders_by_ticker_side.discard(ticker_side_key)
                            continue
                        except APIError as exc:
                            console.print(f"[CANCEL AGE ERROR] ticker={ticker} order_id={oid} error={exc}")
                            cycle_counts["aged_orders_cancel_failed"] += 1
                            continue

                    if not cfg.risk.order_maintenance_enabled:
                        continue
                    if amend_attempts_this_cycle >= cfg.risk.amend_max_per_cycle:
                        break
                    c = candidate_by_ticker.get(ticker)
                    if not c:
                        continue
                    if ticker not in cycle_orderbooks:
                        cycle_orderbooks[ticker] = normalize_orderbook(client.get_orderbook(ticker))
                    book = cycle_orderbooks[ticker]
                    target_side = "YES" if side == "yes" else "NO"
                    max_allowed = int((c["p_yes"] - cfg.risk.edge_buffer) * 100) if target_side == "YES" else int(((1 - c["p_yes"]) - cfg.risk.edge_buffer) * 100)
                    maker = maker_first_entry_price(target_side, book, max_allowed, cfg.risk)
                    if not maker.should_place or maker.price_cents is None:
                        continue
                    existing_price = parse_order_price_cents(order)
                    if existing_price is None:
                        continue
                    if not should_amend(existing_price, int(maker.price_cents), age_seconds, cfg.risk):
                        continue
                    amend_count = int(order.get("remaining_count") or order.get("count") or 1)
                    amend_payload = build_amend_payload(
                        order_id=oid,
                        ticker=ticker,
                        side=target_side,
                        action=str(order.get("action") or "buy"),
                        desired_price_cents=int(maker.price_cents),
                        count=max(1, amend_count),
                        cfg_price_in_dollars_flag=cfg.risk.send_price_in_dollars,
                    )
                    if not effective_trading:
                        console.print(f"[DRY-RUN AMEND] {amend_payload}")
                        db.insert_order(ticker, str(order.get("client_order_id") or f"amend-{oid}"), amend_payload, {"dry_run": True}, "AMEND_DRY_RUN")
                        cycle_counts["orders_amended"] += 1
                        amend_attempts_this_cycle += 1
                        continue
                    try:
                        amend_resp = client.amend_order(oid, amend_payload)
                        console.print(amend_resp)
                        db.insert_order(ticker, str(order.get("client_order_id") or f"amend-{oid}"), amend_payload, amend_resp, "AMENDED")
                        cycle_counts["orders_amended"] += 1
                        amend_attempts_this_cycle += 1
                    except APIError as exc:
                        console.print(f"[AMEND ERROR] ticker={ticker} order_id={oid} error={exc}")
                        cycle_counts["orders_amend_failed"] += 1

            if cfg.risk.strategy_mode == "MAX_CYCLES" and cfg.risk.enable_exit_sells:
                for position in positions:
                    ticker = position.get("ticker") or position.get("market_ticker")
                    if not ticker:
                        cycle_counts["exit_not_eligible"] += 1
                        continue
                    cycle_counts["exit_considered"] += 1
                    candidate = next((c for c in candidates if c.get("market_ticker") == ticker), None)
                    if not candidate:
                        cycle_counts["exit_not_eligible"] += 1
                        continue
                    if candidate["hours_to_close"] > cfg.risk.max_exit_hours_to_close:
                        cycle_counts["exit_not_eligible"] += 1
                        continue
                    if (candidate["lock_status"] == "LOCKED_YES" and str(position.get("side", "")).upper() != "YES") or (
                        candidate["lock_status"] == "LOCKED_NO" and str(position.get("side", "")).upper() != "NO"
                    ):
                        cycle_counts["exit_not_eligible"] += 1
                        continue
                    book = normalize_orderbook(client.get_orderbook(ticker))
                    exit_decision = select_exit_order(position, book, cfg.risk, cfg.fees)
                    if not exit_decision.should_trade:
                        cycle_counts["exit_decision_blocked"] += 1
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
                    if not effective_trading:
                        console.print(f"[DRY-RUN EXIT] {exit_order}")
                        db.insert_order(ticker, exit_order["client_order_id"], exit_order, {"dry_run": True}, "DRY_RUN")
                        cycle_counts["exit_dry_run"] += 1
                        continue
                    if exit_order["client_order_id"] in existing_client_order_ids:
                        cycle_counts["duplicate_order_skipped"] += 1
                        continue
                    resp = client.place_order(exit_order)
                    console.print(resp)
                    db.insert_order(ticker, exit_order["client_order_id"], exit_order, resp, "SUBMITTED")
                    existing_client_order_ids.add(str(exit_order["client_order_id"]))
                    cycle_counts["exit_submitted"] += 1

            if cfg.risk.strategy_mode == "MAX_CYCLES" and (
                effective_exposure_for_cap > cap_dollars or available_cash_dollars < cash_floor_dollars
            ):
                console.print("MAX_CYCLES: skipping new entries because current exposure exceeds cap.")
                console.print(
                    "Cycle gates: "
                    f"entry_unlocked={cycle_counts['entry_unlocked']} "
                    f"entry_outside_exit_window={cycle_counts['entry_outside_exit_window']} "
                    f"orderbook_missing={cycle_counts['orderbook_missing']} "
                    f"spread_too_wide={cycle_counts['spread_too_wide']} "
                        f"liquidity_too_low={cycle_counts['liquidity_too_low']} "
                        f"edge_failed={cycle_counts['edge_failed']} "
                        f"risk_positions_limit_failed={cycle_counts['risk_positions_limit_failed']} "
                        f"risk_orders_per_market_failed={cycle_counts['risk_orders_per_market_failed']} "
                        f"risk_per_market_notional_failed={cycle_counts['risk_per_market_notional_failed']} "
                        f"cap_failed={cycle_counts['cap_failed']} "
                        f"cash_failed={cycle_counts['cash_failed']} "
                        f"stale_orders_canceled={cycle_counts['stale_orders_canceled']} "
                        f"stale_orders_cancel_failed={cycle_counts['stale_orders_cancel_failed']} "
                        f"aged_orders_canceled={cycle_counts['aged_orders_canceled']} "
                        f"aged_orders_cancel_failed={cycle_counts['aged_orders_cancel_failed']} "
                        f"orders_amended={cycle_counts['orders_amended']} "
                        f"orders_amend_failed={cycle_counts['orders_amend_failed']} "
                        f"entry_dry_run={cycle_counts['entry_dry_run']} "
                        f"entry_submitted={cycle_counts['entry_submitted']} "
                    f"duplicate_order_skipped={cycle_counts['duplicate_order_skipped']} "
                    f"ticker_side_guard_skipped={cycle_counts['ticker_side_guard_skipped']} "
                    f"exit_considered={cycle_counts['exit_considered']} "
                    f"exit_not_eligible={cycle_counts['exit_not_eligible']} "
                    f"exit_blocked={cycle_counts['exit_decision_blocked']} "
                    f"exit_dry_run={cycle_counts['exit_dry_run']} "
                    f"exit_submitted={cycle_counts['exit_submitted']}"
                )
                time.sleep(int(interval_seconds))
                continue

            entry_opportunities: list[dict] = []
            for c in candidates:
                if c["lock_status"] == "UNLOCKED":
                    cycle_counts["entry_unlocked"] += 1
                    continue
                if cfg.risk.strategy_mode == "MAX_CYCLES" and c["hours_to_close"] > cfg.risk.max_exit_hours_to_close:
                    cycle_counts["entry_outside_exit_window"] += 1
                    continue
                ticker_key = str(c["market_ticker"])
                if ticker_key not in cycle_orderbooks:
                    cycle_orderbooks[ticker_key] = normalize_orderbook(client.get_orderbook(ticker_key))
                book = cycle_orderbooks[ticker_key]
                decision = select_order(c["lock_status"], c["p_yes"], book, cfg.risk, fees_cfg=cfg.fees)
                if not decision.should_trade:
                    if decision.reason == "Missing orderbook prices":
                        cycle_counts["orderbook_missing"] += 1
                        if len(blocked_examples["orderbook_missing"]) < 5:
                            blocked_examples["orderbook_missing"].append(str(c["market_ticker"]))
                    elif decision.reason == "Spread too wide":
                        cycle_counts["spread_too_wide"] += 1
                        if len(blocked_examples["spread_too_wide"]) < 5:
                            blocked_examples["spread_too_wide"].append(str(c["market_ticker"]))
                    elif decision.reason == "Insufficient liquidity":
                        cycle_counts["liquidity_too_low"] += 1
                        if len(blocked_examples["liquidity_too_low"]) < 5:
                            blocked_examples["liquidity_too_low"].append(str(c["market_ticker"]))
                    elif decision.reason in {"Price above edge-adjusted threshold", "Net edge below threshold"}:
                        cycle_counts["edge_failed"] += 1
                        if len(blocked_examples["edge_failed"]) < 5:
                            blocked_examples["edge_failed"].append(str(c["market_ticker"]))
                    continue

                target_side = decision.side
                max_allowed = int((c["p_yes"] - cfg.risk.edge_buffer) * 100) if target_side == "YES" else int(((1 - c["p_yes"]) - cfg.risk.edge_buffer) * 100)
                maker = maker_first_entry_price(target_side, book, max_allowed, cfg.risk)
                if maker.should_place and maker.price_cents is not None:
                    decision.price_cents = maker.price_cents
                    confidence = c["p_yes"] if target_side == "YES" else (1 - c["p_yes"])
                    decision.expected_fee_cents = _entry_fee_total_cents(cfg, int(decision.price_cents), 1)
                    decision.expected_net_ev_cents = int(round(confidence * 100)) - int(decision.price_cents) - int(decision.expected_fee_cents or 0)

                entry_opportunities.append(
                    {
                        "candidate": c,
                        "decision": decision,
                        "book": book,
                        "close_ts": datetime.fromisoformat(c["close_ts"]),
                    }
                )

            for entry in sorted(entry_opportunities, key=_entry_priority_key, reverse=True):
                c = entry["candidate"]
                decision = entry["decision"]
                bankroll_for_sizing = min(available_cash_dollars, cap_dollars)
                if cfg.risk.strategy_mode == "MAX_CYCLES":
                    bankroll_for_sizing = min(bankroll_for_sizing, max(0.0, cap_dollars - effective_exposure_for_cap))
                side_prob = c["p_yes"] if decision.side == "YES" else (1 - c["p_yes"])
                count = compute_contracts(
                    bankroll_dollars=bankroll_for_sizing,
                    price_cents=int(decision.price_cents),
                    p=float(side_prob),
                    cfg_sizing=cfg.sizing,
                    risk=cfg.risk,
                )
                if count <= 0:
                    continue

                order_notional = (int(decision.price_cents) * count) / 100.0
                total_order_cost_dollars = _entry_total_cost_cents(cfg, int(decision.price_cents), count) / 100.0
                risk_ok, risk_reason = check_entry_risk_limits(
                    ticker=str(c["market_ticker"]),
                    new_order_notional=order_notional,
                    positions=positions,
                    active_orders=active_orders,
                    risk=cfg.risk,
                )
                if not risk_ok:
                    if risk_reason == "Max open positions reached":
                        cycle_counts["risk_positions_limit_failed"] += 1
                    elif risk_reason == "Max orders per market reached":
                        cycle_counts["risk_orders_per_market_failed"] += 1
                    elif risk_reason == "Max per-market notional exceeded":
                        cycle_counts["risk_per_market_notional_failed"] += 1
                    continue
                if not enforce_cap(effective_exposure_for_cap, order_notional, cap_dollars):
                    cycle_counts["cap_failed"] += 1
                    continue
                if (available_cash_dollars - total_order_cost_dollars) < cash_floor_dollars:
                    cycle_counts["cap_failed"] += 1
                    continue
                if available_cash_dollars < total_order_cost_dollars:
                    cycle_counts["cash_failed"] += 1
                    continue

                close_key = datetime.fromisoformat(c["close_ts"]).strftime("%Y%m%d")
                order = _order_payload(
                    cfg=cfg,
                    ticker=c["market_ticker"],
                    decision=decision,
                    count=count,
                    tif=cfg.risk.maker_time_in_force,
                    post_only=True,
                    strategy_mode=cfg.risk.strategy_mode,
                    cycle_key=f"ENTRY-{close_key}",
                )
                if not effective_trading:
                    console.print(f"[DRY-RUN] {order}")
                    db.insert_order(c["market_ticker"], order["client_order_id"], order, {"dry_run": True}, "DRY_RUN")
                    current_exposure += order_notional
                    effective_exposure_for_cap += order_notional
                    available_cash_dollars = max(0.0, available_cash_dollars - total_order_cost_dollars)
                    cycle_counts["entry_dry_run"] += 1
                    continue
                ticker_side_key = (str(order.get("ticker") or ""), str(order.get("side") or "").lower())
                if ticker_side_key in active_entry_orders_by_ticker_side:
                    cycle_counts["ticker_side_guard_skipped"] += 1
                    continue
                if order["client_order_id"] in existing_client_order_ids:
                    cycle_counts["duplicate_order_skipped"] += 1
                    continue
                try:
                    resp = _place_entry_order_with_post_only_cross_fallback(
                        client,
                        order,
                        ticker=str(c["market_ticker"]),
                        side=str(decision.side),
                        cfg=cfg,
                    )
                    if resp is None:
                        continue
                except APIError as exc:
                    if "order_already_exists" in str(exc):
                        cycle_counts["duplicate_order_skipped"] += 1
                        existing_client_order_ids.add(str(order["client_order_id"]))
                        active_entry_orders_by_ticker_side.add(ticker_side_key)
                        continue
                    console.print(f"[ORDER ERROR] ticker={c['market_ticker']} payload={order}")
                    raise
                console.print(resp)
                db.insert_order(c["market_ticker"], order["client_order_id"], order, resp, "SUBMITTED")
                current_exposure += order_notional
                effective_exposure_for_cap += order_notional
                available_cash_dollars = max(0.0, available_cash_dollars - total_order_cost_dollars)
                existing_client_order_ids.add(str(order["client_order_id"]))
                active_entry_orders_by_ticker_side.add(ticker_side_key)
                active_orders.append(
                    {
                        "ticker": c["market_ticker"],
                        "action": "buy",
                        "side": str(order.get("side") or ""),
                        "count": count,
                        "buy_max_cost_dollars": order_notional,
                    }
                )
                cycle_counts["entry_submitted"] += 1
            console.print(
                "Cycle gates: "
                f"entry_unlocked={cycle_counts['entry_unlocked']} "
                f"entry_outside_exit_window={cycle_counts['entry_outside_exit_window']} "
                f"orderbook_missing={cycle_counts['orderbook_missing']} "
                f"spread_too_wide={cycle_counts['spread_too_wide']} "
                f"liquidity_too_low={cycle_counts['liquidity_too_low']} "
                f"edge_failed={cycle_counts['edge_failed']} "
                f"risk_positions_limit_failed={cycle_counts['risk_positions_limit_failed']} "
                f"risk_orders_per_market_failed={cycle_counts['risk_orders_per_market_failed']} "
                f"risk_per_market_notional_failed={cycle_counts['risk_per_market_notional_failed']} "
                f"cap_failed={cycle_counts['cap_failed']} "
                f"cash_failed={cycle_counts['cash_failed']} "
                f"stale_orders_canceled={cycle_counts['stale_orders_canceled']} "
                f"stale_orders_cancel_failed={cycle_counts['stale_orders_cancel_failed']} "
                f"aged_orders_canceled={cycle_counts['aged_orders_canceled']} "
                f"aged_orders_cancel_failed={cycle_counts['aged_orders_cancel_failed']} "
                f"orders_amended={cycle_counts['orders_amended']} "
                f"orders_amend_failed={cycle_counts['orders_amend_failed']} "
                f"entry_dry_run={cycle_counts['entry_dry_run']} "
                f"entry_submitted={cycle_counts['entry_submitted']} "
                f"duplicate_order_skipped={cycle_counts['duplicate_order_skipped']} "
                f"ticker_side_guard_skipped={cycle_counts['ticker_side_guard_skipped']} "
                f"exit_considered={cycle_counts['exit_considered']} "
                f"exit_not_eligible={cycle_counts['exit_not_eligible']} "
                f"exit_blocked={cycle_counts['exit_decision_blocked']} "
                f"exit_dry_run={cycle_counts['exit_dry_run']} "
                f"exit_submitted={cycle_counts['exit_submitted']}"
            )
            blocked_parts = []
            if blocked_examples["orderbook_missing"]:
                blocked_parts.append("orderbook_missing=" + ", ".join(blocked_examples["orderbook_missing"]))
            if blocked_examples["edge_failed"]:
                blocked_parts.append("edge_failed=" + ", ".join(blocked_examples["edge_failed"]))
            if blocked_examples["spread_too_wide"]:
                blocked_parts.append("spread_too_wide=" + ", ".join(blocked_examples["spread_too_wide"]))
            if blocked_examples["liquidity_too_low"]:
                blocked_parts.append("liquidity_too_low=" + ", ".join(blocked_examples["liquidity_too_low"]))
            if blocked_parts:
                console.print("Cycle blocked tickers: " + " | ".join(blocked_parts))
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
