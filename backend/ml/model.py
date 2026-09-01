"""BimodalArbitrageNet: dual-stream network for HFT crypto arbitrage signals.

Stream 1 (Quant/Temporal): a bidirectional LSTM over a window of
``TemporalFeatures.WINDOW_SIZE`` ticks with ``TemporalFeatures.FEATURE_COUNT``
features per tick (spread, order-flow imbalance, VWAP drift, volume
acceleration, ...).

Stream 2 (Visuoespacial): a small CNN encoder over a 2D order-book depth
heatmap (``DepthMatrix``, axis X = price levels, axis Y = time, intensity =
volume).

The two stream embeddings are fused via cross-attention (temporal sequence as
query, depth embedding as key/value) and fed into three heads that predict
the fields of :class:`backend.schemas.ArbitrageSignal`:

- ``execution_probability``: P(Alpha > Custo), sigmoid-bounded to [0, 1].
- ``expected_alpha_bps``: expected net spread in basis points, unbounded.
- ``adverse_hazard``: adverse-selection / tail risk, sigmoid-bounded to [0, 1].

See ``docs/ARCHITECTURE.md`` section 4 for the narrative description of this
architecture. This module is the reference implementation it points to.
"""
from __future__ import annotations

import torch
from torch import nn

from backend.schemas import TemporalFeatures


class CrossAttentionFusion(nn.Module):
    """Cross-attention fusion of a temporal sequence embedding with an image embedding.

    The temporal sequence acts as the query; the image (depth heatmap)
    embedding acts as key and value. This lets the model attend into the
    order-book depth representation conditioned on each time step of the
    temporal stream, e.g. ``Z = softmax(QK^T / sqrt(d)) V``.
    """

    def __init__(self, embed_dim: int, num_heads: int = 4, dropout: float = 0.0) -> None:
        super().__init__()
        self.attn = nn.MultiheadAttention(
            embed_dim=embed_dim,
            num_heads=num_heads,
            dropout=dropout,
            batch_first=True,
        )
        self.norm = nn.LayerNorm(embed_dim)

    def forward(self, seq_feat: torch.Tensor, img_feat: torch.Tensor) -> torch.Tensor:
        """Fuse ``seq_feat`` (query) with ``img_feat`` (key/value).

        Args:
            seq_feat: ``[B, S, embed_dim]`` temporal sequence embedding.
            img_feat: ``[B, I, embed_dim]`` image/depth embedding.

        Returns:
            ``[B, S, embed_dim]`` fused representation.
        """
        attn_out, _ = self.attn(query=seq_feat, key=img_feat, value=img_feat)
        return self.norm(seq_feat + attn_out)


class _TemporalEncoder(nn.Module):
    """Stream 1: Bi-LSTM encoder over the temporal microstructure window."""

    def __init__(
        self,
        input_size: int = TemporalFeatures.FEATURE_COUNT,
        hidden_size: int = 64,
        num_layers: int = 2,
        dropout: float = 0.15,
        proj_dim: int = 64,
    ) -> None:
        super().__init__()
        self.lstm = nn.LSTM(
            input_size=input_size,
            hidden_size=hidden_size,
            num_layers=num_layers,
            batch_first=True,
            bidirectional=True,
            dropout=dropout,
        )
        # bidirectional -> concatenated forward/backward hidden state = 2 * hidden_size
        self.proj = nn.Linear(hidden_size * 2, proj_dim)

    def forward(self, temporal: torch.Tensor) -> torch.Tensor:
        """``temporal``: ``[B, T, input_size]`` -> ``[B, T, proj_dim]``."""
        out, _ = self.lstm(temporal)
        return self.proj(out)


class _DepthEncoder(nn.Module):
    """Stream 2: small CNN encoder over the depth heatmap."""

    def __init__(self, proj_dim: int = 64) -> None:
        super().__init__()
        self.conv = nn.Sequential(
            nn.Conv2d(1, 32, kernel_size=3, padding=1),
            nn.BatchNorm2d(32),
            nn.SiLU(),
            nn.MaxPool2d(2),  # 50x50 -> 25x25
            nn.Conv2d(32, 64, kernel_size=3, padding=1),
            nn.BatchNorm2d(64),
            nn.SiLU(),
            nn.AdaptiveAvgPool2d(1),  # -> [B, 64, 1, 1]
        )
        self.proj = nn.Linear(64, proj_dim)

    def forward(self, depth_image: torch.Tensor) -> torch.Tensor:
        """``depth_image``: ``[B, 1, H, W]`` -> ``[B, 1, proj_dim]`` (single token)."""
        feats = self.conv(depth_image).flatten(1)  # [B, 64]
        feats = self.proj(feats)  # [B, proj_dim]
        return feats.unsqueeze(1)  # [B, 1, proj_dim] so it can serve as K/V


def _mlp_head(in_dim: int, hidden_dim: int, sigmoid: bool) -> nn.Sequential:
    layers: list[nn.Module] = [
        nn.Linear(in_dim, hidden_dim),
        nn.ReLU(),
        nn.Linear(hidden_dim, 1),
    ]
    if sigmoid:
        layers.append(nn.Sigmoid())
    return nn.Sequential(*layers)


class BimodalArbitrageNet(nn.Module):
    """Dual-stream (temporal + visuoespacial) arbitrage signal network.

    Forward inputs:
        temporal_tensor: ``[B, WINDOW_SIZE, FEATURE_COUNT]`` (default ``[B, 100, 12]``).
        depth_image: ``[B, 1, SIZE, SIZE]`` (default ``[B, 1, 50, 50]``).

    Forward output: dict with keys ``execution_probability``,
    ``expected_alpha_bps``, ``adverse_hazard``, each of shape ``[B, 1]``.
    """

    def __init__(
        self,
        temporal_input_size: int = TemporalFeatures.FEATURE_COUNT,
        lstm_hidden_size: int = 64,
        lstm_num_layers: int = 2,
        lstm_dropout: float = 0.15,
        embed_dim: int = 64,
        attn_heads: int = 4,
        head_hidden_dim: int = 32,
    ) -> None:
        super().__init__()
        self.temporal_encoder = _TemporalEncoder(
            input_size=temporal_input_size,
            hidden_size=lstm_hidden_size,
            num_layers=lstm_num_layers,
            dropout=lstm_dropout,
            proj_dim=embed_dim,
        )
        self.depth_encoder = _DepthEncoder(proj_dim=embed_dim)
        self.fusion = CrossAttentionFusion(embed_dim=embed_dim, num_heads=attn_heads)

        fused_dim = embed_dim  # pooled over the temporal axis after fusion

        self.prob_head = _mlp_head(fused_dim, head_hidden_dim, sigmoid=True)
        self.alpha_head = _mlp_head(fused_dim, head_hidden_dim, sigmoid=False)
        self.adverse_head = _mlp_head(fused_dim, head_hidden_dim, sigmoid=True)

    def forward(
        self, temporal_tensor: torch.Tensor, depth_image: torch.Tensor
    ) -> dict[str, torch.Tensor]:
        seq_feat = self.temporal_encoder(temporal_tensor)  # [B, T, embed_dim]
        img_feat = self.depth_encoder(depth_image)  # [B, 1, embed_dim]

        fused = self.fusion(seq_feat, img_feat)  # [B, T, embed_dim]
        pooled = fused.mean(dim=1)  # [B, embed_dim]

        return {
            "execution_probability": self.prob_head(pooled),
            "expected_alpha_bps": self.alpha_head(pooled),
            "adverse_hazard": self.adverse_head(pooled),
        }
