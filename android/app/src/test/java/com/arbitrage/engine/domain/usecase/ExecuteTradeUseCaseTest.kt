package com.arbitrage.engine.domain.usecase

import com.arbitrage.engine.domain.model.ExecutionStatus
import com.arbitrage.engine.domain.model.PortfolioBalance
import com.arbitrage.engine.domain.model.RiskLimits
import com.arbitrage.engine.domain.model.TradeExecutionResult
import com.arbitrage.engine.domain.model.TradeSignalRequest
import com.arbitrage.engine.domain.model.TradingMode
import com.arbitrage.engine.domain.repository.ArbitrageRepository
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertTrue
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.flowOf
import kotlinx.coroutines.test.runTest
import org.junit.Test

/**
 * Fake [ArbitrageRepository] that records whether [evaluateAndExecute] was invoked
 * and returns/throws a canned result, so tests can assert the local risk gate short
 * circuits before the repository is ever reached.
 */
private class FakeArbitrageRepository(
    private val result: TradeExecutionResult? = null,
    private val failure: Throwable? = null
) : ArbitrageRepository {

    var evaluateAndExecuteCallCount = 0
        private set

    override suspend fun evaluateAndExecute(req: TradeSignalRequest): TradeExecutionResult {
        evaluateAndExecuteCallCount++
        failure?.let { throw it }
        return result ?: error("FakeArbitrageRepository: no result configured")
    }

    override fun streamTelemetry(): Flow<PortfolioBalance> = flowOf()

    override suspend fun setKillSwitch(engaged: Boolean) = Unit
}

class ExecuteTradeUseCaseTest {

    private val riskLimits = RiskLimits(
        minAlphaBps = 15.0,
        minExecutionProbability = 0.85,
        maxAdverseHazard = 0.20,
        maxNotionalUsdPerTrade = 50.0,
        maxDailyNotionalUsd = 500.0,
        killSwitchEngaged = false
    )

    private fun validRequest(capitalAllocationUsd: Double = 25.0) = TradeSignalRequest(
        userId = "user-1",
        symbol = "BTC/USDT",
        exchangeBuy = "binance",
        exchangeSell = "kraken",
        capitalAllocationUsd = capitalAllocationUsd,
        minAlphaBps = 15.0,
        tradingMode = TradingMode.TESTNET
    )

    @Test
    fun `request within limits succeeds via repository`() = runTest {
        val expected = TradeExecutionResult(
            status = ExecutionStatus.SUCCESS,
            buyExchange = "binance",
            sellExchange = "kraken",
            symbol = "BTC/USDT",
            executedVolumeUsd = 25.0,
            grossSpreadPct = 0.5,
            netSpreadPct = 0.3,
            realizedPnlUsd = 0.075,
            mlConfidenceScore = 0.91
        )
        val repository = FakeArbitrageRepository(result = expected)
        val useCase = ExecuteTradeUseCase(repository)

        val result = useCase(validRequest(), riskLimits)

        assertTrue(result.isSuccess)
        assertEquals(expected, result.getOrNull())
        assertEquals(1, repository.evaluateAndExecuteCallCount)
    }

    @Test
    fun `request violating maxNotionalUsdPerTrade is rejected locally without calling repository`() = runTest {
        val repository = FakeArbitrageRepository()
        val useCase = ExecuteTradeUseCase(repository)

        val result = useCase(validRequest(capitalAllocationUsd = 100.0), riskLimits)

        assertTrue(result.isSuccess)
        val execution = result.getOrNull()
        assertEquals(ExecutionStatus.REJECTED, execution?.status)
        assertTrue(execution?.reason?.contains("maxNotionalUsdPerTrade") == true)
        assertEquals(0, repository.evaluateAndExecuteCallCount)
    }

    @Test
    fun `request is rejected locally when kill switch is engaged`() = runTest {
        val repository = FakeArbitrageRepository()
        val useCase = ExecuteTradeUseCase(repository)

        val result = useCase(validRequest(), riskLimits.copy(killSwitchEngaged = true))

        assertTrue(result.isSuccess)
        assertEquals(ExecutionStatus.REJECTED, result.getOrNull()?.status)
        assertEquals(0, repository.evaluateAndExecuteCallCount)
    }

    @Test
    fun `repository error is propagated as Result failure`() = runTest {
        val boom = IllegalStateException("network unreachable")
        val repository = FakeArbitrageRepository(failure = boom)
        val useCase = ExecuteTradeUseCase(repository)

        val result = useCase(validRequest(), riskLimits)

        assertFalse(result.isSuccess)
        assertEquals(boom, result.exceptionOrNull())
        assertEquals(1, repository.evaluateAndExecuteCallCount)
    }
}
