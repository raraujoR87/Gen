package com.arbitrage.engine.domain.usecase

import com.arbitrage.engine.domain.model.PortfolioBalance
import com.arbitrage.engine.domain.repository.ArbitrageRepository
import kotlin.math.pow
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.retryWhen

/**
 * Exposes [ArbitrageRepository.streamTelemetry] as a [Flow] of [PortfolioBalance]
 * updates, with simple exponential backoff reconnection if the underlying stream
 * (SSE/websocket in the data layer) emits an error.
 *
 * Backoff schedule: initialDelayMs * 2^attempt, capped at maxDelayMs, up to
 * maxAttempts retries — after which the failure is allowed to propagate to the
 * collector so the UI can surface a terminal error state.
 */
class StreamTelemetryUseCase(
    private val repository: ArbitrageRepository,
    private val initialDelayMs: Long = 1_000L,
    private val maxDelayMs: Long = 30_000L,
    private val maxAttempts: Int = 5
) {

    operator fun invoke(): Flow<PortfolioBalance> =
        repository.streamTelemetry().retryWhen { _, attempt ->
            if (attempt >= maxAttempts) {
                false
            } else {
                val backoffMs = (initialDelayMs * 2.0.pow(attempt.toInt()))
                    .toLong()
                    .coerceAtMost(maxDelayMs)
                delay(backoffMs)
                true
            }
        }
}
