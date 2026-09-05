"""Net alpha computation for cross-exchange arbitrage opportunities.

Implements the Alpha Liquido formula from docs/ARCHITECTURE.md section 5:

    AlphaLiquido = (VWAP_bid_B*(1-tau_B) - VWAP_ask_A*(1+tau_A)) / (VWAP_ask_A*(1+tau_A))
                   - S_est - C_transf / Q_usd

Where leg A is the buy side (ask) and leg B is the sell side (bid).
"""
from __future__ import annotations

from dataclasses import dataclass


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


@dataclass(frozen=True)
class TriangularAlpha:
    """Result of compute_triangular_net_alpha: the net alpha plus the exact
    intermediate quantities its VWAP walk already computed, so a caller that
    goes on to dispatch the trade doesn't have to re-derive bridge_qty/
    target_qty (and re-walk the same book) a second time."""

    net_alpha: float
    bridge_qty: float
    target_qty: float


def compute_triangular_net_alpha(
    quote_notional: float,
    vwap_bridge_quote: float,
    vwap_target_bridge: float,
    vwap_target_quote: float,
    tau: float,
) -> TriangularAlpha:
    """Net alpha for a single-exchange triangular cycle: quote -> bridge ->
    target -> quote (e.g. USDT -> BTC -> ETH -> USDT), all three legs on the
    same exchange — no cross-exchange transfer or hedging-across-venues risk,
    unlike compute_net_alpha's two-exchange case.

    Callers should compute each VWAP the same way compute_net_alpha's
    callers already do: estimate the quantity from the best price, then
    compute_vwap() for that quantity (see backend.marketdata.runner and
    backend.marketdata.runner.TriangleMonitor). This function only does the
    arithmetic on already-derived VWAPs — it doesn't walk order books
    itself, so there's exactly one VWAP walk per leg, not a redundant one
    for the risk-gate check and another for dispatch.

    Args:
        quote_notional: Capital deployed, in quote-currency units (e.g. USD/
            USDT). Must be > 0.
        vwap_bridge_quote: VWAP to buy the bridge asset spending
            quote_notional worth of the quote currency (e.g. BTC/USDT ask VWAP).
        vwap_target_bridge: VWAP to buy the target asset with the resulting
            bridge amount (e.g. ETH/BTC ask VWAP).
        vwap_target_quote: VWAP to sell the resulting target amount back
            into the quote currency (e.g. ETH/USDT bid VWAP).
        tau: Taker fee rate, applied once per leg (three times total) —
            see backend.config.get_taker_fee_bps for per-exchange defaults.

    Returns:
        A TriangularAlpha with net_alpha as a fraction (e.g. 0.0015 == 15
        bps; multiply by 1e4 for bps) plus the bridge/target quantities the
        walk produced.

    Raises:
        ValueError: if quote_notional or any VWAP is not strictly positive.
    """
    if quote_notional <= 0:
        raise ValueError("quote_notional must be strictly positive")
    if vwap_bridge_quote <= 0 or vwap_target_bridge <= 0 or vwap_target_quote <= 0:
        raise ValueError("all three VWAPs must be strictly positive")

    bridge_qty = (quote_notional / vwap_bridge_quote) * (1 - tau)
    target_qty = (bridge_qty / vwap_target_bridge) * (1 - tau)
    quote_received = (target_qty * vwap_target_quote) * (1 - tau)

    net_alpha = (quote_received - quote_notional) / quote_notional
    return TriangularAlpha(net_alpha=net_alpha, bridge_qty=bridge_qty, target_qty=target_qty)
