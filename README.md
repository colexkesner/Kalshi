# kalshi-weather-hitbot

A **safe-by-default** Python trading bot for Kalshi weather markets. It targets high hit-rate trades by acting only when outcomes appear nearly locked by objective data (METAR observations + NWS hourly forecasts).

## What this bot does
- Screens Kalshi weather series/markets.
- Pulls objective weather data:
  - METAR: `https://aviationweather.gov/api/data/metar`
  - NWS: `https://api.weather.gov`
- Evaluates conservative lock logic:
  - Locked YES if `min_possible >= L` and `max_possible <= U`
  - Locked NO if `min_possible > U` or `max_possible < L`
- Defaults to **DRY-RUN**.
- Uses **post-only maker limit** orders when trading is enabled.
- Persists market snapshots, evaluations, and order attempts to SQLite for auditability.

## Kalshi environments
- Demo: `https://demo-api.kalshi.co`
- Production: `https://api.elections.kalshi.com`

## Authentication signing (critical)
Authenticated headers:
- `KALSHI-ACCESS-KEY`
- `KALSHI-ACCESS-TIMESTAMP`
- `KALSHI-ACCESS-SIGNATURE`

Signature message format:
```text
timestamp_ms + HTTP_METHOD + PATH_WITHOUT_QUERY
```
Example:
```text
1703123456789GET/trade-api/v2/portfolio/balance
```
Important rules:
- Do not include hostname.
- Do not include query params in signed path.
- Use RSA-PSS + SHA256, salt length `PSS.DIGEST_LENGTH`.

## Windows + VS Code setup
```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env
copy configs\config.example.yaml configs\config.yaml
copy configs\cities.example.yaml configs\cities.yaml
```

Recommended private key location: `./secrets/kalshi.key` (gitignored).  
Create API key in Kalshi account settings → API Keys, download the private key, and store securely (it cannot be retrieved later).

## Run commands
Because code lives under `src/`, use `PYTHONPATH=src`:

```bash
PYTHONPATH=src python -m kalshi_weather_hitbot init
PYTHONPATH=src python -m kalshi_weather_hitbot scan
PYTHONPATH=src python -m kalshi_weather_hitbot run
PYTHONPATH=src python -m kalshi_weather_hitbot run --enable-trading
```

Production trading requires `--enable-trading` **and** typed confirmation:
`I_UNDERSTAND_THIS_WILL_TRADE_REAL_MONEY`.

## CLI overview
- `init`: interactive setup, API info, and capital cap (`$` or `%` of available balance).
- `scan`: scan candidates and print locked states (no orders).
- `run`: loop mode, default dry-run.
- `positions`: portfolio balance/info.
- `orders`: show open orders.
- `cancel-all --confirm`: cancel open orders.

## Rate limits and cache
- AviationWeather: keep under 100 req/min. Bot includes TTL caching (default 60s).
- NWS requests also cached with TTL.

## Disclaimers
- No profit guarantees.
- Spreads, liquidity, and fees materially affect outcomes.
- Market settlement uses market rules; station differences can still matter. This bot stores rules metadata for traceability.

