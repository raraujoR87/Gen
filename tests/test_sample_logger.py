"""Tests for backend.marketdata.sample_logger.SampleLogger."""
from __future__ import annotations

import json

from backend.marketdata.sample_logger import SampleLogger
from backend.schemas import DepthMatrix, TemporalFeatures


def test_log_appends_jsonl_record(tmp_path):
    path = tmp_path / "nested" / "samples.jsonl"
    logger = SampleLogger(path)

    temporal = TemporalFeatures(window=[[1.0] * TemporalFeatures.FEATURE_COUNT])
    depth = DepthMatrix(grid=[[2.0] * DepthMatrix.SIZE])

    logger.log(
        symbol="BTC/USDT",
        exchange_buy="binance",
        exchange_sell="kraken",
        temporal=temporal,
        depth=depth,
        net_alpha_bps=12.5,
    )

    assert path.exists()
    lines = path.read_text().splitlines()
    assert len(lines) == 1

    record = json.loads(lines[0])
    assert record["symbol"] == "BTC/USDT"
    assert record["exchange_buy"] == "binance"
    assert record["exchange_sell"] == "kraken"
    assert record["net_alpha_bps"] == 12.5
    assert record["temporal_window"] == temporal.window
    assert record["depth_grid"] == depth.grid
    assert "timestamp" in record


def test_log_appends_multiple_records(tmp_path):
    path = tmp_path / "samples.jsonl"
    logger = SampleLogger(path)
    temporal = TemporalFeatures(window=[[0.0] * TemporalFeatures.FEATURE_COUNT])
    depth = DepthMatrix(grid=[[0.0] * DepthMatrix.SIZE])

    for i in range(3):
        logger.log(
            symbol="BTC/USDT",
            exchange_buy="binance",
            exchange_sell="kraken",
            temporal=temporal,
            depth=depth,
            net_alpha_bps=float(i),
        )

    lines = path.read_text().splitlines()
    assert len(lines) == 3
