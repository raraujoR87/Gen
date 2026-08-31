"""Pydantic request/response contracts for the API gateway (unit 5).

Other units (marketdata, ml, execution, security) should not import this
module — it depends on them, never the other way around, to avoid an import
cycle when the API wires everything together.
"""
from __future__ import annotations

from pydantic import BaseModel, Field

from backend.schemas import ExecutionStatus, TradingMode


class TradeSignalRequest(BaseModel):
    user_id: str
    symbol: str = "BTC/USDT"
    exchange_buy: str
    exchange_sell: str
    capital_allocation_usd: float = Field(gt=0)
    min_alpha_bps: float = 15.0
    trading_mode: TradingMode = TradingMode.TESTNET


class TradeSignalResponse(BaseModel):
    status: str  # "ORDER_DISPATCHED" | "SIGNAL_REJECTED"
    reason: str | None = None
    metrics: dict
    allocated_capital: float | None = None
    target_pair: str | None = None


class ExecutionRecord(BaseModel):
    id: str
    user_id: str
    symbol: str
    buy_exchange: str
    sell_exchange: str
    gross_spread_pct: float
    net_spread_pct: float
    executed_volume_usd: float
    realized_pnl_usd: float
    ml_confidence_score: float
    execution_status: ExecutionStatus
