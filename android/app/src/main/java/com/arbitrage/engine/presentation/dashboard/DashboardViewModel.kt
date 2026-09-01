package com.arbitrage.engine.presentation.dashboard

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.arbitrage.engine.domain.usecase.StreamTelemetryUseCase
import com.arbitrage.engine.domain.usecase.ToggleKillSwitchUseCase
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.catch
import kotlinx.coroutines.flow.launchIn
import kotlinx.coroutines.flow.onEach
import kotlinx.coroutines.launch

/** UI state for [DashboardScreen]. */
data class DashboardUiState(
    val pnlDaily: Double = 0.0,
    val winRate: Double = 0.0,
    val activeExchanges: List<String> = emptyList(),
    val isBotActive: Boolean = false,
    val isLoading: Boolean = true,
    val isTogglingBot: Boolean = false,
    val errorMessage: String? = null
)

class DashboardViewModel(
    private val streamTelemetryUseCase: StreamTelemetryUseCase,
    private val toggleKillSwitchUseCase: ToggleKillSwitchUseCase
) : ViewModel() {

    private val _uiState = MutableStateFlow(DashboardUiState())
    val uiState: StateFlow<DashboardUiState> = _uiState.asStateFlow()

    init {
        observeTelemetry()
    }

    private fun observeTelemetry() {
        streamTelemetryUseCase()
            .onEach { snapshot ->
                _uiState.value = _uiState.value.copy(
                    pnlDaily = snapshot.pnlDailyUsd,
                    winRate = snapshot.winRate,
                    activeExchanges = snapshot.activeExchanges,
                    isBotActive = snapshot.isBotActive,
                    isLoading = false,
                    errorMessage = null
                )
            }
            .catch { throwable ->
                _uiState.value = _uiState.value.copy(
                    isLoading = false,
                    errorMessage = throwable.message ?: "Falha ao carregar telemetria."
                )
            }
            .launchIn(viewModelScope)
    }

    /**
     * Toggles the AI trading engine on/off. `active = false` engages the kill
     * switch, halting any new order dispatch; `active = true` disengages it.
     * The engine's [DashboardUiState.isBotActive] only flips once the backend
     * confirms the change — on failure the switch is reverted with an error.
     */
    fun onToggleBot(active: Boolean) {
        viewModelScope.launch {
            _uiState.value = _uiState.value.copy(isTogglingBot = true, errorMessage = null)
            toggleKillSwitchUseCase(engaged = !active)
                .onSuccess {
                    _uiState.value = _uiState.value.copy(
                        isBotActive = active,
                        isTogglingBot = false
                    )
                }
                .onFailure { throwable ->
                    _uiState.value = _uiState.value.copy(
                        isTogglingBot = false,
                        errorMessage = throwable.message ?: "Falha ao alternar o motor de IA."
                    )
                }
        }
    }

    fun dismissError() {
        _uiState.value = _uiState.value.copy(errorMessage = null)
    }
}
