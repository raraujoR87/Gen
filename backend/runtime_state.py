"""In-process shared state for the local paper-trading runner + dashboard.

Deliberately simple (module-level singleton, in-memory deque) — this is a
single-process local tool, not a distributed system. Executions are still
persisted for real via backend.db.repository.record_execution; this module
only holds the live, ephemeral view the dashboard polls (including
REJECTED signals, which are never written to arbitrage_executions since
that table is for actual — even if paper — trade outcomes).
"""
from __future__ import annotations

import time
import uuid
from collections import deque
from dataclasses import dataclass

from backend.execution.kill_switch import KillSwitch


@dataclass
class SignalRecord:
    id: str
    timestamp: float
    symbol: str
    exchange_buy: str
    exchange_sell: str
    net_alpha_bps: float
    execution_probability: float
    adverse_hazard: float
    approved: bool
    reason: str
    execution_status: str | None = None
    realized_pnl_usd: float | None = None


class RuntimeState:
    def __init__(self, history_size: int = 300) -> None:
        self.kill_switch = KillSwitch()
        self.signal_history: deque[SignalRecord] = deque(maxlen=history_size)
        self.started_at = time.time()
        self.monitored_pairs: list[str] = []
        self.errors: deque[str] = deque(maxlen=50)
        self.local_user_id: uuid.UUID | None = None

    def record_signal(self, **kwargs) -> SignalRecord:
        record = SignalRecord(id=str(uuid.uuid4()), timestamp=time.time(), **kwargs)
        self.signal_history.append(record)
        return record

    def record_error(self, message: str) -> None:
        self.errors.append(f"[{time.strftime('%H:%M:%S')}] {message}")


STATE = RuntimeState()
