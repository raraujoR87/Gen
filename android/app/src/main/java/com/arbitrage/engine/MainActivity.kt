package com.arbitrage.engine

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.viewModels
import androidx.lifecycle.ViewModel
import androidx.lifecycle.ViewModelProvider
import androidx.lifecycle.viewmodel.CreationExtras
import com.arbitrage.engine.data.local.SecureKeyStore
import com.arbitrage.engine.data.remote.NetworkModule
import com.arbitrage.engine.data.remote.TelemetryStreamClient
import com.arbitrage.engine.data.repository.ArbitrageRepositoryImpl
import com.arbitrage.engine.domain.repository.ArbitrageRepository
import com.arbitrage.engine.domain.usecase.StreamTelemetryUseCase
import com.arbitrage.engine.domain.usecase.ToggleKillSwitchUseCase
import com.arbitrage.engine.presentation.dashboard.DashboardScreen
import com.arbitrage.engine.presentation.dashboard.DashboardViewModel
import com.arbitrage.engine.presentation.theme.ArbitrageEngineTheme

/**
 * TODO before a real deployment: replace with the deployed Modal.com base
 * URL (see DEPLOY.md — `modal deploy modal_app.py` prints it). Left as an
 * obviously-fake placeholder rather than a real-looking URL so it fails
 * loudly instead of silently pointing at nothing.
 */
private const val BACKEND_BASE_URL = "https://replace-with-your-modal-deployment-url.example"

class MainActivity : ComponentActivity() {

    private val viewModel: DashboardViewModel by viewModels {
        DashboardViewModelFactory(applicationContext)
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContent {
            ArbitrageEngineTheme {
                DashboardScreen(viewModel = viewModel)
            }
        }
    }
}

/**
 * Manual composition root: builds the real [ArbitrageRepository] (Retrofit +
 * Ktor SSE/WebSocket + [SecureKeyStore]) and the use cases [DashboardViewModel]
 * needs. No DI framework — the object graph is small enough that adding
 * Hilt/Koin would be more ceremony than it saves.
 */
private class DashboardViewModelFactory(
    private val appContext: android.content.Context
) : ViewModelProvider.Factory {

    override fun <T : ViewModel> create(modelClass: Class<T>, extras: CreationExtras): T {
        val repository: ArbitrageRepository = ArbitrageRepositoryImpl(
            apiService = NetworkModule.createArbitrageApiService(
                baseUrl = BACKEND_BASE_URL,
                loggingEnabled = BuildConfigCompat.DEBUG
            ),
            telemetryClient = TelemetryStreamClient(baseUrl = BACKEND_BASE_URL),
            secureKeyStore = SecureKeyStore(appContext)
        )

        @Suppress("UNCHECKED_CAST")
        return DashboardViewModel(
            streamTelemetryUseCase = StreamTelemetryUseCase(repository),
            toggleKillSwitchUseCase = ToggleKillSwitchUseCase(repository)
        ) as T
    }
}

/**
 * The auto-generated `BuildConfig.DEBUG` field needs the module's
 * `buildFeatures.buildConfig = true` (not enabled here to keep the module
 * lean) — this local constant stands in for it so OkHttp request logging is
 * simply always on for now. Flip to false before a release build if that's
 * too noisy for production logs.
 */
private object BuildConfigCompat {
    const val DEBUG = true
}
