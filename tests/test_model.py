"""Tests for backend/ml/model.py and backend/ml/inference.py."""
from __future__ import annotations

import torch

from backend.ml.inference import evaluate_spread
from backend.ml.model import BimodalArbitrageNet
from backend.schemas import ArbitrageSignal, DepthMatrix, TemporalFeatures


def test_forward_pass_output_shapes_and_ranges():
    model = BimodalArbitrageNet()
    model.eval()

    temporal_tensor = torch.randn(2, TemporalFeatures.WINDOW_SIZE, TemporalFeatures.FEATURE_COUNT)
    depth_image = torch.randn(2, 1, DepthMatrix.SIZE, DepthMatrix.SIZE)

    with torch.no_grad():
        outputs = model(temporal_tensor, depth_image)

    assert set(outputs.keys()) == {
        "execution_probability",
        "expected_alpha_bps",
        "adverse_hazard",
    }

    for key in ("execution_probability", "expected_alpha_bps", "adverse_hazard"):
        assert outputs[key].shape == (2, 1)

    prob = outputs["execution_probability"]
    hazard = outputs["adverse_hazard"]

    assert torch.all(prob >= 0.0) and torch.all(prob <= 1.0)
    assert torch.all(hazard >= 0.0) and torch.all(hazard <= 1.0)

    # expected_alpha_bps is unbounded (no sigmoid) - just check it's finite.
    assert torch.all(torch.isfinite(outputs["expected_alpha_bps"]))


def test_forward_pass_is_deterministic_in_eval_mode():
    model = BimodalArbitrageNet()
    model.eval()

    temporal_tensor = torch.randn(1, TemporalFeatures.WINDOW_SIZE, TemporalFeatures.FEATURE_COUNT)
    depth_image = torch.randn(1, 1, DepthMatrix.SIZE, DepthMatrix.SIZE)

    with torch.no_grad():
        out1 = model(temporal_tensor, depth_image)
        out2 = model(temporal_tensor, depth_image)

    for key in out1:
        assert torch.allclose(out1[key], out2[key])


def test_cross_attention_fusion_preserves_sequence_shape():
    from backend.ml.model import CrossAttentionFusion

    fusion = CrossAttentionFusion(embed_dim=64, num_heads=4)
    seq_feat = torch.randn(3, 100, 64)
    img_feat = torch.randn(3, 1, 64)

    fused = fusion(seq_feat, img_feat)

    assert fused.shape == seq_feat.shape


def _synthetic_temporal() -> TemporalFeatures:
    window = [
        [0.0] * TemporalFeatures.FEATURE_COUNT for _ in range(TemporalFeatures.WINDOW_SIZE)
    ]
    return TemporalFeatures(window=window)


def _synthetic_depth() -> DepthMatrix:
    grid = [[0.0] * DepthMatrix.SIZE for _ in range(DepthMatrix.SIZE)]
    return DepthMatrix(grid=grid)


def test_evaluate_spread_end_to_end():
    model = BimodalArbitrageNet()

    temporal = _synthetic_temporal()
    depth = _synthetic_depth()

    signal = evaluate_spread(model, temporal, depth)

    assert isinstance(signal, ArbitrageSignal)
    assert 0.0 <= signal.execution_probability <= 1.0
    assert 0.0 <= signal.adverse_hazard <= 1.0
    assert isinstance(signal.expected_alpha_bps, float)


def test_evaluate_spread_restores_training_mode():
    model = BimodalArbitrageNet()
    model.train()

    evaluate_spread(model, _synthetic_temporal(), _synthetic_depth())

    assert model.training is True
