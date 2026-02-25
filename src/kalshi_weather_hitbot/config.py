from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, Field


class CapitalConfig(BaseModel):
    cap_mode: Literal["dollars", "percent"] = "dollars"
    cap_value: float = 100.0


class FeesConfig(BaseModel):
    enabled: bool = True
    assume_maker_fee: bool = False
    assume_taker_fee_on_exit: bool = True


class SizingConfig(BaseModel):
    mode: Literal["fixed", "fractional_kelly"] = "fixed"
    fixed_contracts: int = 1
    kelly_fraction: float = 0.10
    max_contracts_per_order: int = 10
    max_order_cost_dollars: float = 25.0


class CalibrationConfig(BaseModel):
    enabled: bool = False
    by_city: bool = False
    buckets_hours_to_close: list[float] = Field(default_factory=lambda: [1.0, 3.0, 6.0, 24.0])
    prior_alpha: float = 1.0
    prior_beta: float = 1.0
    min_samples_per_bucket: int = 5


class RiskConfig(BaseModel):
    p_confidence_gate: float = 0.90
    lock_yes_probability: float = 0.99
    lock_no_probability: float = 0.01
    edge_buffer: float = 0.02
    safety_bias_f: float = 3.0
    station_uncertainty_f: float = 0.5
    min_hours_to_close: float = 0.25
    max_hours_to_close: float = 6.0
    max_per_market_notional: float = 50.0
    max_open_positions: int = 5
    max_orders_per_market: int = 2
    min_liquidity_contracts: int = 5
    max_spread_cents: int = 15
    min_net_edge_cents: int = 2
    order_maintenance_enabled: bool = False
    amend_min_age_seconds: int = 60
    amend_max_per_cycle: int = 5
    amend_min_tick: int = 1
    cancel_unfilled_after_minutes: int | None = None
    post_only_cross_retry_once: bool = True
    strategy_mode: Literal["HOLD_TO_SETTLEMENT", "MAX_CYCLES"] = "HOLD_TO_SETTLEMENT"
    take_profit_cents: int = 98
    min_profit_cents: int = 1
    max_exit_hours_to_close: float = 6.0
    enable_exit_sells: bool = True
    maker_time_in_force: str = "good_till_canceled"
    taker_time_in_force: str = "immediate_or_cancel"
    send_price_in_dollars: bool = True


class DataConfig(BaseModel):
    cache_ttl_seconds: int = 60
    metar_timeout_seconds: int = 15
    metar_station_cooldown_seconds: int = 600
    metar_max_fallbacks: int = 2
    nws_timeout_seconds: int = 15
    aviationweather_base_url: str = "https://aviationweather.gov"
    nws_base_url: str = "https://api.weather.gov"
    awc_station_cache_url: str = "https://aviationweather.gov/data/cache/stations.cache.json.gz"
    awc_station_cache_path: str = ".cache/awc/stations.cache.json.gz"


class ScanConfig(BaseModel):
    tags: str = "Weather"
    limit_series: int = 30
    limit_markets: int = 100


class RuntimeConfig(BaseModel):
    allow_yaml_base_url: bool = False
    warn_on_env_mismatch: bool = True
    warn_on_db_path_mismatch: bool = True


class AppConfig(BaseModel):
    env: Literal["demo", "production"] = "demo"
    base_url: str = "https://demo-api.kalshi.co"
    user_agent: str = "kalshi-weather-hitbot/0.1 (+local)"
    api_key_id: str = ""
    private_key_path: str = "./secrets/kalshi.key"
    db_path: str = "./kalshi_weather_hitbot.db"
    trading_enabled: bool = False
    capital: CapitalConfig = Field(default_factory=CapitalConfig)
    fees: FeesConfig = Field(default_factory=FeesConfig)
    sizing: SizingConfig = Field(default_factory=SizingConfig)
    calibration: CalibrationConfig = Field(default_factory=CalibrationConfig)
    risk: RiskConfig = Field(default_factory=RiskConfig)
    data: DataConfig = Field(default_factory=DataConfig)
    scan: ScanConfig = Field(default_factory=ScanConfig)
    runtime: RuntimeConfig = Field(default_factory=RuntimeConfig)


class EnvSettings(BaseModel):
    kalshi_env: str = "demo"
    kalshi_api_key_id: str = ""
    kalshi_private_key_path: str = "./secrets/kalshi.key"
    kalshi_user_agent: str = "kalshi-weather-hitbot/0.1 (+local)"
    kalshi_db_path: str = "./kalshi_weather_hitbot.db"
    kalshi_config_path: str = "./configs/config.yaml"
    kalshi_trading_enabled: bool = False

    @classmethod
    def load(cls) -> "EnvSettings":
        load_dotenv()
        return cls(
            kalshi_env=os.getenv("KALSHI_ENV", "demo"),
            kalshi_api_key_id=os.getenv("KALSHI_API_KEY_ID", ""),
            kalshi_private_key_path=os.getenv("KALSHI_PRIVATE_KEY_PATH", "./secrets/kalshi.key"),
            kalshi_user_agent=os.getenv("KALSHI_USER_AGENT", "kalshi-weather-hitbot/0.1 (+local)"),
            kalshi_db_path=os.getenv("KALSHI_DB_PATH", "./kalshi_weather_hitbot.db"),
            kalshi_config_path=os.getenv("KALSHI_CONFIG_PATH", "./configs/config.yaml"),
            kalshi_trading_enabled=os.getenv("KALSHI_TRADING_ENABLED", "false").lower() in {"1", "true", "yes"},
        )


def load_yaml_config(path: Path) -> AppConfig:
    if not path.exists():
        return AppConfig()
    data = yaml.safe_load(path.read_text()) or {}
    return AppConfig.model_validate(data)


def save_yaml_config(path: Path, cfg: AppConfig) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(cfg.model_dump(mode="json"), sort_keys=False))
