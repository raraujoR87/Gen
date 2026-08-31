"""Pre-trade risk gate: decides whether a candidate signal may be executed.

Mirrors docs/ARCHITECTURE.md section 5:

    Execucao autorizada apenas se AlphaLiquido > AlphaMinimo e
    P(Alpha) > 0.85 e Hazard < 0.20

plus the per-trade / daily notional caps and the kill switch carried on
RiskLimits.
"""
from __future__ import annotations

from typing import Optional

from backend.schemas import ArbitrageSignal, RiskLimits


def should_execute(
    net_alpha_bps: float,
    signal: ArbitrageSignal,
    limits: RiskLimits,
    trade_notional_usd: Optional[float] = None,
    daily_notional_used_usd: float = 0.0,
) -> tuple[bool, str]:
    """Evaluate the full risk gate for a candidate trade.

    Args:
        net_alpha_bps: Net alpha of the candidate trade, in basis points.
        signal: The model's ArbitrageSignal for this opportunity.
        limits: The user's configured RiskLimits.
        trade_notional_usd: Notional USD size of this specific trade, if
            known. When None, the per-trade cap is not checked.
        daily_notional_used_usd: Notional USD already traded today, before
            this trade. Used together with trade_notional_usd to check the
            daily cap.

    Returns:
        (True, "") if execution is authorized.
        (False, "<reason>") with a specific reason otherwise. Checks are
        evaluated in a fixed order and the first violation is reported.
    """
    if limits.kill_switch_engaged:
        return False, "kill switch engaged"

    if net_alpha_bps <= limits.min_alpha_bps:
        return False, (
            f"net_alpha_bps {net_alpha_bps:.4f} <= min_alpha_bps "
            f"{limits.min_alpha_bps:.4f}"
        )

    if signal.execution_probability <= limits.min_execution_probability:
        return False, (
            f"execution_probability {signal.execution_probability:.4f} <= "
            f"min_execution_probability {limits.min_execution_probability:.4f}"
        )

    if signal.adverse_hazard >= limits.max_adverse_hazard:
        return False, (
            f"adverse_hazard {signal.adverse_hazard:.4f} >= "
            f"max_adverse_hazard {limits.max_adverse_hazard:.4f}"
        )

    if trade_notional_usd is not None:
        if trade_notional_usd > limits.max_notional_usd_per_trade:
            return False, (
                f"trade_notional_usd {trade_notional_usd:.2f} > "
                f"max_notional_usd_per_trade {limits.max_notional_usd_per_trade:.2f}"
            )

        projected_daily = daily_notional_used_usd + trade_notional_usd
        if projected_daily > limits.max_daily_notional_usd:
            return False, (
                f"projected daily notional {projected_daily:.2f} > "
                f"max_daily_notional_usd {limits.max_daily_notional_usd:.2f}"
            )

    return True, ""
