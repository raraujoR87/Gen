package com.arbitrage.engine.presentation.keys

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Visibility
import androidx.compose.material.icons.filled.VisibilityOff
import androidx.compose.material.icons.filled.WarningAmber
import androidx.compose.material3.Button
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.ExposedDropdownMenuBox
import androidx.compose.material3.ExposedDropdownMenuDefaults
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.ElevatedCard
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Snackbar
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.TopAppBarDefaults
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.text.input.VisualTransformation
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.arbitrage.engine.domain.usecase.SupportedExchange
import com.arbitrage.engine.presentation.theme.ArbitrageEngineTheme
import com.arbitrage.engine.presentation.theme.WarningAmber

/**
 * Onboarding form for a user's exchange API credentials. The key/secret fields
 * are masked by default (toggleable) and nothing is persisted until the backend
 * confirms — via [KeyManagementViewModel.onValidateAndSave] — that the key has
 * withdrawal permission disabled.
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun KeyManagementScreen(
    viewModel: KeyManagementViewModel,
    onSaved: () -> Unit = {},
    modifier: Modifier = Modifier
) {
    val uiState by viewModel.uiState.collectAsStateWithLifecycle()
    val snackbarHostState = remember { SnackbarHostState() }

    LaunchedEffect(uiState.lastEvent) {
        when (val event = uiState.lastEvent) {
            is KeySaveEvent.Success -> {
                snackbarHostState.showSnackbar("Chave validada e salva com sucesso.")
                viewModel.onEventConsumed()
                onSaved()
            }
            is KeySaveEvent.Failure -> {
                snackbarHostState.showSnackbar(event.message)
                viewModel.onEventConsumed()
            }
            null -> Unit
        }
    }

    Scaffold(
        modifier = modifier.fillMaxSize(),
        topBar = {
            TopAppBar(
                title = { Text("Chaves de API") },
                colors = TopAppBarDefaults.topAppBarColors(
                    containerColor = MaterialTheme.colorScheme.surface,
                    titleContentColor = MaterialTheme.colorScheme.onSurface
                )
            )
        },
        snackbarHost = {
            SnackbarHost(snackbarHostState) { data ->
                Snackbar(
                    containerColor = MaterialTheme.colorScheme.surfaceVariant,
                    contentColor = MaterialTheme.colorScheme.onSurfaceVariant
                ) { Text(data.visuals.message) }
            }
        },
        containerColor = MaterialTheme.colorScheme.background
    ) { paddingValues ->
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(paddingValues)
                .padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(16.dp)
        ) {
            SecurityWarningCard()

            ExchangeDropdown(
                selected = uiState.selectedExchange,
                onSelected = viewModel::onExchangeSelected,
                enabled = !uiState.isValidating
            )

            MaskedField(
                label = "API Key",
                value = uiState.apiKey,
                onValueChange = viewModel::onApiKeyChanged,
                enabled = !uiState.isValidating
            )

            MaskedField(
                label = "API Secret",
                value = uiState.apiSecret,
                onValueChange = viewModel::onApiSecretChanged,
                enabled = !uiState.isValidating
            )

            Button(
                onClick = viewModel::onValidateAndSave,
                enabled = uiState.isSaveEnabled,
                modifier = Modifier.fillMaxWidth()
            ) {
                if (uiState.isValidating) {
                    CircularProgressIndicator(
                        modifier = Modifier.size(18.dp),
                        strokeWidth = 2.dp,
                        color = MaterialTheme.colorScheme.onPrimary
                    )
                    Spacer(Modifier.size(8.dp))
                }
                Text(if (uiState.isValidating) "Validando..." else "Validar e Salvar")
            }
        }
    }
}

@Composable
private fun SecurityWarningCard() {
    ElevatedCard(
        modifier = Modifier.fillMaxWidth(),
        colors = CardDefaults.elevatedCardColors(containerColor = MaterialTheme.colorScheme.surfaceVariant)
    ) {
        Row(
            modifier = Modifier.padding(16.dp),
            verticalAlignment = Alignment.Top
        ) {
            Icon(
                imageVector = Icons.Filled.WarningAmber,
                contentDescription = null,
                tint = WarningAmber
            )
            Spacer(Modifier.size(12.dp))
            Text(
                text = "Sua chave de API DEVE ter o saque (withdrawal) desabilitado na " +
                    "exchange. Habilite apenas permissões de Spot Trading e leitura de " +
                    "saldo. Nunca informe uma chave com permissão de saque.",
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onSurface
            )
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun ExchangeDropdown(
    selected: SupportedExchange,
    onSelected: (SupportedExchange) -> Unit,
    enabled: Boolean = true
) {
    var expanded by remember { mutableStateOf(false) }

    ExposedDropdownMenuBox(
        expanded = expanded && enabled,
        onExpandedChange = { if (enabled) expanded = it }
    ) {
        OutlinedTextField(
            modifier = Modifier
                .fillMaxWidth()
                .menuAnchor(),
            readOnly = true,
            enabled = enabled,
            value = selected.displayName(),
            onValueChange = {},
            label = { Text("Exchange") },
            trailingIcon = { ExposedDropdownMenuDefaults.TrailingIcon(expanded = expanded) },
            colors = ExposedDropdownMenuDefaults.outlinedTextFieldColors()
        )
        DropdownMenu(
            expanded = expanded,
            onDismissRequest = { expanded = false }
        ) {
            SupportedExchange.entries.forEach { exchange ->
                DropdownMenuItem(
                    text = { Text(exchange.displayName()) },
                    onClick = {
                        onSelected(exchange)
                        expanded = false
                    }
                )
            }
        }
    }
}

@Composable
private fun MaskedField(
    label: String,
    value: String,
    onValueChange: (String) -> Unit,
    enabled: Boolean = true
) {
    var isVisible by rememberSaveable { mutableStateOf(false) }

    OutlinedTextField(
        value = value,
        onValueChange = onValueChange,
        modifier = Modifier.fillMaxWidth(),
        label = { Text(label) },
        singleLine = true,
        enabled = enabled,
        keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Password),
        visualTransformation = if (isVisible) VisualTransformation.None else PasswordVisualTransformation(),
        trailingIcon = {
            IconButton(onClick = { isVisible = !isVisible }) {
                Icon(
                    imageVector = if (isVisible) Icons.Filled.VisibilityOff else Icons.Filled.Visibility,
                    contentDescription = if (isVisible) "Ocultar $label" else "Mostrar $label"
                )
            }
        }
    )
}

private fun SupportedExchange.displayName(): String = when (this) {
    SupportedExchange.BINANCE -> "Binance"
    SupportedExchange.BYBIT -> "Bybit"
    SupportedExchange.OKX -> "OKX"
    SupportedExchange.KRAKEN -> "Kraken"
    SupportedExchange.MERCADO_BITCOIN -> "Mercado Bitcoin"
}
