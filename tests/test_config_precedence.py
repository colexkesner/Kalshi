from kalshi_weather_hitbot import cli
from kalshi_weather_hitbot.config import AppConfig, EnvSettings


def _env_settings(**overrides) -> EnvSettings:
    base = EnvSettings(
        kalshi_env="demo",
        kalshi_api_key_id="",
        kalshi_private_key_path="./secrets/kalshi.key",
        kalshi_user_agent="ua",
        kalshi_db_path="./env.db",
        kalshi_config_path="./configs/config.yaml",
        kalshi_trading_enabled=False,
    )
    return base.model_copy(update=overrides)


def test_load_cfg_warns_on_env_base_and_db_mismatch(monkeypatch, capsys):
    cfg = AppConfig(env="production", base_url="https://api.elections.kalshi.com", db_path="./yaml.db")
    monkeypatch.setattr(cli.EnvSettings, "load", lambda: _env_settings(kalshi_env="demo", kalshi_db_path="./env.db"))
    monkeypatch.setattr(cli, "load_yaml_config", lambda _p: cfg)

    out = cli._load_cfg()
    captured = capsys.readouterr().out

    assert out.env == "demo"
    assert out.base_url == "https://demo-api.kalshi.co"
    assert out.db_path == "./env.db"
    assert "YAML env='production' but runtime KALSHI_ENV='demo'" in captured
    assert "YAML base_url='https://api.elections.kalshi.com'" in captured
    assert "YAML db_path='./yaml.db'" in captured


def test_load_cfg_honors_yaml_base_url_when_enabled(monkeypatch, capsys):
    cfg = AppConfig(env="demo", base_url="https://custom.example", db_path="./kalshi_weather_hitbot.db")
    cfg.runtime.allow_yaml_base_url = True
    monkeypatch.setattr(cli.EnvSettings, "load", lambda: _env_settings(kalshi_env="production", kalshi_db_path="./kalshi_weather_hitbot.db"))
    monkeypatch.setattr(cli, "load_yaml_config", lambda _p: cfg)

    out = cli._load_cfg()
    captured = capsys.readouterr().out

    assert out.env == "production"
    assert out.base_url == "https://custom.example"
    assert "CONFIG WARNING" in captured
