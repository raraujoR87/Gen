package com.arbitrage.engine.data.repository

import com.arbitrage.engine.data.local.SecureKeyStore
import com.arbitrage.engine.data.remote.ArbitrageApiService
import com.arbitrage.engine.data.remote.TelemetryStreamClient
import com.arbitrage.engine.data.remote.dto.toDomain
import com.arbitrage.engine.data.remote.dto.toDto
import com.arbitrage.engine.domain.model.ExecutionStatus
import com.arbitrage.engine.domain.model.PortfolioBalance
import com.arbitrage.engine.domain.model.TradeExecutionResult
import com.arbitrage.engine.domain.model.TradeSignalRequest
import com.arbitrage.engine.domain.repository.ArbitrageRepository
import java.io.IOException
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.emitAll
import kotlinx.coroutines.flow.flow
import retrofit2.HttpException

/**
 * Default [ArbitrageRepository] implementation wiring the REST gateway
 * ([ArbitrageApiService]) and the real-time telemetry transport
 * ([TelemetryStreamClient]) behind the domain-facing contract.
 *
 * The active user id is read from [SecureKeyStore] rather than passed in
 * per-call, since every telemetry/session-scoped request needs it and the
 * presentation layer should not have to thread it through every use case.
 */
class ArbitrageRepositoryImpl(
    private val apiService: ArbitrageApiService,
    private val telemetryClient: TelemetryStreamClient,
    private val secureKeyStore: SecureKeyStore
) : ArbitrageRepository {

    override suspend fun evaluateAndExecute(req: TradeSignalRequest): TradeExecutionResult {
        return try {
            apiService.processArbitrageIntent(req.toDto()).toDomain(req.symbol)
        } catch (e: HttpException) {
            rejectedResult(req, "HTTP ${e.code()}: ${e.message()}")
        } catch (e: IOException) {
            rejectedResult(req, "Network error: ${e.message ?: e::class.simpleName}")
        }
    }

    override fun streamTelemetry(): Flow<PortfolioBalance> = flow {
        val userId = requireActiveUserId()
        emitAll(telemetryClient.streamPortfolioTelemetry(userId))
    }

    override fun streamBotStatus(): Flow<String> = flow {
        val userId = requireActiveUserId()
        emitAll(telemetryClient.streamBotStatus(userId))
    }

    private fun requireActiveUserId(): String =
        secureKeyStore.readEncrypted(SecureKeyStore.KEY_ACTIVE_USER_ID)
            ?: error("No active user session — cannot stream telemetry without a signed-in user")

    /** A network/transport failure never crashes the caller — it surfaces as a REJECTED result. */
    private fun rejectedResult(req: TradeSignalRequest, reason: String) = TradeExecutionResult(
        status = ExecutionStatus.REJECTED,
        buyExchange = req.exchangeBuy,
        sellExchange = req.exchangeSell,
        symbol = req.symbol,
        executedVolumeUsd = 0.0,
        grossSpreadPct = 0.0,
        netSpreadPct = 0.0,
        realizedPnlUsd = 0.0,
        mlConfidenceScore = 0.0,
        reason = reason
    )
}
