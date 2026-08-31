"""Simple kill switch controller for RiskLimits.kill_switch_engaged.

RiskLimits is a frozen dataclass, so "toggling" it means producing a new
instance with kill_switch_engaged flipped. This module optionally persists
the engaged state to a small JSON file so it survives process restarts,
without pulling in any external infra (no DB, no Redis).
"""
from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import Optional

from backend.schemas import RiskLimits

DEFAULT_STATE_PATH = Path("kill_switch_state.json")


class KillSwitch:
    """In-memory (optionally file-backed) kill switch controller."""

    def __init__(self, state_path: Optional[Path] = None):
        self._state_path = state_path
        self._engaged = False
        if self._state_path is not None:
            self._engaged = self._read_persisted()

    @property
    def engaged(self) -> bool:
        return self._engaged

    def engage(self) -> None:
        """Trip the kill switch (blocks all new executions)."""
        self._set(True)

    def disengage(self) -> None:
        """Reset the kill switch (allows executions again)."""
        self._set(False)

    def apply(self, limits: RiskLimits) -> RiskLimits:
        """Return a copy of `limits` with kill_switch_engaged set to this
        switch's current state. RiskLimits is frozen, so this never mutates
        the input."""
        return replace(limits, kill_switch_engaged=self._engaged)

    def _set(self, value: bool) -> None:
        self._engaged = value
        if self._state_path is not None:
            self._persist()

    def _persist(self) -> None:
        assert self._state_path is not None
        self._state_path.write_text(json.dumps({"kill_switch_engaged": self._engaged}))

    def _read_persisted(self) -> bool:
        assert self._state_path is not None
        if not self._state_path.exists():
            return False
        try:
            data = json.loads(self._state_path.read_text())
            return bool(data.get("kill_switch_engaged", False))
        except (json.JSONDecodeError, OSError):
            return False
