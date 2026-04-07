# Neutral Grid Bot

A minimal, exchange-agnostic neutral grid trading bot supporting both **arithmetic** and **geometric** grid strategies.

No web UI. No database. Run it from the command line with a JSON config file.

---

## Features

- **Arithmetic grid** — equal price spacing between levels
- **Geometric grid** — equal percentage spacing between levels
- **Flexible sizing** — specify `qty_per_grid` directly, or let the bot calculate it from `total_investment` and current price
- **Stop loss / Take profit** — optional price guards to stop the bot automatically
- **Exchange-agnostic** — implement one Python class to connect any exchange

---

## Quick Start

```bash
pip install -r requirements.txt

cp config.json.example config.json
# Edit config.json with your exchange credentials and strategy parameters

python main.py --config config.json
```

Logs are printed to stdout and optionally written to a file (`log_file` in config).

---

## Connecting Your Exchange

Implement `ExchangeAdapter` from `exchanges/base.py`:

```python
# exchanges/my_exchange.py
from exchanges.base import ExchangeAdapter, OrderResult, Ticker
from decimal import Decimal

class MyAdapter(ExchangeAdapter):
    async def get_ticker(self, symbol: str) -> Ticker: ...
    async def get_balance(self, currency: str = "USDT") -> Decimal: ...
    async def place_limit_order(self, symbol, side, price, qty) -> OrderResult: ...
    async def cancel_order(self, symbol, order_id) -> bool: ...
    async def get_order(self, symbol, order_id) -> OrderResult: ...
    async def get_open_orders(self, symbol) -> list[OrderResult]: ...
```

Then point `config.exchange.adapter` at your class:

```json
{
  "exchange": {
    "adapter": "exchanges.my_exchange.MyAdapter",
    "api_key": "...",
    "api_secret": "..."
  }
}
```

The `extra` field (optional string or JSON object) is passed as the third argument to your adapter's `__init__` — useful for passphrases, account indexes, RPC URLs, etc.

---

## Config Reference

| Field | Type | Required | Description |
|---|---|---|---|
| `exchange.adapter` | string | ✅ | Dotted path to your `ExchangeAdapter` subclass |
| `exchange.api_key` | string | ✅ | |
| `exchange.api_secret` | string | ✅ | |
| `exchange.extra` | string/object | — | Extra credentials (passphrase, etc.) |
| `strategy.symbol` | string | ✅ | Market name as your exchange expects it |
| `strategy.lower_price` | number | ✅ | Grid lower bound |
| `strategy.upper_price` | number | ✅ | Grid upper bound |
| `strategy.grid_count` | int | ✅ | Number of grid intervals (2–300) |
| `strategy.is_arithmetic` | bool | — | `true` = equal spacing (default), `false` = equal ratio |
| `strategy.qty_per_grid` | number | *one of | Order size per grid in base asset |
| `strategy.total_investment` | number | *one of | Total capital in quote asset; qty is auto-calculated |
| `strategy.stop_loss` | number | — | Stop bot if price drops below this |
| `strategy.take_profit` | number | — | Stop bot if price rises above this |
| `log_level` | string | — | `DEBUG` / `INFO` / `WARNING` (default: `INFO`) |
| `log_file` | string | — | Path to log file (in addition to stdout) |

---

## Project Structure

```
grid-bot/
  main.py                  # CLI entry point
  config.json.example      # Config template
  requirements.txt
  exchanges/
    base.py                # ExchangeAdapter abstract interface + data classes
  grid/
    config.py              # GridConfig parameter model (pydantic)
    strategy.py            # Core grid logic
```

---

## License

MIT
