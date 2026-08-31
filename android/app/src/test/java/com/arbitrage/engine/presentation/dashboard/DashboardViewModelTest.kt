package com.arbitrage.engine.presentation.dashboard

import com.arbitrage.engine.domain.usecase.StreamTelemetryUseCase
import com.arbitrage.engine.domain.usecase.TelemetrySnapshot
import com.arbitrage.engine.domain.usecase.ToggleKillSwitchUseCase
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.flow
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

/**
 * Unit tests for [DashboardViewModel] state transitions, exercised against
 * fake [StreamTelemetryUseCase] / [ToggleKillSwitchUseCase] implementations
 * (no real backend or business logic — that belongs to Unit 8).
 *
 * NOTE: this module could not be compiled/run in this environment — no Android
 * SDK / Gradle wrapper toolchain was available in the sandbox (the repo has no
 * `build.gradle`/wrapper yet at all, pending the Gradle-setup unit). The test
 * is written to standard JUnit4 + kotlinx-coroutines-test conventions used in
 * Android/Compose projects; please run `./gradlew testDebugUnitTest` in an
 * environment with the Android SDK to confirm it passes and compiles once the
 * Gradle module and its test dependencies (junit, kotlinx-coroutines-test) are
 * wired up.
 */
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

    private class FakeStreamTelemetryUseCase(
        private val snapshots: Flow<TelemetrySnapshot>
    ) : StreamTelemetryUseCase {
        override fun invoke(): Flow<TelemetrySnapshot> = snapshots
    }

    private class FakeToggleKillSwitchUseCase(
        var result: Result<Unit> = Result.success(Unit)
    ) : ToggleKillSwitchUseCase {
        var lastEngagedArg: Boolean? = null
        override suspend fun invoke(engaged: Boolean): Result<Unit> {
            lastEngagedArg = engaged
            return result
        }
    }

    private fun snapshot(
        pnl: Double = 100.0,
        winRate: Double = 0.7,
        exchanges: List<String> = listOf("Binance", "Bybit"),
        active: Boolean = false
    ) = TelemetrySnapshot(
        pnlDailyUsd = pnl,
        winRate = winRate,
        activeExchanges = exchanges,
        balances = emptyList(),
        isBotActive = active
    )

    @Test
    fun `initial state is loading`() = runTest {
        val telemetry = FakeStreamTelemetryUseCase(flow { /* never emits */ })
        val toggle = FakeToggleKillSwitchUseCase()
        val viewModel = DashboardViewModel(telemetry, toggle)

        assertTrue(viewModel.uiState.value.isLoading)
    }

    @Test
    fun `telemetry emission updates ui state and clears loading`() = runTest {
        val telemetry = FakeStreamTelemetryUseCase(
            flow { emit(snapshot(pnl = 250.5, winRate = 0.81, active = true)) }
        )
        val toggle = FakeToggleKillSwitchUseCase()
        val viewModel = DashboardViewModel(telemetry, toggle)

        testDispatcher.scheduler.advanceUntilIdle()

        val state = viewModel.uiState.value
        assertFalse(state.isLoading)
        assertEquals(250.5, state.pnlDaily, 0.0001)
        assertEquals(0.81, state.winRate, 0.0001)
        assertEquals(listOf("Binance", "Bybit"), state.activeExchanges)
        assertTrue(state.isBotActive)
    }

    @Test
    fun `telemetry failure surfaces an error message and clears loading`() = runTest {
        val telemetry = FakeStreamTelemetryUseCase(
            flow { throw IllegalStateException("stream broken") }
        )
        val toggle = FakeToggleKillSwitchUseCase()
        val viewModel = DashboardViewModel(telemetry, toggle)

        testDispatcher.scheduler.advanceUntilIdle()

        val state = viewModel.uiState.value
        assertFalse(state.isLoading)
        assertEquals("stream broken", state.errorMessage)
    }

    @Test
    fun `onToggleBot true disengages the kill switch and flips isBotActive on success`() = runTest {
        val telemetry = FakeStreamTelemetryUseCase(flow { emit(snapshot(active = false)) })
        val toggle = FakeToggleKillSwitchUseCase(result = Result.success(Unit))
        val viewModel = DashboardViewModel(telemetry, toggle)
        testDispatcher.scheduler.advanceUntilIdle()

        viewModel.onToggleBot(true)
        testDispatcher.scheduler.advanceUntilIdle()

        assertEquals(false, toggle.lastEngagedArg) // active=true -> engaged=false
        assertTrue(viewModel.uiState.value.isBotActive)
        assertFalse(viewModel.uiState.value.isTogglingBot)
    }

    @Test
    fun `onToggleBot surfaces an error and does not flip state on failure`() = runTest {
        val telemetry = FakeStreamTelemetryUseCase(flow { emit(snapshot(active = false)) })
        val toggle = FakeToggleKillSwitchUseCase(
            result = Result.failure(IllegalStateException("kill switch rejected"))
        )
        val viewModel = DashboardViewModel(telemetry, toggle)
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
        val telemetry = FakeStreamTelemetryUseCase(flow { throw RuntimeException("boom") })
        val toggle = FakeToggleKillSwitchUseCase()
        val viewModel = DashboardViewModel(telemetry, toggle)
        testDispatcher.scheduler.advanceUntilIdle()

        assertEquals("boom", viewModel.uiState.value.errorMessage)
        viewModel.dismissError()
        assertEquals(null, viewModel.uiState.value.errorMessage)
    }
}
