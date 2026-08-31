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
     * Sends [req] to the backend `process_arbitrage_intent` endpoint and returns the
     * resulting [TradeExecutionResult]. Throws on network/backend failure — callers
     * (use cases) are expected to wrap this in [kotlin.Result].
     */
    suspend fun evaluateAndExecute(req: TradeSignalRequest): TradeExecutionResult

    /**
     * Live stream of portfolio/exchange balances (backed by SSE or polling in the
     * data layer). May emit an error/terminate on connection loss — callers should
     * handle reconnection.
     */
    fun streamTelemetry(): Flow<PortfolioBalance>

    /**
     * Engages/disengages the remote kill switch, halting/resuming trade execution.
     */
    suspend fun setKillSwitch(engaged: Boolean)
}
