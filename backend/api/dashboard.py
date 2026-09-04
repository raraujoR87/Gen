"""Local web dashboard: read-only view over backend.runtime_state.STATE plus
persisted executions, and a kill-switch control endpoint.

This is the interface the user chose over the (deferred) Android app for
this validation phase: a simple `localhost:8000/dashboard` page showing
live signals/executions, polled from a browser — no separate frontend
build, no mobile app, nothing beyond FastAPI serving one HTML page and a
few JSON endpoints.
"""
from __future__ import annotations

import time

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

from backend.db.repository import get_recent_executions
from backend.db.session import AsyncSessionLocal
from backend.runtime_state import STATE
from backend.schemas import RiskLimits

router = APIRouter()

# The runner evaluates every signal against RiskLimits()'s defaults (see
# backend.marketdata.runner.PairMonitor._evaluate_once — it does not
# currently read the MIN_ALPHA_BPS/etc. env vars in .env.example, only the
# HTTP endpoint in backend.api.main does). Exposed here so the dashboard can
# show *why* a signal was rejected against the actual thresholds in effect,
# not just the raw text reason.
_DEFAULT_LIMITS = RiskLimits()


@router.get("/api/config")
async def get_config() -> dict:
    return {
        "min_alpha_bps": _DEFAULT_LIMITS.min_alpha_bps,
        "min_execution_probability": _DEFAULT_LIMITS.min_execution_probability,
        "max_adverse_hazard": _DEFAULT_LIMITS.max_adverse_hazard,
        "max_notional_usd_per_trade": _DEFAULT_LIMITS.max_notional_usd_per_trade,
        "max_daily_notional_usd": _DEFAULT_LIMITS.max_daily_notional_usd,
    }


@router.get("/api/status")
async def get_status() -> dict:
    return {
        "started_at": STATE.started_at,
        "uptime_s": time.time() - STATE.started_at,
        "monitored_pairs": STATE.monitored_pairs,
        "kill_switch_engaged": STATE.kill_switch.engaged,
        "local_user_id": str(STATE.local_user_id) if STATE.local_user_id else None,
        "errors": list(STATE.errors),
        "mode": "paper-trading (real market data, simulated execution)",
    }


@router.get("/api/signals")
async def get_signals(limit: int = 100) -> list[dict]:
    records = list(STATE.signal_history)[-limit:]
    records.reverse()  # newest first
    return [
        {
            "id": r.id,
            "timestamp": r.timestamp,
            "symbol": r.symbol,
            "exchange_buy": r.exchange_buy,
            "exchange_sell": r.exchange_sell,
            "net_alpha_bps": r.net_alpha_bps,
            "execution_probability": r.execution_probability,
            "adverse_hazard": r.adverse_hazard,
            "approved": r.approved,
            "reason": r.reason,
            "execution_status": r.execution_status,
            "realized_pnl_usd": r.realized_pnl_usd,
        }
        for r in records
    ]


@router.get("/api/executions")
async def get_executions(limit: int = 50) -> list[dict]:
    if STATE.local_user_id is None:
        return []
    async with AsyncSessionLocal() as session:
        executions = await get_recent_executions(session, STATE.local_user_id, limit=limit)
    return [
        {
            "id": str(e.id),
            "symbol": e.symbol,
            "buy_exchange": e.buy_exchange,
            "sell_exchange": e.sell_exchange,
            "gross_spread_pct": e.gross_spread_pct,
            "net_spread_pct": e.net_spread_pct,
            "executed_volume_usd": e.executed_volume_usd,
            "realized_pnl_usd": e.realized_pnl_usd,
            "ml_confidence_score": e.ml_confidence_score,
            "execution_status": e.execution_status,
            "executed_at": e.executed_at.isoformat() if e.executed_at else None,
        }
        for e in executions
    ]


@router.post("/api/kill-switch/engage")
async def engage_kill_switch() -> dict:
    STATE.kill_switch.engage()
    return {"kill_switch_engaged": STATE.kill_switch.engaged}


@router.post("/api/kill-switch/disengage")
async def disengage_kill_switch() -> dict:
    STATE.kill_switch.disengage()
    return {"kill_switch_engaged": STATE.kill_switch.engaged}


_DASHBOARD_HTML = """<!doctype html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<title>Arbitragem Bimodal — Paper Trading Local</title>
<style>
  body { font-family: -apple-system, Segoe UI, Roboto, sans-serif; margin: 0; padding: 24px;
         background: #0b0f14; color: #dbe2ea; }
  h1 { font-size: 18px; margin: 0 0 4px; }
  .subtitle { color: #7f8b99; font-size: 13px; margin-bottom: 6px; }
  .explainer { background: #131a22; border: 1px solid #212b36; border-radius: 8px; padding: 12px 16px;
               font-size: 13px; color: #a9b4c0; line-height: 1.5; margin: 14px 0 24px; }
  .explainer b { color: #dbe2ea; }
  .cards { display: flex; gap: 16px; margin-bottom: 16px; flex-wrap: wrap; }
  .card { background: #131a22; border: 1px solid #212b36; border-radius: 8px; padding: 14px 18px; min-width: 160px; }
  .card .label { font-size: 11px; color: #7f8b99; text-transform: uppercase; letter-spacing: .04em; }
  .card .value { font-size: 22px; margin-top: 4px; }
  .card .sub { font-size: 11px; color: #7f8b99; margin-top: 2px; }
  .ok { color: #3fd68c; } .bad { color: #ff5c5c; } .warn { color: #ffb84d; } .muted { color: #7f8b99; }
  .thresholds { display: flex; gap: 16px; margin-bottom: 24px; flex-wrap: wrap; font-size: 12px; color: #a9b4c0; }
  .thresholds .item { background: #101720; border: 1px solid #1b232c; border-radius: 6px; padding: 6px 12px; }
  table { width: 100%; border-collapse: collapse; font-size: 13px; margin-bottom: 28px; }
  th, td { text-align: left; padding: 6px 10px; border-bottom: 1px solid #1b232c; white-space: nowrap; }
  th { color: #7f8b99; font-weight: 500; font-size: 11px; text-transform: uppercase; cursor: help; }
  tr:hover { background: #101720; }
  tr.approved-row { background: rgba(63, 214, 140, 0.06); }
  .approved { color: #3fd68c; font-weight: 600; } .rejected { color: #7f8b99; }
  button { background: #1b232c; color: #dbe2ea; border: 1px solid #2c3a48; border-radius: 6px;
           padding: 6px 14px; cursor: pointer; font-size: 13px; }
  button:hover { background: #24303c; }
  button.danger { border-color: #6b2530; color: #ff8080; }
  section h2 { font-size: 14px; color: #a9b4c0; margin: 0 0 4px; }
  section .hint { font-size: 12px; color: #7f8b99; margin: 0 0 8px; }
  .empty-hint { color: #7f8b99; font-size: 12px; padding: 12px 0; }
  .errors { color: #ff8080; font-size: 12px; white-space: pre-wrap; }
</style>
</head>
<body>
  <h1>Arbitragem Bimodal — Paper Trading Local</h1>
  <div class="subtitle">Dados reais de mercado, execução simulada. Nenhuma ordem real é enviada por esta tela.</div>
  <div class="explainer">
    Este painel mostra, em tempo real, o que o sistema está decidindo com dados de mercado
    <b>reais</b> — mas toda execução é <b>simulada</b> (papel), sem risco financeiro.
    Cada linha da tabela de sinais é uma avaliação: o sistema calcula o spread líquido real entre
    as duas exchanges e decide se valeria a pena executar, comparando com os limites de risco
    configurados. Só é <b>aprovado</b> (e só então simulado) quando passa nos três critérios ao mesmo tempo.
  </div>

  <div class="cards" id="cards"></div>
  <div class="thresholds" id="thresholds"></div>

  <section>
    <h2>Interruptor de emergência (kill switch)</h2>
    <p class="hint">Engatar interrompe imediatamente qualquer nova execução simulada, sem parar o serviço.</p>
    <button id="engage" class="danger">Engatar (parar trading)</button>
    <button id="disengage">Desengatar</button>
  </section>

  <section>
    <h2>Sinais (avaliações ao vivo)</h2>
    <p class="hint">Cada linha é uma checagem real feita nos últimos segundos. Verde = passou nesse critério; vermelho = foi o motivo da reprovação.</p>
    <table id="signals"><thead><tr>
      <th title="Horário da avaliação">Hora</th>
      <th title="Par de moedas monitorado">Par</th>
      <th title="Compra na primeira exchange, venda na segunda">Rota</th>
      <th title="Spread líquido estimado, já descontando taxas — precisa ser maior que o mínimo configurado">Spread líq. (bps)</th>
      <th title="Probabilidade de a oportunidade ainda existir quando a ordem chegar à exchange (persistência real, não aleatória)">P(execução)</th>
      <th title="Risco de o preço virar contra a posição antes de conseguir proteger (hedge) — calculado pela volatilidade real recente">Risco (hazard)</th>
      <th title="Aprovado = passou nos 3 critérios acima ao mesmo tempo">Aprovado?</th>
      <th title="Detalhe técnico do motivo da reprovação">Motivo</th>
      <th title="Resultado da execução simulada, se aprovado">Execução</th>
      <th title="Lucro/prejuízo simulado em USD">PnL</th>
    </tr></thead><tbody></tbody></table>
    <div class="empty-hint" id="signals-empty" hidden>
      Nenhum sinal ainda — aguardando dados suficientes das duas exchanges para começar a avaliar
      (a primeira avaliação leva um tempo, até o histórico de preços encher a janela necessária).
    </div>
  </section>

  <section>
    <h2>Execuções simuladas (persistidas)</h2>
    <p class="hint">Só aparece aqui quando um sinal é aprovado — cada linha é uma ordem simulada de verdade, salva no banco local.</p>
    <table id="executions"><thead><tr>
      <th>Hora</th><th>Símbolo</th><th>Rota</th><th>Notional (USD)</th><th>Spread líq. %</th>
      <th>PnL</th><th>Status</th>
    </tr></thead><tbody></tbody></table>
    <div class="empty-hint" id="executions-empty" hidden>
      Nenhuma execução ainda — normal enquanto nenhum sinal for aprovado (veja a tabela de sinais acima).
    </div>
  </section>

  <div class="errors" id="errors"></div>

<script>
async function j(url, opts) { const r = await fetch(url, opts); return r.json(); }
function fmt(n, d) { return (n === null || n === undefined) ? "-" : Number(n).toFixed(d ?? 2); }
function fmtTime(t) { return new Date(t * 1000).toLocaleTimeString("pt-BR"); }
function passClass(pass) { return pass ? "ok" : "bad"; }

let config = null;

async function refresh() {
  if (!config) config = await j("/api/config");

  const status = await j("/api/status");
  document.getElementById("cards").innerHTML = `
    <div class="card"><div class="label">Kill switch</div>
      <div class="value ${status.kill_switch_engaged ? 'bad' : 'ok'}">${status.kill_switch_engaged ? 'ENGATADO' : 'desligado'}</div></div>
    <div class="card"><div class="label">Tempo ativo</div><div class="value">${Math.floor(status.uptime_s)}s</div></div>
    <div class="card"><div class="label">Pares monitorados</div><div class="value">${status.monitored_pairs.join(', ') || '-'}</div>
      <div class="sub">dados reais de mercado</div></div>
    <div class="card"><div class="label">Modo</div><div class="value" style="font-size:13px">paper-trading</div>
      <div class="sub">execução sempre simulada</div></div>
  `;
  document.getElementById("thresholds").innerHTML = `
    <div class="item">Spread líq. mínimo: <b>${fmt(config.min_alpha_bps)} bps</b></div>
    <div class="item">P(execução) mínima: <b>${fmt(config.min_execution_probability, 2)}</b></div>
    <div class="item">Risco máximo: <b>${fmt(config.max_adverse_hazard, 2)}</b></div>
    <div class="item">Notional máx/trade: <b>US$ ${fmt(config.max_notional_usd_per_trade)}</b></div>
  `;
  document.getElementById("errors").textContent = status.errors.join("\\n");

  const signals = await j("/api/signals?limit=100");
  document.getElementById("signals-empty").hidden = signals.length > 0;
  document.querySelector("#signals tbody").innerHTML = signals.map(s => {
    const alphaOk = s.net_alpha_bps > config.min_alpha_bps;
    const probOk = s.execution_probability > config.min_execution_probability;
    const hazardOk = s.adverse_hazard < config.max_adverse_hazard;
    return `
    <tr class="${s.approved ? 'approved-row' : ''}">
      <td>${fmtTime(s.timestamp)}</td><td>${s.symbol}</td>
      <td>${s.exchange_buy}→${s.exchange_sell}</td>
      <td class="${passClass(alphaOk)}">${fmt(s.net_alpha_bps)}</td>
      <td class="${passClass(probOk)}">${fmt(s.execution_probability, 3)}</td>
      <td class="${passClass(hazardOk)}">${fmt(s.adverse_hazard, 3)}</td>
      <td class="${s.approved ? 'approved' : 'rejected'}">${s.approved ? 'SIM' : 'não'}</td>
      <td class="muted">${s.reason || ''}</td><td>${s.execution_status || '-'}</td>
      <td>${fmt(s.realized_pnl_usd)}</td>
    </tr>`;
  }).join("");

  const executions = await j("/api/executions?limit=50");
  document.getElementById("executions-empty").hidden = executions.length > 0;
  document.querySelector("#executions tbody").innerHTML = executions.map(e => `
    <tr>
      <td>${e.executed_at || ''}</td><td>${e.symbol}</td>
      <td>${e.buy_exchange}→${e.sell_exchange}</td>
      <td>${fmt(e.executed_volume_usd)}</td><td>${fmt(e.net_spread_pct * 100, 3)}</td>
      <td>${fmt(e.realized_pnl_usd)}</td><td>${e.execution_status}</td>
    </tr>`).join("");
}

document.getElementById("engage").onclick = async () => { await j("/api/kill-switch/engage", {method: "POST"}); refresh(); };
document.getElementById("disengage").onclick = async () => { await j("/api/kill-switch/disengage", {method: "POST"}); refresh(); };

refresh();
setInterval(refresh, 2000);
</script>
</body>
</html>
"""


@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard() -> str:
    return _DASHBOARD_HTML
