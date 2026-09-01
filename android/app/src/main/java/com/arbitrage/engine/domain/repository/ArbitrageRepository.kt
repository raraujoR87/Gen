package com.arbitrage.engine.domain.repository

import com.arbitrage.engine.domain.model.PortfolioBalance
import com.arbitrage.engine.domain.model.TradeExecutionResult
import com.arbitrage.engine.domain.model.TradeSignalRequest
import kotlinx.coroutines.flow.Flow

/**
 * Boundary between the domain layer and the data layer (Ktor/Retrofit + SSE + local
 * persistence). Implemented by `data/repository/ArbitrageRepositoryImpl.kt`.
 *
 * NOTE: this interface is shared across parallel work units — keep its signatures
 * stable to avoid merge conflicts with the data-layer implementation.
 */
interface ArbitrageRepository {

    /**
     * Submits [req] for model evaluation and, if the backend's risk gates
     * pass, concurrent dispatch of the arbitrage legs. Suspends until the
     * backend returns a final outcome (including a rejected signal, which
     * is surfaced as [TradeExecutionResult] with a REJECTED status rather
     * than as an exception).
     */
    suspend fun evaluateAndExecute(req: TradeSignalRequest): TradeExecutionResult

    /** Live portfolio balance updates (free/locked per exchange+asset) for the current user. */
    fun streamTelemetry(): Flow<PortfolioBalance>

    /** Live bot/kill-switch status messages for the current user. */
    fun streamBotStatus(): Flow<String>

    /**
     * Engages/disengages the remote kill switch, halting/resuming trade execution.
     */
    suspend fun setKillSwitch(engaged: Boolean)
}
