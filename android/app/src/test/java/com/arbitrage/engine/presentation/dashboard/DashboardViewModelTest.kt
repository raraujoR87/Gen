package com.arbitrage.engine.presentation.dashboard

import com.arbitrage.engine.domain.model.PortfolioBalance
import com.arbitrage.engine.domain.model.TradeExecutionResult
import com.arbitrage.engine.domain.model.TradeSignalRequest
import com.arbitrage.engine.domain.repository.ArbitrageRepository
import com.arbitrage.engine.domain.usecase.StreamTelemetryUseCase
import com.arbitrage.engine.domain.usecase.ToggleKillSwitchUseCase
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.flow
import kotlinx.coroutines.flow.flowOf
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.runTest
import kotlinx.coroutines.test.setMain
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test

@OptIn(ExperimentalCoroutinesApi::class)
class DashboardViewModelTest {

    private val testDispatcher = StandardTestDispatcher()

    @Before
    fun setUp() {
        Dispatchers.setMain(testDispatcher)
    }

    @After
    fun tearDown() {
        Dispatchers.resetMain()
    }

    private class FakeArbitrageRepository(
        private val balances: Flow<PortfolioBalance> = flowOf(),
        var killSwitchResult: Result<Unit> = Result.success(Unit)
    ) : ArbitrageRepository {

        var lastKillSwitchArg: Boolean? = null

        override suspend fun evaluateAndExecute(req: TradeSignalRequest): TradeExecutionResult =
            error("not exercised by these tests")

        override fun streamTelemetry(): Flow<PortfolioBalance> = balances

        override fun streamBotStatus(): Flow<String> = flowOf()

        override suspend fun setKillSwitch(engaged: Boolean) {
            lastKillSwitchArg = engaged
            killSwitchResult.getOrThrow()
        }
    }

    private fun balance(exchange: String) = PortfolioBalance(
        exchange = exchange,
        asset = "USDT",
        free = 100.0,
        locked = 0.0
    )

    // Zero backoff delay so failure-path tests resolve on the first attempt
    // under the virtual test dispatcher without needing extra scheduler steps.
    private fun noRetryTelemetryUseCase(repository: ArbitrageRepository) =
        StreamTelemetryUseCase(repository, initialDelayMs = 0L, maxDelayMs = 0L, maxAttempts = 0)

    @Test
    fun `initial state is loading`() = runTest {
        val repository = FakeArbitrageRepository(balances = flow { /* never emits */ })
        val viewModel = DashboardViewModel(
            noRetryTelemetryUseCase(repository),
            ToggleKillSwitchUseCase(repository)
        )

        assertTrue(viewModel.uiState.value.isLoading)
    }

    @Test
    fun `telemetry emission updates active exchanges and clears loading`() = runTest {
        val repository = FakeArbitrageRepository(
            balances = flow {
                emit(balance("binance"))
                emit(balance("bybit"))
            }
        )
        val viewModel = DashboardViewModel(
            noRetryTelemetryUseCase(repository),
            ToggleKillSwitchUseCase(repository)
        )

        testDispatcher.scheduler.advanceUntilIdle()

        val state = viewModel.uiState.value
        assertFalse(state.isLoading)
        assertEquals(listOf("binance", "bybit"), state.activeExchanges)
    }

    @Test
    fun `telemetry failure surfaces an error message and clears loading`() = runTest {
        val repository = FakeArbitrageRepository(
            balances = flow { throw IllegalStateException("stream broken") }
        )
        val viewModel = DashboardViewModel(
            noRetryTelemetryUseCase(repository),
            ToggleKillSwitchUseCase(repository)
        )

        testDispatcher.scheduler.advanceUntilIdle()

        val state = viewModel.uiState.value
        assertFalse(state.isLoading)
        assertEquals("stream broken", state.errorMessage)
    }

    @Test
    fun `onToggleBot true disengages the kill switch and flips isBotActive on success`() = runTest {
        val repository = FakeArbitrageRepository(balances = flowOf(), killSwitchResult = Result.success(Unit))
        val viewModel = DashboardViewModel(
            noRetryTelemetryUseCase(repository),
            ToggleKillSwitchUseCase(repository)
        )
        testDispatcher.scheduler.advanceUntilIdle()

        viewModel.onToggleBot(true)
        testDispatcher.scheduler.advanceUntilIdle()

        assertEquals(false, repository.lastKillSwitchArg) // active=true -> engaged=false
        assertTrue(viewModel.uiState.value.isBotActive)
        assertFalse(viewModel.uiState.value.isTogglingBot)
    }

    @Test
    fun `onToggleBot surfaces an error and does not flip state on failure`() = runTest {
        val repository = FakeArbitrageRepository(
            balances = flowOf(),
            killSwitchResult = Result.failure(IllegalStateException("kill switch rejected"))
        )
        val viewModel = DashboardViewModel(
            noRetryTelemetryUseCase(repository),
            ToggleKillSwitchUseCase(repository)
        )
        testDispatcher.scheduler.advanceUntilIdle()

        viewModel.onToggleBot(true)
        testDispatcher.scheduler.advanceUntilIdle()

        val state = viewModel.uiState.value
        assertFalse(state.isBotActive)
        assertFalse(state.isTogglingBot)
        assertEquals("kill switch rejected", state.errorMessage)
    }

    @Test
    fun `dismissError clears the error message`() = runTest {
        val repository = FakeArbitrageRepository(balances = flow { throw RuntimeException("boom") })
        val viewModel = DashboardViewModel(
            noRetryTelemetryUseCase(repository),
            ToggleKillSwitchUseCase(repository)
        )
        testDispatcher.scheduler.advanceUntilIdle()

        assertEquals("boom", viewModel.uiState.value.errorMessage)
        viewModel.dismissError()
        assertEquals(null, viewModel.uiState.value.errorMessage)
    }
}
