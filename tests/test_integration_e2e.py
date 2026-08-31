"""End-to-end integration test for the full arbitrage pipeline.

This test is an executable specification of the flow described in
docs/ARCHITECTURE.md:

    OrderBookSnapshot(s)
        -> MicrostructureMetrics            (backend.marketdata, unit 2)
        -> TemporalFeatures / DepthMatrix    (backend.marketdata / backend.ml, units 2/3)
        -> BimodalArbitrageNet.evaluate_spread -> ArbitrageSignal   (backend.ml, unit 3)
        -> should_execute(signal, RiskLimits) -> bool                (backend.execution, unit 4)
        -> execute_paired_orders(...) -> TradeExecutionResult         (backend.execution, unit 4)
        -> record_execution(...)                                     (backend.db, unit 6)
        -> get_recent_executions(...)                                (backend.db, unit 6)

Units 1-6 (backend/security, backend/marketdata, backend/ml, backend/execution,
backend/api, backend/db) are implemented in parallel branches and will not
exist in this branch's checkout yet. Every cross-unit import is guarded with
`pytest.importorskip` so this test SKIPS gracefully (instead of erroring the
whole suite) until those modules are merged, while still documenting and
exercising the intended contract once they are.

Function/class names below (`evaluate_spread`, `should_execute`,
`execute_paired_orders`, `record_execution`, `get_recent_executions`,
`compute_microstructure_metrics`, `BimodalArbitrageNet`) follow the naming
implied by docs/ARCHITECTURE.md and backend/schemas.py. If a given unit lands
with a different symbol name, update the corresponding import below rather
than the overall test shape.
"""
from __future__ import annotations

import datetime as dt
import random

import pytest

from backend.schemas import (
    ExecutionStatus,
    OrderBookLevel,
    OrderBookSnapshot,
    TemporalFeatures,
    DepthMatrix,
)

pytestmark = pytest.mark.integration


def _synthetic_order_book(exchange: str, symbol: str, mid: float) -> OrderBookSnapshot:
    """Build a synthetic, deterministic L2 snapshot around `mid`."""
    rng = random.Random(42)
    bids = [
        OrderBookLevel(price=round(mid - i * 0.5, 2), volume=round(rng.uniform(0.1, 2.0), 4))
        for i in range(1, 11)
    ]
    asks = [
        OrderBookLevel(price=round(mid + i * 0.5, 2), volume=round(rng.uniform(0.1, 2.0), 4))
        for i in range(1, 11)
    ]
    return OrderBookSnapshot(
        exchange=exchange,
        symbol=symbol,
        timestamp=dt.datetime.now(dt.timezone.utc),
        bids=bids,
        asks=asks,
    )


def _synthetic_temporal_features() -> TemporalFeatures:
    rng = random.Random(7)
    window = [
        [rng.uniform(-1, 1) for _ in range(TemporalFeatures.FEATURE_COUNT)]
        for _ in range(TemporalFeatures.WINDOW_SIZE)
    ]
    return TemporalFeatures(window=window)


def _synthetic_depth_matrix() -> DepthMatrix:
    rng = random.Random(11)
    grid = [
        [rng.uniform(0, 1) for _ in range(DepthMatrix.SIZE)] for _ in range(DepthMatrix.SIZE)
    ]
    return DepthMatrix(grid=grid)


class _FakeExchangeClient:
    """Minimal fake exchange client for exercising execute_paired_orders
    without hitting a real exchange or CCXT."""

    def __init__(self, name: str):
        self.name = name
        self.orders = []

    async def create_order(self, symbol, side, amount, price=None, order_type="market"):
        order = {
            "id": f"{self.name}-{len(self.orders) + 1}",
            "symbol": symbol,
            "side": side,
            "amount": amount,
            "price": price,
            "type": order_type,
            "status": "closed",
        }
        self.orders.append(order)
        return order


@pytest.mark.asyncio
async def test_full_arbitrage_pipeline_e2e(default_risk_limits, db_session):
    # --- Step 1: synthetic order books on two exchanges -------------------
    book_a = _synthetic_order_book("binance", "BTC/USDT", mid=60000.0)
    book_b = _synthetic_order_book("bybit", "BTC/USDT", mid=60050.0)

    # --- Step 2: microstructure metrics (unit 2: backend.marketdata) ------
    marketdata_metrics = pytest.importorskip(
        "backend.marketdata.metrics",
        reason="backend.marketdata.metrics not implemented yet (unit 2)",
    )
    compute_microstructure_metrics = marketdata_metrics.compute_microstructure_metrics
    metrics_a = compute_microstructure_metrics(book_a)
    metrics_b = compute_microstructure_metrics(book_b)
    assert metrics_a.micro_price > 0
    assert metrics_b.micro_price > 0

    # --- Step 3: bimodal model inputs & evaluation (unit 3: backend.ml) ---
    ml_model = pytest.importorskip(
        "backend.ml.model", reason="backend.ml.model not implemented yet (unit 3)"
    )
    temporal_features = _synthetic_temporal_features()
    depth_matrix = _synthetic_depth_matrix()

    net = ml_model.BimodalArbitrageNet()
    signal = net.evaluate_spread(temporal_features, depth_matrix)
    assert 0.0 <= signal.execution_probability <= 1.0
    assert 0.0 <= signal.adverse_hazard <= 1.0

    # --- Step 4: risk decision (unit 4: backend.execution) ----------------
    execution_engine = pytest.importorskip(
        "backend.execution.engine",
        reason="backend.execution.engine not implemented yet (unit 4)",
    )
    should_execute = execution_engine.should_execute
    decision = should_execute(signal, default_risk_limits)
    assert isinstance(decision, bool)

    # --- Step 5: paired order execution with a fake exchange client -------
    execute_paired_orders = execution_engine.execute_paired_orders
    buy_client = _FakeExchangeClient("binance")
    sell_client = _FakeExchangeClient("bybit")

    result = await execute_paired_orders(
        buy_client=buy_client,
        sell_client=sell_client,
        symbol="BTC/USDT",
        notional_usd=default_risk_limits.max_notional_usd_per_trade,
        metrics_buy=metrics_a,
        metrics_sell=metrics_b,
        signal=signal,
    )
    assert result.status in {
        ExecutionStatus.SUCCESS,
        ExecutionStatus.PARTIAL_FILL,
        ExecutionStatus.HEDGED,
        ExecutionStatus.REJECTED,
    }

    # --- Step 6: persist execution (unit 6: backend.db) --------------------
    db_repo = pytest.importorskip(
        "backend.db.repository", reason="backend.db.repository not implemented yet (unit 6)"
    )
    record_execution = db_repo.record_execution
    get_recent_executions = db_repo.get_recent_executions

    user_id = "e2e-test-user"
    await record_execution(db_session, user_id=user_id, result=result)

    recent = await get_recent_executions(db_session, user_id=user_id, limit=10)
    assert len(recent) >= 1
    assert recent[0].symbol == "BTC/USDT"
