"""Modal.com deployment entrypoint for the bimodal arbitrage backend.

Wraps the FastAPI app (backend.api.main:app) as a Modal ASGI app, and defines
`BimodalInferenceWorker`, a GPU-backed Modal class that hosts the bimodal
model for inference calls issued by the API layer.

See docs/ARCHITECTURE.md section 6. Deploy with:

    modal deploy modal_app.py
"""
from __future__ import annotations

import modal

app = modal.App("bimodal-arbitrage")

image = (
    modal.Image.debian_slim(python_version="3.11")
    .pip_install_from_requirements("requirements.txt")
    .add_local_python_source("backend")
)


@app.cls(
    gpu="T4",
    scaledown_window=120,
    secrets=[modal.Secret.from_name("arbitrage-secrets")],
    image=image,
)
class BimodalInferenceWorker:
    """Hosts BimodalArbitrageNet on a T4 GPU for low-latency spread evaluation."""

    @modal.enter()
    def load_model(self) -> None:
        from backend.ml.model import BimodalArbitrageNet

        self.model = BimodalArbitrageNet()
        self.model.eval()

    @modal.method()
    def evaluate(self, temporal_window: list[list[float]], depth_grid: list[list[float]]) -> dict:
        """Run one forward pass of the bimodal model and return its signal.

        Args:
            temporal_window: Stream 1 input, shape [100, 12] (see
                backend.schemas.TemporalFeatures).
            depth_grid: Stream 2 input, shape [50, 50] (see
                backend.schemas.DepthMatrix).

        Returns:
            A dict shaped like backend.schemas.ArbitrageSignal:
            execution_probability, expected_alpha_bps, adverse_hazard.
        """
        import torch

        with torch.no_grad():
            temporal_tensor = torch.tensor(temporal_window, dtype=torch.float32).unsqueeze(0)
            depth_tensor = torch.tensor(depth_grid, dtype=torch.float32).unsqueeze(0)
            output = self.model(temporal_tensor, depth_tensor)

        return {
            "execution_probability": float(output["execution_probability"]),
            "expected_alpha_bps": float(output["expected_alpha_bps"]),
            "adverse_hazard": float(output["adverse_hazard"]),
        }


@app.function(
    image=image,
    secrets=[modal.Secret.from_name("arbitrage-secrets")],
)
@modal.asgi_app()
def fastapi_app():
    """Serve the FastAPI gateway (backend/api/main.py) as a Modal ASGI app."""
    from backend.api.main import app as web_app

    return web_app
