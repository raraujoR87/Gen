"""Central place to read the local-runner's environment configuration.

Kept separate from backend/db/session.py's DATABASE_URL and
backend/api/auth.py's JWT_SECRET (those are read directly where used,
matching the existing convention) — this module is specifically for the
new autonomous local paper-trading runner's settings.
"""
from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class PairConfig:
    symbol: str
    exchange_buy: str
    exchange_sell: str


def _parse_monitored_pairs(raw: str) -> list[PairConfig]:
    """Parses MONITORED_PAIRS="BTC/USDT:binance:kraken,ETH/USDT:binance:bybit"."""
    pairs: list[PairConfig] = []
    for chunk in raw.split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        parts = chunk.split(":")
        if len(parts) != 3:
            raise ValueError(
                f"invalid MONITORED_PAIRS entry {chunk!r}; expected SYMBOL:exchange_buy:exchange_sell"
            )
        symbol, exchange_buy, exchange_sell = parts
        pairs.append(PairConfig(symbol=symbol, exchange_buy=exchange_buy, exchange_sell=exchange_sell))
    return pairs


@dataclass(frozen=True)
class RunnerConfig:
    monitored_pairs: list[PairConfig]
    notional_per_trade_usd: float
    default_taker_fee_bps: float
    poll_interval_s: float
    local_user_email: str
    redis_url: str
    enabled: bool
    sample_logging_enabled: bool
    sample_log_path: str


def load_runner_config() -> RunnerConfig:
    raw_pairs = os.environ.get("MONITORED_PAIRS", "")
    return RunnerConfig(
        monitored_pairs=_parse_monitored_pairs(raw_pairs),
        notional_per_trade_usd=float(os.environ.get("NOTIONAL_PER_TRADE_USD", "50.0")),
        default_taker_fee_bps=float(os.environ.get("DEFAULT_TAKER_FEE_BPS", "10.0")),
        poll_interval_s=float(os.environ.get("POLL_INTERVAL_S", "2.0")),
        local_user_email=os.environ.get("LOCAL_USER_EMAIL", "local@paper-trading.dev"),
        redis_url=os.environ.get("REDIS_URL", "redis://localhost:6379/0"),
        enabled=os.environ.get("RUNNER_ENABLED", "true").lower() in ("1", "true", "yes"),
        sample_logging_enabled=os.environ.get("SAMPLE_LOGGING_ENABLED", "true").lower() in ("1", "true", "yes"),
        sample_log_path=os.environ.get("SAMPLE_LOG_PATH", "data/training_samples.jsonl"),
    )
