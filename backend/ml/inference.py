"""Inference helpers bridging backend.schemas dataclasses and BimodalArbitrageNet."""
from __future__ import annotations

import torch

from backend.ml.model import BimodalArbitrageNet
from backend.schemas import ArbitrageSignal, DepthMatrix, TemporalFeatures


def _temporal_to_tensor(temporal: TemporalFeatures) -> torch.Tensor:
    """``TemporalFeatures.window`` ([T, F] rows) -> ``[1, T, F]`` float tensor."""
    return torch.tensor(temporal.window, dtype=torch.float32).unsqueeze(0)


def _depth_to_tensor(depth: DepthMatrix) -> torch.Tensor:
    """``DepthMatrix.grid`` ([H, W] rows) -> ``[1, 1, H, W]`` float tensor."""
    grid = torch.tensor(depth.grid, dtype=torch.float32)
    return grid.unsqueeze(0).unsqueeze(0)


@torch.no_grad()
def evaluate_spread(
    model: BimodalArbitrageNet,
    temporal: TemporalFeatures,
    depth: DepthMatrix,
) -> ArbitrageSignal:
    """Run a single candidate opportunity through the model and return an ArbitrageSignal.

    Args:
        model: a (trained or freshly-initialized) BimodalArbitrageNet.
        temporal: Stream 1 input, shape ``[WINDOW_SIZE, FEATURE_COUNT]``.
        depth: Stream 2 input, shape ``[SIZE, SIZE]``.

    Returns:
        ArbitrageSignal populated from the model's three heads.
    """
    was_training = model.training
    model.eval()
    try:
        temporal_tensor = _temporal_to_tensor(temporal)
        depth_tensor = _depth_to_tensor(depth)

        outputs = model(temporal_tensor, depth_tensor)

        return ArbitrageSignal(
            execution_probability=outputs["execution_probability"].item(),
            expected_alpha_bps=outputs["expected_alpha_bps"].item(),
            adverse_hazard=outputs["adverse_hazard"].item(),
        )
    finally:
        model.train(was_training)
