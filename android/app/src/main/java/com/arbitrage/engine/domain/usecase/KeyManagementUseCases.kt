package com.arbitrage.engine.domain.usecase

/**
 * Minimal use-case contracts for exchange API key onboarding, consumed by
 * `presentation.keys`. Compile-only stub — see the note in UseCases.kt.
 * Unit 8 owns the real validation logic (calling the exchange, checking that
 * withdrawal permissions are disabled, encrypting via the Android Keystore, etc.)
 * and the persistence in `data/repository`.
 */

/** Supported exchanges for API key onboarding. */
enum class SupportedExchange {
    BINANCE, BYBIT, OKX, KRAKEN, MERCADO_BITCOIN
}

data class ExchangeKeyInput(
    val exchange: SupportedExchange,
    val apiKey: String,
    val apiSecret: String
)

enum class KeyValidationError {
    INVALID_CREDENTIALS,
    WITHDRAWAL_PERMISSION_ENABLED,
    NETWORK_ERROR,
    UNKNOWN
}

/**
 * Validates an API key/secret pair against the exchange (confirming withdrawal
 * is disabled and the key has at least spot-trading + read permissions), then
 * persists it encrypted if valid.
 */
interface ValidateAndSaveExchangeKeyUseCase {
    suspend operator fun invoke(input: ExchangeKeyInput): Result<Unit>
}

/** Lists the exchanges the user has already onboarded (masked, no raw secrets). */
interface GetSavedExchangeKeysUseCase {
    suspend operator fun invoke(): Result<List<SupportedExchange>>
}
