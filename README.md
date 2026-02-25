# kalshi-weather-hitbot

A safe-by-default **Kalshi** climate/weather bot focused on high hit-rate, lock-only execution.

## Environment + credentials
Set:
- `KALSHI_ENV=demo|production` (default demo)
- `KALSHI_API_KEY_ID`
- `KALSHI_PRIVATE_KEY_PATH`

Base URLs are selected automatically from `KALSHI_ENV`:
- demo: `https://demo-api.kalshi.co`
- production: `https://api.elections.kalshi.com`

By default, runtime env vars win over YAML (`env`, `base_url`, `db_path`). Startup now warns on mismatches.
Set `runtime.allow_yaml_base_url: true` only if you intentionally want to override the env-selected base URL.

## Install
### macOS / Linux
```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .[dev]
```

### Windows (PowerShell)
```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e .[dev]
```
For the local monitoring dashboard:
```powershell
pip install -e .[dev,monitor]
```

First-time setup walkthrough:
- `FIRST_STARTUP.txt`

## Bootstrap all climate cities
Generate a station-accurate mapping from Kalshi Climate series and contract terms:
```bash
kalshi-hitbot bootstrap-cities --overwrite --out configs/cities.yaml --category Climate --tags Weather
```

This command:
- pulls `/trade-api/v2/series?category=Climate&tags=Weather` by default
- parses contract terms PDF/HTML for location + WFO hints
- resolves ICAO/lat/lon using AviationWeather station cache (`stations.cache.json.gz`)
- resolves timezone via NWS `points/{lat},{lon}`
- writes `configs/cities.yaml`
- snapshots YAML to SQLite (`city_mapping_snapshots`)

Set `--tags " "` (PowerShell-safe) to fetch all tags.

If station resolution fails, city stays in YAML and is reported in a manual-override list.

## Strategy modes
- `HOLD_TO_SETTLEMENT` (default)
- `MAX_CYCLES` (exits first, reduce-only, then entries)

Safety defaults:
- DRY-RUN by default
- `--enable-trading` required for live submission
- production additionally requires typing confirmation string

## CLI
```bash
kalshi-hitbot init
kalshi-hitbot bootstrap-cities --overwrite
kalshi-hitbot bootstrap-cities --overwrite --tags " "
kalshi-hitbot scan
kalshi-hitbot run
kalshi-hitbot run --cap 150
kalshi-hitbot run --cap 20%
kalshi-hitbot run --enable-trading
```

## Monitoring
Terminal output already shows:
- cycle summaries (candidates, locks, positions, open orders, exposure)
- submitted order responses (entries/exits)

SQLite (`kalshi_weather_hitbot.db`) stores:
- `orders`
- `run_evaluations`
- `market_snapshots`

Optional Streamlit dashboard (read-only, local):
```powershell
streamlit run src/kalshi_weather_hitbot/monitor_dashboard.py
```

Aggressive demo MAX_CYCLES example config:
- `configs/config.max_cycles_demo.aggressive.example.yaml`

Profile overlays (copy values into `configs/config.yaml` as needed):
- `configs/profiles/max_upside_controlled.yaml`
- `configs/profiles/max_turnover_compounding.yaml`
- `configs/profiles/aggressive_expansion.yaml`

Recommended API hygiene:
- Set `user_agent` to include a contact handle/email for NWS requests.
- Use reasonable scan intervals and avoid excessive request rates to AviationWeather.

## Tests
```bash
pytest
```
