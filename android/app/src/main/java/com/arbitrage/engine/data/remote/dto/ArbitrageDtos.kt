package com.arbitrage.engine.data.remote.dto

import com.arbitrage.engine.domain.model.ExecutionStatus
import com.arbitrage.engine.domain.model.PortfolioBalance
import com.arbitrage.engine.domain.model.TradeExecutionResult
import com.arbitrage.engine.domain.model.TradeSignalRequest
import com.arbitrage.engine.domain.model.TradingMode
import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable

/**
 * Wire-format DTOs mirroring backend/api/contracts.py and backend/schemas.py.
 * Field names are snake_case to match the FastAPI/Pydantic JSON payloads
 * (Pydantic uses each model's declared field name verbatim, no camelCase
 * aliasing on the backend). Keep in sync with those files.
 *
 * The domain layer (domain/model/Contracts.kt) stays free of serialization
 * annotations and backend wire-format concerns; mapping happens only here.
 */

@Serializable
enum class TradingModeDto {
    @SerialName("testnet") TESTNET,
    @SerialName("live") LIVE
}

@Serializable
enum class ExecutionStatusDto {
    SUCCESS, PARTIAL_FILL, HEDGED, REJECTED
}

@Serializable
data class TradeSignalRequestDto(
    @SerialName("user_id") val userId: String,
    @SerialName("symbol") val symbol: String = "BTC/USDT",
    @SerialName("exchange_buy") val exchangeBuy: String,
    @SerialName("exchange_sell") val exchangeSell: String,
    @SerialName("capital_allocation_usd") val capitalAllocationUsd: Double,
    @SerialName("min_alpha_bps") val minAlphaBps: Double = 15.0,
    @SerialName("trading_mode") val tradingMode: TradingModeDto = TradingModeDto.TESTNET
)

@Serializable
data class TradeSignalResponseDto(
    @SerialName("status") val status: String,
    @SerialName("reason") val reason: String? = null,
    @SerialName("metrics") val metrics: Map<String, Double> = emptyMap(),
    @SerialName("allocated_capital") val allocatedCapital: Double? = null,
    @SerialName("target_pair") val targetPair: String? = null,
    // Populated when the backend was able to dispatch/settle an execution;
    // absent for a purely rejected signal (status == "SIGNAL_REJECTED").
    @SerialName("execution") val execution: TradeExecutionResultDto? = null
)

@Serializable
data class TradeExecutionResultDto(
    @SerialName("status") val status: ExecutionStatusDto,
    @SerialName("buy_exchange") val buyExchange: String,
    @SerialName("sell_exchange") val sellExchange: String,
    @SerialName("symbol") val symbol: String,
    @SerialName("executed_volume_usd") val executedVolumeUsd: Double,
    @SerialName("gross_spread_pct") val grossSpreadPct: Double,
    @SerialName("net_spread_pct") val netSpreadPct: Double,
    @SerialName("realized_pnl_usd") val realizedPnlUsd: Double,
    @SerialName("ml_confidence_score") val mlConfidenceScore: Double,
    @SerialName("reason") val reason: String? = null
)

@Serializable
data class PortfolioBalanceDto(
    @SerialName("exchange") val exchange: String,
    @SerialName("asset") val asset: String,
    @SerialName("free") val free: Double,
    @SerialName("locked") val locked: Double
)

// --- Domain <-> DTO mappers -------------------------------------------------

fun TradingMode.toDto(): TradingModeDto = when (this) {
    TradingMode.TESTNET -> TradingModeDto.TESTNET
    TradingMode.LIVE -> TradingModeDto.LIVE
}

fun TradeSignalRequest.toDto(): TradeSignalRequestDto = TradeSignalRequestDto(
    userId = userId,
    symbol = symbol,
    exchangeBuy = exchangeBuy,
    exchangeSell = exchangeSell,
    capitalAllocationUsd = capitalAllocationUsd,
    minAlphaBps = minAlphaBps,
    tradingMode = tradingMode.toDto()
)

fun ExecutionStatusDto.toDomain(): ExecutionStatus = when (this) {
    ExecutionStatusDto.SUCCESS -> ExecutionStatus.SUCCESS
    ExecutionStatusDto.PARTIAL_FILL -> ExecutionStatus.PARTIAL_FILL
    ExecutionStatusDto.HEDGED -> ExecutionStatus.HEDGED
    ExecutionStatusDto.REJECTED -> ExecutionStatus.REJECTED
}

fun TradeExecutionResultDto.toDomain(): TradeExecutionResult = TradeExecutionResult(
    status = status.toDomain(),
    buyExchange = buyExchange,
    sellExchange = sellExchange,
    symbol = symbol,
    executedVolumeUsd = executedVolumeUsd,
    grossSpreadPct = grossSpreadPct,
    netSpreadPct = netSpreadPct,
    realizedPnlUsd = realizedPnlUsd,
    mlConfidenceScore = mlConfidenceScore,
    reason = reason
)

/**
 * Reduces a [TradeSignalResponseDto] to the domain [TradeExecutionResult].
 * A rejected signal (no [TradeSignalResponseDto.execution]) is surfaced as
 * a synthetic [ExecutionStatus.REJECTED] result carrying the backend's
 * reason, so callers always get a single well-typed outcome.
 */
fun TradeSignalResponseDto.toDomain(requestSymbol: String): TradeExecutionResult {
    execution?.let { return it.toDomain() }
    return TradeExecutionResult(
        status = ExecutionStatus.REJECTED,
        buyExchange = "",
        sellExchange = "",
        symbol = targetPair ?: requestSymbol,
        executedVolumeUsd = 0.0,
        grossSpreadPct = 0.0,
        netSpreadPct = 0.0,
        realizedPnlUsd = 0.0,
        mlConfidenceScore = metrics["execution_probability"] ?: 0.0,
        reason = reason ?: status
    )
}

fun PortfolioBalanceDto.toDomain(): PortfolioBalance = PortfolioBalance(
    exchange = exchange,
    asset = asset,
    free = free,
    locked = locked
)
