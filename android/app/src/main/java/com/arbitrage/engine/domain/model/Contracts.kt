package com.arbitrage.engine.domain.model

/**
 * Shared domain models — the Kotlin mirror of backend/schemas.py and
 * backend/api/contracts.py. Keep field names/types in sync with those files.
 */

enum class TradingMode { TESTNET, LIVE }

enum class ExecutionStatus { SUCCESS, PARTIAL_FILL, HEDGED, REJECTED }

data class ArbitrageSignal(
    val executionProbability: Double,
    val expectedAlphaBps: Double,
    val adverseHazard: Double
)

data class RiskLimits(
    val minAlphaBps: Double = 15.0,
    val minExecutionProbability: Double = 0.85,
    val maxAdverseHazard: Double = 0.20,
    val maxNotionalUsdPerTrade: Double = 50.0,
    val maxDailyNotionalUsd: Double = 500.0,
    val killSwitchEngaged: Boolean = false
)

data class PortfolioBalance(
    val exchange: String,
    val asset: String,
    val free: Double,
    val locked: Double
)

data class TradeExecutionResult(
    val status: ExecutionStatus,
    val buyExchange: String,
    val sellExchange: String,
    val symbol: String,
    val executedVolumeUsd: Double,
    val grossSpreadPct: Double,
    val netSpreadPct: Double,
    val realizedPnlUsd: Double,
    val mlConfidenceScore: Double,
    val reason: String? = null
)

data class TradeSignalRequest(
    val userId: String,
    val symbol: String = "BTC/USDT",
    val exchangeBuy: String,
    val exchangeSell: String,
    val capitalAllocationUsd: Double,
    val minAlphaBps: Double = 15.0,
    val tradingMode: TradingMode = TradingMode.TESTNET
)
