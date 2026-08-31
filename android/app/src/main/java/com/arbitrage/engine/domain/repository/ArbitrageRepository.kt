package com.arbitrage.engine.domain.repository

import com.arbitrage.engine.domain.model.PortfolioBalance
import com.arbitrage.engine.domain.model.TradeExecutionResult
import com.arbitrage.engine.domain.model.TradeSignalRequest
import kotlinx.coroutines.flow.Flow

/**
 * Domain-facing contract for the arbitrage data layer.
 *
 * NOTE: this is a minimal placeholder interface owned by the data-layer
 * unit (unit 7) so `data/repository/ArbitrageRepositoryImpl` and the
 * presentation-layer use cases have something to compile against without
 * blocking on unit 8 (domain use cases). Unit 8 owns `domain/` and may
 * relocate, rename, or extend this interface — coordinate before editing
 * it further.
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
}
