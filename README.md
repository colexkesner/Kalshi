# kalshi-weather-hitbot

A safe-by-default **Kalshi** weather bot (daily high-temperature markets) with conservative lock logic and optional profit-cycling mode.

## Install
```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .[dev]
cp configs/config.example.yaml configs/config.yaml
cp configs/cities.example.yaml configs/cities.yaml
```

## Credentials
For authenticated endpoints and live orders:
- `KALSHI_API_KEY_ID`
- `KALSHI_PRIVATE_KEY_PATH` (downloaded Kalshi private key file)

Environments:
- Demo: `https://demo-api.kalshi.co`
- Production: `https://api.elections.kalshi.com`

## Kalshi signing
Sign: `timestamp_ms + METHOD + PATH_WITHOUT_QUERY` using RSA-PSS SHA256.

## Strategy modes
- `HOLD_TO_SETTLEMENT` (default): enter locked outcomes and hold.
- `MAX_CYCLES`: try exits first (reduce-only sells), then entries.

## Safety defaults
- DRY-RUN by default.
- Live requires `--enable-trading`.
- Production live requires typing: `I_UNDERSTAND_THIS_WILL_TRADE_REAL_MONEY`.

## CLI
```bash
kalshi-hitbot init
kalshi-hitbot scan
kalshi-hitbot run
kalshi-hitbot run --cap 150
kalshi-hitbot run --cap 20%
kalshi-hitbot run --enable-trading
```

## Testing
```bash
pytest
```

No `PYTHONPATH` hack is needed.
