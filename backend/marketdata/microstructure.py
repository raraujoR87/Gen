"""Pure functions computing microstructure metrics from order book snapshots.

Implements exactly the formulas in docs/ARCHITECTURE.md section 3
("Pipeline de Ingestao de Microestrutura e Market Data"). No I/O, no
external state — safe to unit test with small synthetic books.
"""
from __future__ import annotations

from backend.schemas import MicrostructureMetrics, OrderBookLevel, OrderBookSnapshot


def compute_vwap(levels: list[OrderBookLevel], quantity: float) -> float:
    """VWAP to fill `quantity` units walking `levels` in order.

    VWAP(Q) = sum_i P_i * min(q_i, Q - sum_{j<i} q_j) / Q

    `levels` must already be ordered best-first (best bid first for the bid
    side, best ask first for the ask side) — the function does not sort.

    Raises ValueError if `quantity` is not positive, or if the book does not
    have enough depth to fill the requested quantity.
    """
    if quantity <= 0:
        raise ValueError("quantity must be positive")

    filled = 0.0
    notional = 0.0
    for level in levels:
        remaining = quantity - filled
        if remaining <= 0:
            break
        take = min(level.volume, remaining)
        notional += level.price * take
        filled += take

    if filled < quantity:
        raise ValueError(
            f"insufficient depth to fill quantity={quantity}: only {filled} available"
        )

    return notional / quantity


def compute_micro_price(best_bid: OrderBookLevel, best_ask: OrderBookLevel) -> float:
    """Micro-price weighted by the *opposite* side's volume.

    P_micro = P_bid * (V_ask / (V_bid + V_ask)) + P_ask * (V_bid / (V_bid + V_ask))
    """
    total_volume = best_bid.volume + best_ask.volume
    if total_volume <= 0:
        raise ValueError("best_bid.volume + best_ask.volume must be positive")

    bid_weight = best_ask.volume / total_volume
    ask_weight = best_bid.volume / total_volume
    return best_bid.price * bid_weight + best_ask.price * ask_weight


def _best_level(levels: list[OrderBookLevel]) -> OrderBookLevel:
    if not levels:
        raise ValueError("order book side has no levels")
    return levels[0]


def compute_order_flow_imbalance(prev: OrderBookSnapshot, curr: OrderBookSnapshot) -> float:
    """Order Flow Imbalance (OFI_t) between two consecutive snapshots.

    Classic best-quote OFI (Cont, Kukanov & Stoikov): contribution from each
    side depends on whether the best price improved, stayed, or worsened
    between t-1 and t.

    Bid-side contribution e^b_t:
      P_bid_t  > P_bid_{t-1}: +V_bid_t
      P_bid_t == P_bid_{t-1}: V_bid_t - V_bid_{t-1}
      P_bid_t  < P_bid_{t-1}: -V_bid_t

    Ask-side contribution e^a_t:
      P_ask_t  > P_ask_{t-1}: -V_ask_t
      P_ask_t == P_ask_{t-1}: V_ask_t - V_ask_{t-1}
      P_ask_t  < P_ask_{t-1}: +V_ask_t

    OFI_t = e^b_t - e^a_t
    """
    prev_bid = _best_level(prev.bids)
    curr_bid = _best_level(curr.bids)
    prev_ask = _best_level(prev.asks)
    curr_ask = _best_level(curr.asks)

    if curr_bid.price > prev_bid.price:
        e_bid = curr_bid.volume
    elif curr_bid.price == prev_bid.price:
        e_bid = curr_bid.volume - prev_bid.volume
    else:
        e_bid = -curr_bid.volume

    if curr_ask.price > prev_ask.price:
        e_ask = -curr_ask.volume
    elif curr_ask.price == prev_ask.price:
        e_ask = curr_ask.volume - prev_ask.volume
    else:
        e_ask = curr_ask.volume

    return e_bid - e_ask


def compute_microstructure_metrics(
    prev: OrderBookSnapshot,
    curr: OrderBookSnapshot,
    quantity: float,
) -> MicrostructureMetrics:
    """Bundle vwap_ask/vwap_bid/micro_price/OFI for snapshot `curr` given `prev`."""
    vwap_ask = compute_vwap(curr.asks, quantity)
    vwap_bid = compute_vwap(curr.bids, quantity)
    micro_price = compute_micro_price(_best_level(curr.bids), _best_level(curr.asks))
    ofi = compute_order_flow_imbalance(prev, curr)

    return MicrostructureMetrics(
        vwap_ask=vwap_ask,
        vwap_bid=vwap_bid,
        micro_price=micro_price,
        order_flow_imbalance=ofi,
    )
