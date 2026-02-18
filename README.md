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

## Bootstrap all climate cities
Generate a station-accurate mapping from Kalshi Climate series and contract terms:
```bash
kalshi-hitbot bootstrap-cities --overwrite --out configs/cities.yaml --category Climate
```

This command:
- pulls `/trade-api/v2/series?category=Climate`
- parses contract terms PDF/HTML for location + WFO hints
- resolves ICAO/lat/lon using AviationWeather station cache (`stations.cache.json.gz`)
- resolves timezone via NWS `points/{lat},{lon}`
- writes `configs/cities.yaml`
- snapshots YAML to SQLite (`city_mapping_snapshots`)

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
kalshi-hitbot scan
kalshi-hitbot run
kalshi-hitbot run --cap 150
kalshi-hitbot run --cap 20%
kalshi-hitbot run --enable-trading
```

## Tests
```bash
pytest
```
