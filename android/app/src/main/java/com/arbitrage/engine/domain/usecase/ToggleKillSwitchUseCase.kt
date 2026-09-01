package com.arbitrage.engine.domain.usecase

import com.arbitrage.engine.domain.repository.ArbitrageRepository

/**
 * Engages or disengages the remote kill switch (mirrors [com.arbitrage.engine.domain.model.RiskLimits.killSwitchEngaged]).
 * When engaged, [ExecuteTradeUseCase] also rejects new trades locally before ever
 * reaching the network.
 */
class ToggleKillSwitchUseCase(
    private val repository: ArbitrageRepository
) {

    suspend operator fun invoke(engaged: Boolean): Result<Unit> =
        runCatching { repository.setKillSwitch(engaged) }
}
