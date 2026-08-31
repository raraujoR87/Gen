package com.arbitrage.engine.data.remote

import com.arbitrage.engine.data.remote.dto.PortfolioBalanceDto
import com.arbitrage.engine.data.remote.dto.toDomain
import com.arbitrage.engine.domain.model.PortfolioBalance
import io.ktor.client.HttpClient
import io.ktor.client.plugins.sse.SSE
import io.ktor.client.plugins.sse.sse
import io.ktor.client.plugins.websocket.WebSockets
import io.ktor.client.plugins.websocket.webSocket
import io.ktor.websocket.Frame
import io.ktor.websocket.readText
import kotlinx.coroutines.channels.ClosedReceiveChannelException
import kotlinx.coroutines.channels.awaitClose
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.callbackFlow
import kotlinx.serialization.json.Json

/**
 * Real-time telemetry channel to the backend (PnL, live portfolio balances,
 * bot/kill-switch status) — docs/ARCHITECTURE.md sections 1 and 5.
 *
 * Two transports are supported because the two telemetry kinds have
 * different delivery semantics on the backend:
 *  - Server-Sent Events for one-way portfolio/PnL push updates
 *    (`GET /users/{id}/telemetry/stream`).
 *  - WebSocket for bidirectional bot status (start/pause/kill-switch acks)
 *    (`GET /users/{id}/telemetry/status-ws`).
 *
 * Reconnection/backoff is intentionally left to the caller (e.g. a
 * ViewModel-scoped supervisor in the presentation layer) — this class just
 * exposes a single attempt as a cold [Flow] that completes/throws when the
 * connection drops.
 */
class TelemetryStreamClient(
    private val baseUrl: String,
    private val client: HttpClient = defaultClient(),
    private val json: Json = Json { ignoreUnknownKeys = true }
) {

    /** Streams live [PortfolioBalance] snapshots (free/locked per exchange+asset) via SSE. */
    fun streamPortfolioTelemetry(userId: String): Flow<PortfolioBalance> = callbackFlow {
        val url = "$baseUrl/users/$userId/telemetry/stream"
        try {
            client.sse(urlString = url) {
                incoming.collect { event ->
                    val data = event.data ?: return@collect
                    val dto = json.decodeFromString(PortfolioBalanceDto.serializer(), data)
                    trySend(dto.toDomain())
                }
            }
        } catch (e: ClosedReceiveChannelException) {
            // Server closed the stream cleanly; let the flow complete.
        } finally {
            close()
        }
        awaitClose { }
    }

    /** Streams raw bot/kill-switch status messages (e.g. "RUNNING", "KILLED") over a WebSocket. */
    fun streamBotStatus(userId: String): Flow<String> = callbackFlow {
        val url = "$baseUrl/users/$userId/telemetry/status-ws"
        try {
            client.webSocket(urlString = url) {
                for (frame in incoming) {
                    if (frame is Frame.Text) {
                        trySend(frame.readText())
                    }
                }
            }
        } catch (e: ClosedReceiveChannelException) {
            // Server closed the socket cleanly; let the flow complete.
        } finally {
            close()
        }
        awaitClose { }
    }

    /** Releases the underlying [HttpClient] and its engine resources. */
    fun shutdown() {
        client.close()
    }

    companion object {
        private fun defaultClient(): HttpClient = HttpClient {
            install(SSE)
            install(WebSockets)
        }
    }
}
