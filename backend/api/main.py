"""FastAPI application for the API gateway.

Wires together auth, rate limiting, the bimodal ML inference module and the
execution/risk engine behind a single endpoint, `POST /process_arbitrage_intent`,
per docs/ARCHITECTURE.md section 6.

The ML and execution modules (backend.ml, backend.execution, backend.marketdata)
are owned by other units being implemented in parallel; this module only
depends on the interfaces documented below and imported at module load time.
If those modules are missing at import time, this module fails to import —
which is expected outside of isolated unit tests. Tests provide local stubs
(see tests/conftest.py) and monkeypatch the call sites directly.
"""
from __future__ import annotations

import asyncio
import logging
import random
import sys
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI

from backend.api.contracts import TradeSignalRequest, TradeSignalResponse
from backend.api.dashboard import router as dashboard_router
from backend.api.rate_limit import rate_limit_dependency
from backend.ml.model_cache import get_model as _get_model
from backend.schemas import DepthMatrix, RiskLimits, TemporalFeatures

logger = logging.getLogger("backend.api.main")

if sys.platform == "win32":
    # ccxt requires aiodns, and aiohttp (which ccxt's async clients use)
    # prefers aiodns for DNS resolution whenever it's importable. aiodns
    # (pycares/c-ares) frequently cannot read Windows' DNS configuration
    # correctly and fails with "Could not contact DNS servers"
    # (aiodns.error.DNSError errno 11, ECONNREFUSED) even though the
    # machine's own DNS works fine for everything else — switching the
    # asyncio event loop policy alone does not fix this. Poisoning the
    # module cache here (before aiohttp.resolver's own `import aiodns`
    # runs anywhere in the process) makes that import fail, so aiohttp
    # falls back to ThreadedResolver — plain socket.getaddrinfo, the same
    # resolution path every other program on the machine already uses.
    sys.modules["aiodns"] = None  # type: ignore[assignment]

    # Belt-and-suspenders: also avoid ProactorEventLoop, since it doesn't
    # support add_reader/add_writer used by some libraries' fallback
    # resolvers and is a known source of other asyncio-on-Windows quirks.
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


@asynccontextmanager
async def _lifespan(app: FastAPI):
    """Launches the local paper-trading runner (backend.marketdata.runner)
    as a background task, unless disabled via RUNNER_ENABLED=false.

    This is the local-service entry point the user chose over an Android
    app for the initial validation phase: real market data drives the
    model, but only simulated (paper) orders are ever placed — see
    backend.marketdata.runner and backend.execution.paper_exchange.
    """
    from backend.marketdata.runner import run_forever

    runner_task = asyncio.create_task(run_forever())
    try:
        yield
    finally:
        runner_task.cancel()


app = FastAPI(title="Bimodal Arbitrage API Gateway", lifespan=_lifespan)
app.include_router(dashboard_router)


def _synthetic_temporal_features() -> TemporalFeatures:
    """Placeholder Stream 1 input, pending live backend.marketdata wiring.

    See docs/ARCHITECTURE.md section 6: the reference Modal skeleton itself
    used synthetic normalized tensors as an explicit interim mock at this
    call site. backend.marketdata's WS ingestion is a long-running
    worker/cache, not something this synchronous HTTP handler fetches
    per-request — wiring it in (or an order-book cache read) is tracked in
    DEPLOY.md as a pre-launch task.
    """
    return TemporalFeatures(
        window=[
            [random.gauss(0.0, 1.0) for _ in range(TemporalFeatures.FEATURE_COUNT)]
            for _ in range(TemporalFeatures.WINDOW_SIZE)
        ]
    )


def _synthetic_depth_matrix() -> DepthMatrix:
    """Placeholder Stream 2 input — see _synthetic_temporal_features()."""
    return DepthMatrix(
        grid=[
            [random.random() for _ in range(DepthMatrix.SIZE)]
            for _ in range(DepthMatrix.SIZE)
        ]
    )


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}


@app.post("/process_arbitrage_intent", response_model=TradeSignalResponse)
async def process_arbitrage_intent(
    request: TradeSignalRequest,
    user_id: str = Depends(rate_limit_dependency),
) -> TradeSignalResponse:
    """Evaluate an arbitrage intent and, if approved by risk, dispatch orders.

    Flow:
      1. Authenticate + rate-limit the caller (via dependencies).
      2. Evaluate the bimodal ML model on the current spread
         (backend.ml.inference.evaluate_spread).
      3. Apply the risk/decision gate (backend.execution.decision.should_execute).
      4. If approved, dispatch orders with broken-leg mitigation
         (backend.execution.broken_leg) and return status=ORDER_DISPATCHED.
         Otherwise return status=SIGNAL_REJECTED with the rejection reason.
    """
    # Imported lazily (inside the handler) rather than at module top-level so
    # that tests can monkeypatch backend.ml.inference / backend.execution.*
    # attributes and have this handler see the patched versions even when
    # those packages only exist as test stubs.
    from backend.execution import broken_leg
    from backend.execution.decision import should_execute
    from backend.ml.inference import evaluate_spread

    if request.user_id != user_id:
        return TradeSignalResponse(
            status="SIGNAL_REJECTED",
            reason="user_id mismatch between token and request body",
            metrics={},
        )

    temporal = _synthetic_temporal_features()
    depth = _synthetic_depth_matrix()
    # evaluate_spread is synchronous (a plain torch forward pass under
    # @torch.no_grad()) — run it off the event loop thread.
    signal = await asyncio.to_thread(evaluate_spread, _get_model(), temporal, depth)

    limits = RiskLimits(min_alpha_bps=request.min_alpha_bps)

    # net_alpha_bps: the model's own alpha head (signal.expected_alpha_bps)
    # already estimates net alpha in bps for this candidate opportunity — see
    # backend.ml.model.BimodalArbitrageNet's alpha_head and
    # backend.execution.alpha.compute_net_alpha for the underlying formula
    # this estimate approximates.
    approved, reason = should_execute(
        net_alpha_bps=signal.expected_alpha_bps,
        signal=signal,
        limits=limits,
        trade_notional_usd=request.capital_allocation_usd,
    )

    metrics = {
        "execution_probability": signal.execution_probability,
        "expected_alpha_bps": signal.expected_alpha_bps,
        "adverse_hazard": signal.adverse_hazard,
    }

    if not approved:
        return TradeSignalResponse(
            status="SIGNAL_REJECTED",
            reason=reason,
            metrics=metrics,
            target_pair=f"{request.exchange_buy}->{request.exchange_sell}:{request.symbol}",
        )

    try:
        execution_result = await broken_leg.dispatch_orders(
            request=request,
            signal=signal,
        )
    except Exception:
        logger.exception("Order dispatch failed for user_id=%s symbol=%s", user_id, request.symbol)
        return TradeSignalResponse(
            status="SIGNAL_REJECTED",
            reason="order dispatch failed",
            metrics=metrics,
            target_pair=f"{request.exchange_buy}->{request.exchange_sell}:{request.symbol}",
        )

    metrics["execution_status"] = getattr(execution_result, "status", None)
    metrics["net_spread_pct"] = getattr(execution_result, "net_spread_pct", None)
    metrics["realized_pnl_usd"] = getattr(execution_result, "realized_pnl_usd", None)

    return TradeSignalResponse(
        status="ORDER_DISPATCHED",
        reason=None,
        metrics=metrics,
        allocated_capital=request.capital_allocation_usd,
        target_pair=f"{request.exchange_buy}->{request.exchange_sell}:{request.symbol}",
    )
