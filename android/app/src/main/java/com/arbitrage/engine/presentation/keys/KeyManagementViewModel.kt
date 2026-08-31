package com.arbitrage.engine.presentation.keys

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.arbitrage.engine.domain.usecase.ExchangeKeyInput
import com.arbitrage.engine.domain.usecase.SupportedExchange
import com.arbitrage.engine.domain.usecase.ValidateAndSaveExchangeKeyUseCase
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch

/** Result of the last "Validar e Salvar" attempt, surfaced as a one-shot UI event. */
sealed interface KeySaveEvent {
    data object Success : KeySaveEvent
    data class Failure(val message: String) : KeySaveEvent
}

data class KeyManagementUiState(
    val selectedExchange: SupportedExchange = SupportedExchange.BINANCE,
    val apiKey: String = "",
    val apiSecret: String = "",
    val isValidating: Boolean = false,
    val lastEvent: KeySaveEvent? = null
) {
    /** Form is submittable only once both fields are non-blank. */
    val isSaveEnabled: Boolean
        get() = apiKey.isNotBlank() && apiSecret.isNotBlank() && !isValidating
}

class KeyManagementViewModel(
    private val validateAndSaveExchangeKeyUseCase: ValidateAndSaveExchangeKeyUseCase
) : ViewModel() {

    private val _uiState = MutableStateFlow(KeyManagementUiState())
    val uiState: StateFlow<KeyManagementUiState> = _uiState.asStateFlow()

    fun onExchangeSelected(exchange: SupportedExchange) {
        _uiState.value = _uiState.value.copy(selectedExchange = exchange)
    }

    fun onApiKeyChanged(value: String) {
        _uiState.value = _uiState.value.copy(apiKey = value)
    }

    fun onApiSecretChanged(value: String) {
        _uiState.value = _uiState.value.copy(apiSecret = value)
    }

    /** Triggers remote validation (withdrawal permission check, credential check) then saves. */
    fun onValidateAndSave() {
        val state = _uiState.value
        if (!state.isSaveEnabled) return

        viewModelScope.launch {
            _uiState.value = state.copy(isValidating = true, lastEvent = null)
            val input = ExchangeKeyInput(
                exchange = state.selectedExchange,
                apiKey = state.apiKey,
                apiSecret = state.apiSecret
            )
            validateAndSaveExchangeKeyUseCase(input)
                .onSuccess {
                    _uiState.value = KeyManagementUiState(
                        selectedExchange = _uiState.value.selectedExchange,
                        lastEvent = KeySaveEvent.Success
                    )
                }
                .onFailure { throwable ->
                    _uiState.value = _uiState.value.copy(
                        isValidating = false,
                        lastEvent = KeySaveEvent.Failure(
                            throwable.message ?: "Falha ao validar as credenciais."
                        )
                    )
                }
        }
    }

    fun onEventConsumed() {
        _uiState.value = _uiState.value.copy(lastEvent = null)
    }
}
