package com.arbitrage.engine.domain.usecase

import com.arbitrage.engine.domain.model.ExecutionStatus
import com.arbitrage.engine.domain.model.RiskLimits
import com.arbitrage.engine.domain.model.TradeExecutionResult
import com.arbitrage.engine.domain.model.TradeSignalRequest
import com.arbitrage.engine.domain.repository.ArbitrageRepository

/**
 * Validates a [TradeSignalRequest] against [RiskLimits] on-device — a defensive,
 * client-side mirror of the gate the backend re-applies authoritatively in
 * `process_arbitrage_intent` (see docs/ARCHITECTURE.md section 5):
 *
 *   AlphaLiquido > AlphaMinimo AND P(Alpha) > 0.85 AND Hazard < 0.20
 *
 * The client does not have access to the live spread/probability/hazard estimates
 * that back that inequality (those are computed server-side from live order books),
 * so this use case only enforces the checks it *can* evaluate locally from the
 * request and the configured limits: the kill switch, per-trade notional cap, a
 * sane positive allocation, and that the client is not requesting a weaker alpha
 * floor than policy allows. A request that fails any of these is rejected without
 * ever reaching the network/backend — reducing wasted round-trips and the blast
 * radius of a misconfigured client. The backend remains the source of truth and
 * re-validates independently; this is a UX/defense-in-depth layer, not a
 * replacement for server-side risk checks.
 */
class ExecuteTradeUseCase(
    private val repository: ArbitrageRepository
) {

    suspend operator fun invoke(
        request: TradeSignalRequest,
        riskLimits: RiskLimits
    ): Result<TradeExecutionResult> {
        localRejectionReason(request, riskLimits)?.let { reason ->
            return Result.success(
                TradeExecutionResult(
                    status = ExecutionStatus.REJECTED,
                    buyExchange = request.exchangeBuy,
                    sellExchange = request.exchangeSell,
                    symbol = request.symbol,
                    executedVolumeUsd = 0.0,
                    grossSpreadPct = 0.0,
                    netSpreadPct = 0.0,
                    realizedPnlUsd = 0.0,
                    mlConfidenceScore = 0.0,
                    reason = reason
                )
            )
        }

        return runCatching { repository.evaluateAndExecute(request) }
    }

    /** Returns a human-readable rejection reason, or null if [request] passes local checks. */
    private fun localRejectionReason(request: TradeSignalRequest, limits: RiskLimits): String? = when {
        limits.killSwitchEngaged ->
            "Kill switch is engaged; trade execution is halted."
        request.capitalAllocationUsd <= 0.0 ->
            "capitalAllocationUsd must be positive."
        request.capitalAllocationUsd > limits.maxNotionalUsdPerTrade ->
            "capitalAllocationUsd (${request.capitalAllocationUsd}) exceeds " +
                "maxNotionalUsdPerTrade (${limits.maxNotionalUsdPerTrade})."
        request.minAlphaBps < limits.minAlphaBps ->
            "Requested minAlphaBps (${request.minAlphaBps}) is below the configured floor " +
                "(${limits.minAlphaBps})."
        request.exchangeBuy.isBlank() || request.exchangeSell.isBlank() ->
            "exchangeBuy/exchangeSell must not be blank."
        request.exchangeBuy == request.exchangeSell ->
            "exchangeBuy and exchangeSell must differ."
        else -> null
    }
}
