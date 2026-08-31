"""Test-local stubs for modules other units are implementing in parallel.

Unit 5 (API gateway) depends on backend.ml.inference.evaluate_spread,
backend.execution.decision.should_execute and backend.execution.broken_leg,
which do not exist yet in this working copy. These stubs exist ONLY so
tests/test_api.py can exercise the API layer in isolation - they contain no
real business logic (no risk math, no model inference), just enough shape to
satisfy the imports in backend/api/main.py and to be monkeypatched per-test.
"""
from __future__ import annotations

import importlib
import sys
import types

from backend.schemas import ArbitrageSignal, ExecutionStatus, TradeExecutionResult


def _register_submodule(dotted_name: str, module: types.ModuleType) -> None:
    """Install `module` in sys.modules AND as an attribute of its parent package.

    `from package import submodule` only works reliably when the submodule is
    both registered in sys.modules and set as an attribute on the imported
    parent module object - the latter is normally done by the import
    machinery, but since these are hand-built stubs we do it explicitly.
    """
    sys.modules[dotted_name] = module
    parent_name, _, attr_name = dotted_name.rpartition(".")
    parent = importlib.import_module(parent_name)
    setattr(parent, attr_name, module)


def _install_stub_modules() -> None:
    if "backend.ml.inference" not in sys.modules:
        ml_inference = types.ModuleType("backend.ml.inference")

        async def evaluate_spread(*, symbol: str, exchange_buy: str, exchange_sell: str) -> ArbitrageSignal:
            return ArbitrageSignal(
                execution_probability=0.0,
                expected_alpha_bps=0.0,
                adverse_hazard=1.0,
            )

        ml_inference.evaluate_spread = evaluate_spread
        _register_submodule("backend.ml.inference", ml_inference)

    if "backend.execution.decision" not in sys.modules:
        execution_decision = types.ModuleType("backend.execution.decision")

        def should_execute(*, signal, request, limits):
            return False, "stub: not implemented"

        execution_decision.should_execute = should_execute
        _register_submodule("backend.execution.decision", execution_decision)

    if "backend.execution.broken_leg" not in sys.modules:
        broken_leg = types.ModuleType("backend.execution.broken_leg")

        async def dispatch_orders(*, request, signal) -> TradeExecutionResult:
            return TradeExecutionResult(
                status=ExecutionStatus.SUCCESS,
                buy_exchange=request.exchange_buy,
                sell_exchange=request.exchange_sell,
                symbol=request.symbol,
                executed_volume_usd=request.capital_allocation_usd,
                gross_spread_pct=0.0,
                net_spread_pct=0.0,
                realized_pnl_usd=0.0,
                ml_confidence_score=signal.execution_probability,
            )

        broken_leg.dispatch_orders = dispatch_orders
        _register_submodule("backend.execution.broken_leg", broken_leg)


_install_stub_modules()
