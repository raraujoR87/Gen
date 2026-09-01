package com.arbitrage.engine.domain.usecase

import com.arbitrage.engine.domain.model.PortfolioBalance
import com.arbitrage.engine.domain.model.TradeExecutionResult
import com.arbitrage.engine.domain.model.TradeSignalRequest
import kotlinx.coroutines.flow.Flow

/**
 * Minimal use-case contracts consumed by the `presentation` layer.
 *
 * NOTE: This is a compile-only stub. Unit 8 (`domain/usecase` + `data/repository`)
 * owns the real business logic, error handling and wiring of these use cases —
 * do not add business behavior here beyond what presentation needs to build against.
 * Replace this file's bodies (not its public signatures, unless coordinated) once
 * Unit 8 lands its implementation.
 */

/** Snapshot of live account/bot telemetry streamed to the dashboard. */
data class TelemetrySnapshot(
    val pnlDailyUsd: Double,
    val winRate: Double,
    val activeExchanges: List<String>,
    val balances: List<PortfolioBalance>,
    val isBotActive: Boolean
)

/** Submits a trade signal for evaluation/execution by the backend engine. */
interface ExecuteTradeUseCase {
    suspend operator fun invoke(request: TradeSignalRequest): Result<TradeExecutionResult>
}

/** Engages/disengages the global kill switch that halts all live trading. */
interface ToggleKillSwitchUseCase {
    suspend operator fun invoke(engaged: Boolean): Result<Unit>
}

/** Streams live telemetry (P&L, win rate, active exchanges, bot status) for the dashboard. */
interface StreamTelemetryUseCase {
    operator fun invoke(): Flow<TelemetrySnapshot>
}
