"""Training skeleton for BimodalArbitrageNet.

This is a reference training loop, not a runnable pipeline: it has no real
dataset wired in (see ``ArbitrageDataset`` below, which raises
``NotImplementedError``). It documents the intended optimizer, combined loss
and checkpointing shape so a future unit can plug in real data loaders
without re-deriving this structure.

Loss:
    - ``execution_probability`` and ``adverse_hazard`` are trained with BCE
      (they are already sigmoid-activated in the model, so we use
      ``nn.BCELoss`` directly on the head outputs).
    - ``expected_alpha_bps`` is trained with MSE.
    - Combined loss is a weighted sum of the three.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path

import torch
from torch import nn
from torch.utils.data import DataLoader, Dataset

from backend.ml.model import BimodalArbitrageNet


@dataclass
class TrainConfig:
    epochs: int = 10
    batch_size: int = 32
    learning_rate: float = 1e-3
    prob_loss_weight: float = 1.0
    alpha_loss_weight: float = 1.0
    hazard_loss_weight: float = 1.0
    checkpoint_path: Path = Path("checkpoints/bimodal_arbitrage_net.pt")


class ArbitrageDataset(Dataset):
    """Placeholder dataset: (TemporalFeatures, DepthMatrix) -> labeled targets.

    A real implementation would load historical order-book snapshots,
    compute TemporalFeatures/DepthMatrix per sample, and label each with the
    realized execution outcome, realized net alpha (bps) and whether adverse
    selection occurred. Left unimplemented here since no real dataset is
    available yet.
    """

    def __init__(self, *_args, **_kwargs) -> None:
        raise NotImplementedError(
            "ArbitrageDataset has no real data source yet; wire in a "
            "historical order-book dataset before training."
        )

    def __len__(self) -> int:  # pragma: no cover - placeholder
        raise NotImplementedError

    def __getitem__(self, index: int):  # pragma: no cover - placeholder
        raise NotImplementedError


def combined_loss(
    outputs: dict[str, torch.Tensor],
    targets: dict[str, torch.Tensor],
    config: TrainConfig,
) -> torch.Tensor:
    """BCE for the two probability heads, MSE for the alpha head, weighted sum."""
    bce = nn.BCELoss()
    mse = nn.MSELoss()

    prob_loss = bce(outputs["execution_probability"], targets["execution_probability"])
    hazard_loss = bce(outputs["adverse_hazard"], targets["adverse_hazard"])
    alpha_loss = mse(outputs["expected_alpha_bps"], targets["expected_alpha_bps"])

    return (
        config.prob_loss_weight * prob_loss
        + config.hazard_loss_weight * hazard_loss
        + config.alpha_loss_weight * alpha_loss
    )


def train(model: BimodalArbitrageNet, dataset: Dataset, config: TrainConfig) -> None:
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    model.to(device)
    model.train()

    optimizer = torch.optim.Adam(model.parameters(), lr=config.learning_rate)
    loader = DataLoader(dataset, batch_size=config.batch_size, shuffle=True)

    for epoch in range(config.epochs):
        running_loss = 0.0
        for batch in loader:
            temporal_tensor = batch["temporal"].to(device)
            depth_tensor = batch["depth"].to(device)
            targets = {
                "execution_probability": batch["execution_probability"].to(device),
                "expected_alpha_bps": batch["expected_alpha_bps"].to(device),
                "adverse_hazard": batch["adverse_hazard"].to(device),
            }

            optimizer.zero_grad()
            outputs = model(temporal_tensor, depth_tensor)
            loss = combined_loss(outputs, targets, config)
            loss.backward()
            optimizer.step()

            running_loss += loss.item()

        avg_loss = running_loss / max(len(loader), 1)
        print(f"epoch {epoch + 1}/{config.epochs} - avg_loss={avg_loss:.4f}")

        save_checkpoint(model, config.checkpoint_path, epoch=epoch)


def save_checkpoint(model: BimodalArbitrageNet, path: Path, epoch: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    torch.save({"epoch": epoch, "model_state_dict": model.state_dict()}, path)


def load_checkpoint(model: BimodalArbitrageNet, path: Path) -> BimodalArbitrageNet:
    checkpoint = torch.load(path, map_location="cpu")
    model.load_state_dict(checkpoint["model_state_dict"])
    return model


def main() -> None:
    parser = argparse.ArgumentParser(description="Train BimodalArbitrageNet")
    parser.add_argument("--epochs", type=int, default=TrainConfig.epochs)
    parser.add_argument("--batch-size", type=int, default=TrainConfig.batch_size)
    parser.add_argument("--lr", type=float, default=TrainConfig.learning_rate)
    parser.add_argument(
        "--checkpoint", type=Path, default=TrainConfig.checkpoint_path
    )
    args = parser.parse_args()

    config = TrainConfig(
        epochs=args.epochs,
        batch_size=args.batch_size,
        learning_rate=args.lr,
        checkpoint_path=args.checkpoint,
    )

    model = BimodalArbitrageNet()
    dataset = ArbitrageDataset()  # raises NotImplementedError until wired up
    train(model, dataset, config)


if __name__ == "__main__":
    main()
