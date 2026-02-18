# kalshi-weather-hitbot

This repository is a **Kalshi weather bot** (despite the parent folder name being `polymarket`).
It is a safe-by-default Python trading system focused on high hit-rate weather contracts.

## What this bot does
- Scans Kalshi weather markets.
- Uses conservative lock logic from METAR + NWS data.
- Trades only when outcome is deterministic enough (`LOCKED_YES` / `LOCKED_NO`).
- Defaults to **DRY-RUN** mode.

## Credentials and environments
Required for authenticated endpoints/trading:
- Kalshi API key id (`KALSHI_API_KEY_ID`)
- Downloaded private key file path (`KALSHI_PRIVATE_KEY_PATH`)

Kalshi base URLs:
- Demo: `https://demo-api.kalshi.co`
- Production: `https://api.elections.kalshi.com`

## Authentication signing (Kalshi Trade API v2)
Authenticated requests include:
- `KALSHI-ACCESS-KEY`
- `KALSHI-ACCESS-TIMESTAMP`
- `KALSHI-ACCESS-SIGNATURE`

Signature payload format:

```text
timestamp_ms + HTTP_METHOD + PATH_WITHOUT_QUERY
```

Example:

```text
1703123456789GET/trade-api/v2/portfolio/balance
```

Signing rules:
- Do not include hostname.
- Do not include query parameters in signed path.
- Use RSA-PSS with SHA256 (`PSS.DIGEST_LENGTH`).

## Strategy modes
Configured under `risk.strategy_mode`:

1. `HOLD_TO_SETTLEMENT` (default)
   - Enters only on locked outcomes.
   - No early exit attempts.

2. `MAX_CYCLES`
   - Can attempt reduce-only exit sells near close when lock remains favorable.
   - Uses `take_profit_cents`, `min_profit_cents`, and `max_exit_hours_to_close`.

## Safety defaults
- DRY-RUN remains default.
- Live trading requires `--enable-trading`.
- In production, live trading also requires typing:
  `I_UNDERSTAND_THIS_WILL_TRADE_REAL_MONEY`

## Run commands
Because code lives under `src/`, use `PYTHONPATH=src`:

```bash
PYTHONPATH=src python -m kalshi_weather_hitbot init
PYTHONPATH=src python -m kalshi_weather_hitbot scan
PYTHONPATH=src python -m kalshi_weather_hitbot run
PYTHONPATH=src python -m kalshi_weather_hitbot run --cap 150
PYTHONPATH=src python -m kalshi_weather_hitbot run --cap 20%
PYTHONPATH=src python -m kalshi_weather_hitbot run --enable-trading
```

## Notes
- `scan` works without API auth.
- `run` in DRY-RUN can work without auth, but positions/balance/order endpoints require credentials.
- This project persists evaluations/orders/capital choices to SQLite for auditability.
