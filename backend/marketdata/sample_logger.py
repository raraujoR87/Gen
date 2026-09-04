"""Appends real market samples to a local JSONL file, for future model
training.

Each record is one tick's (TemporalFeatures window, DepthMatrix grid, real
net_alpha_bps) — this is exactly the real data source
backend.ml.train.ArbitrageDataset's placeholder needs and doesn't have.
It's log-only: this module makes no claim about what happened next (no
label), since that requires a forward-looking outcome this single tick
doesn't have yet. Turning a logged file into a trained checkpoint (joining
each row with its realized future outcome, then running
backend.ml.train.train) is a deliberately separate, future step — this
module's only job is making sure real data actually accumulates while the
service runs, instead of there being nothing to train on later.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from backend.schemas import DepthMatrix, TemporalFeatures


class SampleLogger:
    """Appends one JSON record per line to `path`, creating parent dirs as needed."""

    def __init__(self, path: str | Path = "data/training_samples.jsonl") -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)

    def log(
        self,
        *,
        symbol: str,
        exchange_buy: str,
        exchange_sell: str,
        temporal: TemporalFeatures,
        depth: DepthMatrix,
        net_alpha_bps: float,
    ) -> None:
        record = {
            "timestamp": time.time(),
            "symbol": symbol,
            "exchange_buy": exchange_buy,
            "exchange_sell": exchange_sell,
            "net_alpha_bps": net_alpha_bps,
            "temporal_window": temporal.window,
            "depth_grid": depth.grid,
        }
        with self._path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")
