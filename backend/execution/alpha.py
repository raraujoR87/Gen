"""Net alpha computation for cross-exchange arbitrage opportunities.

Implements the Alpha Liquido formula from docs/ARCHITECTURE.md section 5:

    AlphaLiquido = (VWAP_bid_B*(1-tau_B) - VWAP_ask_A*(1+tau_A)) / (VWAP_ask_A*(1+tau_A))
                   - S_est - C_transf / Q_usd

Where leg A is the buy side (ask) and leg B is the sell side (bid).
"""
from __future__ import annotations


def compute_net_alpha(
    vwap_bid_b: float,
    tau_b: float,
    vwap_ask_a: float,
    tau_a: float,
    slippage_est: float,
    transfer_cost: float,
    capital_usd: float,
) -> float:
    """Compute the net (liquid) alpha of a candidate two-leg arbitrage trade.

    Args:
        vwap_bid_b: VWAP of the sell-side (bid) fill on exchange B.
        tau_b: Taker fee rate on exchange B (e.g. 0.001 for 10 bps).
        vwap_ask_a: VWAP of the buy-side (ask) fill on exchange A.
        tau_a: Taker fee rate on exchange A.
        slippage_est: Estimated slippage, as a fraction (S_est).
        transfer_cost: Fixed transfer/withdrawal cost in USD (C_transf).
        capital_usd: Notional capital deployed in USD (Q_usd). Must be > 0.

    Returns:
        Net alpha as a fraction (e.g. 0.0015 == 15 bps). Multiply by 1e4 to
        obtain basis points.

    Raises:
        ValueError: if capital_usd or the effective ask-side denominator is
            not strictly positive.
    """
    if capital_usd <= 0:
        raise ValueError("capital_usd must be strictly positive")

    denom = vwap_ask_a * (1 + tau_a)
    if denom <= 0:
        raise ValueError("vwap_ask_a*(1+tau_a) must be strictly positive")

    gross = (vwap_bid_b * (1 - tau_b) - denom) / denom
    return gross - slippage_est - (transfer_cost / capital_usd)
