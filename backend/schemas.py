"""Shared data contracts used across every backend module.

These types are the interface boundary between market data, ML, execution,
security and the API gateway. Do not duplicate these definitions elsewhere —
import from here so all modules agree on shape.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional


class TradingMode(str, Enum):
    TESTNET = "testnet"
    LIVE = "live"


class ExecutionStatus(str, Enum):
    SUCCESS = "SUCCESS"
    PARTIAL_FILL = "PARTIAL_FILL"
    HEDGED = "HEDGED"
    REJECTED = "REJECTED"


@dataclass(frozen=True)
class OrderBookLevel:
    price: float
    volume: float


@dataclass(frozen=True)
class OrderBookSnapshot:
    """L2 snapshot for one symbol on one exchange at one instant."""

    exchange: str
    symbol: str
    timestamp: datetime
    bids: list[OrderBookLevel]
    asks: list[OrderBookLevel]


@dataclass(frozen=True)
class MicrostructureMetrics:
    """Derived metrics computed from a pair of OrderBookSnapshot in sequence."""

    vwap_ask: float
    vwap_bid: float
    micro_price: float
    order_flow_imbalance: float


@dataclass(frozen=True)
class TemporalFeatures:
    """Stream 1 input to BimodalArbitrageNet: [T_steps, 12] flattened as rows."""

    window: list[list[float]]  # shape [100, 12] by convention

    FEATURE_COUNT = 12
    WINDOW_SIZE = 100


@dataclass(frozen=True)
class DepthMatrix:
    """Stream 2 input to BimodalArbitrageNet: 2D depth heatmap [50, 50]."""

    grid: list[list[float]]

    SIZE = 50


@dataclass(frozen=True)
class ArbitrageSignal:
    """Output of the bimodal model for one candidate opportunity."""

    execution_probability: float  # p_exec in [0, 1]
    expected_alpha_bps: float
    adverse_hazard: float  # in [0, 1]


@dataclass(frozen=True)
class RiskLimits:
    """Per-user configurable risk envelope enforced by the execution engine."""

    min_alpha_bps: float = 15.0
    min_execution_probability: float = 0.85
    max_adverse_hazard: float = 0.20
    max_notional_usd_per_trade: float = 50.0
    max_daily_notional_usd: float = 500.0
    kill_switch_engaged: bool = False


@dataclass(frozen=True)
class TradeExecutionResult:
    status: ExecutionStatus
    buy_exchange: str
    sell_exchange: str
    symbol: str
    executed_volume_usd: float
    gross_spread_pct: float
    net_spread_pct: float
    realized_pnl_usd: float
    ml_confidence_score: float
    reason: Optional[str] = None
