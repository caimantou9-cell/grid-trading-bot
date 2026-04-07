"""
main.py — Grid Bot Command-Line Entry Point

Usage:
    python main.py --config config.json
    python main.py --config config.json --log-level DEBUG

Config file format: see config.json.example
"""
from __future__ import annotations

import argparse
import asyncio
import importlib
import json
import logging
import sys
from decimal import Decimal
from pathlib import Path


def _setup_logging(level: str, log_file: str | None) -> None:
    fmt = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stdout)]
    if log_file:
        handlers.append(logging.FileHandler(log_file, encoding="utf-8"))
    logging.basicConfig(level=getattr(logging, level.upper(), logging.INFO),
                        format=fmt, handlers=handlers)
    # Suppress verbose third-party loggers
    for noisy in ("aiohttp", "asyncio", "urllib3"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def _load_adapter(cfg: dict):
    """
    Instantiate the exchange adapter specified in config['exchange']['adapter'].

    The value must be a dotted import path to an ExchangeAdapter subclass, e.g.:
        "exchanges.my_exchange.MyAdapter"

    The class is imported dynamically and constructed with:
        MyAdapter(api_key, api_secret, extra)
    """
    exc = cfg.get("exchange", {})
    adapter_path: str = exc.get("adapter", "")
    if not adapter_path:
        print("ERROR: config.exchange.adapter is required.\n"
              "  Set it to the dotted import path of your ExchangeAdapter subclass,\n"
              "  e.g.: \"exchanges.my_exchange.MyAdapter\"", file=sys.stderr)
        sys.exit(1)

    parts = adapter_path.rsplit(".", 1)
    if len(parts) != 2:
        print(f"ERROR: invalid adapter path: {adapter_path!r}", file=sys.stderr)
        sys.exit(1)

    module_path, class_name = parts
    try:
        module = importlib.import_module(module_path)
    except ModuleNotFoundError as e:
        print(f"ERROR: cannot import adapter module '{module_path}': {e}", file=sys.stderr)
        sys.exit(1)

    cls = getattr(module, class_name, None)
    if cls is None:
        print(f"ERROR: class '{class_name}' not found in module '{module_path}'", file=sys.stderr)
        sys.exit(1)

    api_key    = exc.get("api_key", "")
    api_secret = exc.get("api_secret", "")
    extra      = exc.get("extra", None)
    if isinstance(extra, dict):
        extra = json.dumps(extra)

    return cls(api_key, api_secret, extra)


async def _run(config_path: str, log_level: str, log_file: str | None) -> None:
    raw = json.loads(Path(config_path).read_text(encoding="utf-8"))

    _setup_logging(log_level or raw.get("log_level", "INFO"), log_file or raw.get("log_file"))

    # Import here so logging is configured first
    from exchanges.base import ExchangeAdapter  # noqa: F401 — validate interface available
    from grid.config import GridConfig
    from grid.strategy import GridStrategy

    adapter = _load_adapter(raw)

    strategy_cfg = raw.get("strategy", {})
    try:
        config = GridConfig(**strategy_cfg)
    except Exception as e:
        print(f"ERROR: invalid strategy config: {e}", file=sys.stderr)
        sys.exit(1)

    bot = GridStrategy(adapter, config)
    await bot.start()


def main() -> None:
    parser = argparse.ArgumentParser(description="Neutral Grid Bot")
    parser.add_argument("--config",    required=True,  help="Path to config.json")
    parser.add_argument("--log-level", default=None,   help="DEBUG | INFO | WARNING (overrides config)")
    parser.add_argument("--log-file",  default=None,   help="Append logs to this file (overrides config)")
    args = parser.parse_args()

    if not Path(args.config).exists():
        print(f"ERROR: config file not found: {args.config}", file=sys.stderr)
        sys.exit(1)

    asyncio.run(_run(args.config, args.log_level, args.log_file))


if __name__ == "__main__":
    main()
