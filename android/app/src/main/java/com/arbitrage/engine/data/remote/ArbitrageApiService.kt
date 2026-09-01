package com.arbitrage.engine.data.remote

import com.arbitrage.engine.data.remote.dto.PortfolioBalanceDto
import com.arbitrage.engine.data.remote.dto.TradeSignalRequestDto
import com.arbitrage.engine.data.remote.dto.TradeSignalResponseDto
import retrofit2.http.Body
import retrofit2.http.GET
import retrofit2.http.POST
import retrofit2.http.Path

/**
 * REST surface of the FastAPI gateway on Modal.com (docs/ARCHITECTURE.md
 * sections 1 and 6). Endpoints mirror backend/api/contracts.py.
 *
 * The base URL (Modal deployment endpoint) is supplied by the DI/build
 * config that constructs the Retrofit instance — not hardcoded here.
 */
interface ArbitrageApiService {

    /**
     * Submits a candidate arbitrage intent for evaluation by the bimodal
     * model and, if the risk thresholds (P(Alpha) > 0.85, Hazard < 0.20,
     * AlphaLiquido > AlphaMinimo) are satisfied, concurrent dispatch of the
     * hedge legs. Mirrors POST /process_arbitrage_intent.
     */
    @POST("process_arbitrage_intent")
    suspend fun processArbitrageIntent(
        @Body request: TradeSignalRequestDto
    ): TradeSignalResponseDto

    /** Current free/locked balances per exchange/asset for the authenticated user. */
    @GET("users/{userId}/balances")
    suspend fun getPortfolioBalances(
        @Path("userId") userId: String
    ): List<PortfolioBalanceDto>

    /** Paginated execution history for the authenticated user (arbitrage_executions table). */
    @GET("users/{userId}/executions")
    suspend fun getExecutionHistory(
        @Path("userId") userId: String
    ): List<TradeSignalResponseDto>

    /**
     * Engages/disengages the user's remote kill switch (RiskLimits.kill_switch_engaged),
     * halting or resuming trade execution server-side.
     */
    @POST("users/{userId}/kill-switch")
    suspend fun setKillSwitch(
        @Path("userId") userId: String,
        @Body engaged: Map<String, Boolean>
    )
}
