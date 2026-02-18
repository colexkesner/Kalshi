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


class RiskConfig(BaseModel):
    p_confidence_gate: float = 0.90
    lock_yes_probability: float = 0.99
    lock_no_probability: float = 0.01
    edge_buffer: float = 0.02
    safety_bias_f: float = 3.0
    min_hours_to_close: float = 0.25
    max_hours_to_close: float = 6.0
    max_per_market_notional: float = 50.0
    max_open_positions: int = 5
    max_orders_per_market: int = 2
    min_liquidity_contracts: int = 5
    max_spread_cents: int = 15


class DataConfig(BaseModel):
    cache_ttl_seconds: int = 60
    aviationweather_base_url: str = "https://aviationweather.gov"
    nws_base_url: str = "https://api.weather.gov"


class ScanConfig(BaseModel):
    tags: str = "Weather"
    limit_series: int = 30
    limit_markets: int = 100


class AppConfig(BaseModel):
    env: Literal["demo", "production"] = "demo"
    base_url: str = "https://demo-api.kalshi.co"
    user_agent: str = "kalshi-weather-hitbot/0.1 (+local)"
    api_key_id: str = ""
    private_key_path: str = "./secrets/kalshi.key"
    db_path: str = "./kalshi_weather_hitbot.db"
    trading_enabled: bool = False
    capital: CapitalConfig = Field(default_factory=CapitalConfig)
    risk: RiskConfig = Field(default_factory=RiskConfig)
    data: DataConfig = Field(default_factory=DataConfig)
    scan: ScanConfig = Field(default_factory=ScanConfig)


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
