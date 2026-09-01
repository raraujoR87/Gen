"""Process-wide singleton BimodalArbitrageNet instance.

Both the on-demand HTTP endpoint (backend/api/main.py) and the autonomous
local runner (backend/marketdata/runner.py) need a model instance — sharing
one avoids re-instantiating (and re-randomizing, since it's untrained)
separate networks that would silently disagree with each other.
"""
from __future__ import annotations

from backend.ml.model import BimodalArbitrageNet

_model: BimodalArbitrageNet | None = None


def get_model() -> BimodalArbitrageNet:
    """Returns the shared model instance, constructing it once.

    Untrained (randomly initialized) weights — see docs/ARCHITECTURE.md
    section 9, Fase 1: this must be replaced with a checkpoint loaded via
    backend.ml.train.load_checkpoint before TRADING_MODE=live.
    """
    global _model
    if _model is None:
        _model = BimodalArbitrageNet()
        _model.eval()
    return _model
