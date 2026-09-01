package com.arbitrage.engine.data.remote

import com.arbitrage.engine.data.remote.dto.PortfolioBalanceDto
import com.arbitrage.engine.data.remote.dto.toDomain
import com.arbitrage.engine.domain.model.PortfolioBalance
import io.ktor.client.HttpClient
import io.ktor.client.plugins.websocket.WebSockets
import io.ktor.client.plugins.websocket.webSocket
import io.ktor.websocket.Frame
import io.ktor.websocket.readText
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.channels.ClosedReceiveChannelException
import kotlinx.coroutines.channels.awaitClose
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.callbackFlow
import kotlinx.coroutines.flow.flowOn
import kotlinx.serialization.json.Json
import okhttp3.OkHttpClient
import okhttp3.Request

/**
 * Real-time telemetry channel to the backend (PnL, live portfolio balances,
 * bot/kill-switch status) — docs/ARCHITECTURE.md sections 1 and 5.
 *
 * Two transports are used because the two telemetry kinds have different
 * delivery semantics on the backend:
 *  - Server-Sent Events (plain OkHttp — see the note below) for one-way
 *    portfolio/PnL push updates (`GET /users/{id}/telemetry/stream`).
 *  - WebSocket (Ktor) for bidirectional bot status (start/pause/kill-switch
 *    acks) (`GET /users/{id}/telemetry/status-ws`).
 *
 * NOTE: portfolio SSE is hand-rolled on OkHttp rather than a Ktor SSE
 * plugin — `io.ktor:ktor-client-sse` is not an artifact that exists on
 * Maven Central/Google's Maven at any version (confirmed against
 * repo.maven.apache.org while diagnosing a real CI build failure); Ktor's
 * client SSE support ships as part of `ktor-client-core` request builders
 * in newer Ktor releases, not as this standalone module name.
 *
 * Reconnection/backoff is intentionally left to the caller (e.g. a
 * ViewModel-scoped supervisor in the presentation layer) — this class just
 * exposes a single attempt as a cold [Flow] that completes/throws when the
 * connection drops.
 */
class TelemetryStreamClient(
    private val baseUrl: String,
    private val okHttpClient: OkHttpClient = OkHttpClient(),
    private val wsClient: HttpClient = defaultWsClient(),
    private val json: Json = Json { ignoreUnknownKeys = true }
) {

    /** Streams live [PortfolioBalance] snapshots (free/locked per exchange+asset) via SSE. */
    fun streamPortfolioTelemetry(userId: String): Flow<PortfolioBalance> = callbackFlow {
        val request = Request.Builder()
            .url("$baseUrl/users/$userId/telemetry/stream")
            .header("Accept", "text/event-stream")
            .build()

        val call = okHttpClient.newCall(request)
        try {
            call.execute().use { response ->
                val body = response.body ?: error("Empty SSE response body")
                val source = body.source()
                while (!source.exhausted()) {
                    val line = source.readUtf8Line() ?: break
                    if (!line.startsWith("data:")) continue
                    val data = line.removePrefix("data:").trim()
                    if (data.isEmpty()) continue
                    val dto = json.decodeFromString(PortfolioBalanceDto.serializer(), data)
                    trySend(dto.toDomain())
                }
            }
        } finally {
            call.cancel()
            close()
        }
        awaitClose { call.cancel() }
    }.flowOn(Dispatchers.IO)

    /** Streams raw bot/kill-switch status messages (e.g. "RUNNING", "KILLED") over a WebSocket. */
    fun streamBotStatus(userId: String): Flow<String> = callbackFlow {
        val url = "$baseUrl/users/$userId/telemetry/status-ws"
        try {
            wsClient.webSocket(urlString = url) {
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

    /** Releases the underlying HTTP clients and their engine resources. */
    fun shutdown() {
        wsClient.close()
        okHttpClient.dispatcher.executorService.shutdown()
    }

    companion object {
        private fun defaultWsClient(): HttpClient = HttpClient {
            install(WebSockets)
        }
    }
}
