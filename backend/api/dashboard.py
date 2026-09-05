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
            # These columns are SQLAlchemy Numeric (stored as fixed-point
            # strings so SQLite preserves precision), which come back as
            # decimal.Decimal — and Pydantic/FastAPI serializes Decimal to a
            # JSON *string*, not a number. Cast explicitly so the dashboard
            # (and any other consumer) gets real JSON numbers to do
            # arithmetic on, not strings that only look like numbers.
            "gross_spread_pct": float(e.gross_spread_pct),
            "net_spread_pct": float(e.net_spread_pct),
            "executed_volume_usd": float(e.executed_volume_usd),
            "realized_pnl_usd": float(e.realized_pnl_usd),
            "ml_confidence_score": float(e.ml_confidence_score),
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
<title>Arbitragem Bimodal — Live</title>
<style>
  :root {
    --bg: #07040c; --panel: #120a1c; --panel-border: #3a1f4f;
    --pink: #ff2ea6; --pink-dim: #a2286f; --cyan: #38f2d0; --green: #3fe6a0;
    --red: #ff4d6d; --amber: #ffc93f; --text: #f2e9ff; --muted: #9a86b3;
  }
  * { box-sizing: border-box; }
  body {
    font-family: -apple-system, "Segoe UI", Roboto, sans-serif; margin: 0; padding: 20px;
    background: radial-gradient(ellipse at top, #1a0d2b 0%, var(--bg) 60%);
    color: var(--text); min-height: 100vh;
  }
  .topbar { display: flex; align-items: baseline; justify-content: space-between; margin-bottom: 18px; flex-wrap: wrap; gap: 8px; }
  .topbar h1 { font-size: 17px; margin: 0; letter-spacing: .03em; }
  .topbar h1 .accent { color: var(--pink); text-shadow: 0 0 12px var(--pink-dim); }
  .topbar .right { display: flex; align-items: center; gap: 14px; font-size: 12px; color: var(--muted); }
  .pill { padding: 3px 10px; border-radius: 999px; font-size: 11px; font-weight: 600; letter-spacing: .03em; }
  .pill.live { background: rgba(63,230,160,0.12); color: var(--green); border: 1px solid rgba(63,230,160,0.4); }
  .pill.halted { background: rgba(255,77,109,0.12); color: var(--red); border: 1px solid rgba(255,77,109,0.4); }
  .explainer { background: var(--panel); border: 1px solid var(--panel-border); border-radius: 10px;
               padding: 12px 16px; font-size: 12.5px; color: var(--muted); line-height: 1.5; margin-bottom: 18px; }
  .explainer b { color: var(--text); }

  .ticker { overflow: hidden; white-space: nowrap; border: 1px solid var(--panel-border); border-radius: 999px;
            background: var(--panel); margin-bottom: 16px; padding: 8px 0; }
  .ticker-track { display: inline-block; padding-left: 100%; animation: ticker-scroll 30s linear infinite; }
  .ticker:hover .ticker-track { animation-play-state: paused; }
  @keyframes ticker-scroll { from { transform: translateX(0); } to { transform: translateX(-100%); } }
  .ticker-item { display: inline-flex; align-items: center; gap: 6px; padding: 0 22px; font-size: 12.5px; }
  .ticker-item .sym { font-weight: 700; }
  .ticker-item .route { color: var(--muted); font-size: 11px; }

  .stat-row { display: grid; grid-template-columns: repeat(auto-fit, minmax(190px, 1fr)); gap: 14px; margin-bottom: 18px; }
  .stat {
    background: linear-gradient(180deg, var(--panel), #0d0716);
    border: 1px solid var(--panel-border); border-radius: 12px; padding: 16px 18px;
    box-shadow: 0 0 0 1px rgba(255,46,166,0.03) inset;
  }
  .stat .label { font-size: 10.5px; color: var(--muted); text-transform: uppercase; letter-spacing: .08em; }
  .stat .value { font-size: 30px; font-weight: 700; margin-top: 6px; font-variant-numeric: tabular-nums; }
  .stat .value.pink { color: var(--pink); text-shadow: 0 0 18px rgba(255,46,166,0.45); }
  .stat .value.green { color: var(--green); text-shadow: 0 0 18px rgba(63,230,160,0.4); }
  .stat .value.red { color: var(--red); text-shadow: 0 0 18px rgba(255,77,109,0.4); }
  .stat .sub { font-size: 11px; color: var(--muted); margin-top: 4px; }

  .main-grid { display: grid; grid-template-columns: 1.4fr 1fr; gap: 16px; margin-bottom: 16px; }
  @media (max-width: 900px) { .main-grid { grid-template-columns: 1fr; } }
  .panel { background: var(--panel); border: 1px solid var(--panel-border); border-radius: 12px; padding: 16px 18px; }
  .panel h2 { font-size: 12.5px; color: var(--muted); text-transform: uppercase; letter-spacing: .06em; margin: 0 0 10px; font-weight: 600; }
  .panel .hint { font-size: 11.5px; color: var(--muted); margin: -4px 0 10px; }

  #chart-wrap { position: relative; }
  #chart-empty { color: var(--muted); font-size: 12px; text-align: center; padding: 40px 0; }

  #radar { position: relative; height: 240px; overflow: hidden; border-radius: 10px;
           background: radial-gradient(ellipse at 50% 100%, rgba(255,46,166,0.05), transparent 70%); }
  .particle { position: absolute; border-radius: 50%; pointer-events: none; }
  .bubble {
    position: absolute; border-radius: 50%; display: flex; align-items: center; justify-content: center;
    flex-direction: column; text-align: center; transition: all 0.6s ease; cursor: default;
    border: 1px solid rgba(255,255,255,0.15);
  }
  .bubble .pair { font-size: 10px; font-weight: 700; }
  .bubble .val { font-size: 11px; opacity: .85; }
  #radar-empty { color: var(--muted); font-size: 12px; text-align: center; padding: 100px 0 0; }

  .feed { list-style: none; margin: 0; padding: 0; max-height: 220px; overflow-y: auto; }
  .feed li { display: flex; justify-content: space-between; gap: 10px; padding: 7px 0;
             border-bottom: 1px solid rgba(255,255,255,0.05); font-size: 12.5px; }
  .feed li:last-child { border-bottom: none; }
  .feed .route { color: var(--text); }
  .feed .time { color: var(--muted); font-size: 11px; }
  .feed .pnl.green { color: var(--green); font-weight: 600; }
  .feed .pnl.red { color: var(--red); font-weight: 600; }

  .controls { display: flex; gap: 8px; align-items: center; }
  button { background: #1b0f2b; color: var(--text); border: 1px solid var(--panel-border); border-radius: 8px;
           padding: 6px 14px; cursor: pointer; font-size: 12.5px; }
  button:hover { background: #241340; }
  button.danger { border-color: rgba(255,77,109,0.5); color: var(--red); }
  button.danger:hover { background: rgba(255,77,109,0.08); }

  .errors { color: var(--red); font-size: 12px; white-space: pre-wrap; margin-top: 12px; }
</style>
</head>
<body>
  <div class="topbar">
    <h1>Arbitragem <span class="accent">Bimodal</span> — Live</h1>
    <div class="right">
      <span id="clock"></span>
      <span class="pill" id="mode-pill">paper-trading</span>
      <div class="controls">
        <button id="engage" class="danger">Parar</button>
        <button id="disengage">Retomar</button>
      </div>
    </div>
  </div>

  <div class="ticker"><div class="ticker-track" id="ticker"></div></div>

  <div class="explainer">
    Dados de mercado <b>reais</b>, execução sempre <b>simulada</b> — nenhuma ordem real sai daqui.
    No radar, cada ponto brilhante grande é um par monitorado agora (tamanho = magnitude do spread,
    cor = passaria nos critérios de risco); a poeira de pontos menores é o histórico recente de avaliações.
    O gráfico mostra o spread líquido do par mais ativo em velas, com a linha tracejada marcando o mínimo
    exigido para aprovar.
  </div>

  <div class="stat-row" id="stats"></div>

  <div class="panel" style="margin-bottom:16px">
    <h2>Radar de oportunidades</h2>
    <p class="hint">Pontos grandes e brilhantes = pares monitorados agora. Poeira de fundo = avaliações recentes de todos os pares.</p>
    <div id="radar"></div>
    <div id="radar-empty" hidden>Nenhum par avaliado ainda.</div>
  </div>

  <div class="main-grid">
    <div class="panel">
      <h2>Spread líquido ao vivo — <span id="chart-pair-label">-</span></h2>
      <p class="hint">Velas de spread líquido. Linha tracejada = mínimo para aprovar. Vela verde = teve aprovação na janela.</p>
      <div id="chart-wrap">
        <svg id="chart" width="100%" height="220" viewBox="0 0 600 220" preserveAspectRatio="none"></svg>
        <div id="chart-empty" hidden>Aguardando dados suficientes para desenhar o gráfico...</div>
      </div>
    </div>
    <div class="panel">
      <h2>Últimas execuções simuladas</h2>
      <p class="hint">Só aparece aqui quando um sinal é aprovado e a ordem simulada é registrada.</p>
      <ul class="feed" id="feed"></ul>
      <div id="feed-empty" hidden style="color: var(--muted); font-size: 12px; padding: 8px 0;">
        Nenhuma execução ainda — normal enquanto nenhum sinal for aprovado.
      </div>
    </div>
  </div>

  <div class="errors" id="errors"></div>

<script>
async function j(url, opts) { const r = await fetch(url, opts); return r.json(); }
function fmt(n, d) { return (n === null || n === undefined) ? "-" : Number(n).toFixed(d ?? 2); }
function fmtUsd(n) { return (n === null || n === undefined) ? "-" : (n < 0 ? "-$" : "$") + Math.abs(n).toFixed(2); }
function fmtTime(t) { return new Date(t * 1000).toLocaleTimeString("pt-BR"); }
function hashJitter(s, range) {
  let h = 0; for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) | 0;
  return ((h % 1000) / 1000) * range;
}

// Literal hex mirrors of the CSS custom properties in :root — needed
// wherever JS builds a color string dynamically (e.g. appending an alpha
// suffix like `${color}33`), since `var(--x)` is not valid inside such a
// concatenated value the way it is in a plain CSS declaration.
const COLOR = { green: "#3fe6a0", amber: "#ffc93f", red: "#ff4d6d", cyan: "#38f2d0", pinkDim: "#a2286f", muted: "#9a86b3" };

let config = null;

function updateClock() {
  document.getElementById("clock").textContent = new Date().toLocaleTimeString("pt-BR");
}
setInterval(updateClock, 1000);
updateClock();

function pairKey(s) { return s.symbol + "|" + s.exchange_buy + "|" + s.exchange_sell; }

function groupByPair(signals) {
  const groups = {};
  for (const s of signals) (groups[pairKey(s)] ||= []).push(s);
  return groups;
}

// Longest run of consecutive positive-alpha ticks ending at the most
// recent tick (chronological order in), across all monitored pairs —
// a real "streak" computed from actual history, not a vanity counter.
function bestStreak(signals) {
  const groups = groupByPair(signals);
  let best = 0;
  for (const key in groups) {
    const chrono = groups[key].slice().reverse(); // oldest -> newest
    let streak = 0;
    for (let i = chrono.length - 1; i >= 0; i--) {
      if (chrono[i].net_alpha_bps > 0) streak++; else break;
    }
    best = Math.max(best, streak);
  }
  return best;
}

function renderTicker(signals) {
  const groups = groupByPair(signals);
  const latest = Object.values(groups).map(g => g[0]); // signals are newest-first
  const track = document.getElementById("ticker");
  if (!latest.length) { track.innerHTML = "<span class=\\"ticker-item\\">aguardando dados de mercado...</span>"; return; }
  const itemsHtml = latest.map(s => {
    const color = s.approved ? COLOR.green : (s.net_alpha_bps > 0 ? COLOR.amber : COLOR.red);
    return `<span class="ticker-item"><span class="sym">${s.symbol}</span>
      <span class="route">${s.exchange_buy}→${s.exchange_sell}</span>
      <span style="color:${color}">${fmt(s.net_alpha_bps)} bps</span></span>`;
  }).join("");
  // Duplicated once so the CSS marquee loops seamlessly.
  track.innerHTML = itemsHtml + itemsHtml;
}

function renderStats(status, signals, executions) {
  const totalPnl = executions.reduce((acc, e) => acc + (e.realized_pnl_usd || 0), 0);
  const approvedCount = signals.filter(s => s.approved).length;
  const approvalRate = signals.length ? (100 * approvedCount / signals.length) : 0;
  const best = signals.length ? signals.reduce((a, b) => (b.net_alpha_bps > a.net_alpha_bps ? b : a)) : null;
  const streak = bestStreak(signals);

  document.getElementById("stats").innerHTML = `
    <div class="stat">
      <div class="label">PnL simulado</div>
      <div class="value ${totalPnl >= 0 ? 'green' : 'red'}">${fmtUsd(totalPnl)}</div>
      <div class="sub">${executions.length} execução(ões) simulada(s)</div>
    </div>
    <div class="stat">
      <div class="label">Melhor spread agora</div>
      <div class="value pink">${best ? fmt(best.net_alpha_bps) : '-'} bps</div>
      <div class="sub">${best ? best.symbol + ' (' + best.exchange_buy + '→' + best.exchange_sell + ')' : 'aguardando dados'}</div>
    </div>
    <div class="stat">
      <div class="label">Streak (spread positivo)</div>
      <div class="value pink">${streak}</div>
      <div class="sub">ticks seguidos com spread > 0, melhor par</div>
    </div>
    <div class="stat">
      <div class="label">Taxa de aprovação</div>
      <div class="value">${fmt(approvalRate, 1)}%</div>
      <div class="sub">${approvedCount} de ${signals.length} avaliações</div>
    </div>
    <div class="stat">
      <div class="label">Tempo ativo</div>
      <div class="value" style="font-size:22px">${Math.floor(status.uptime_s)}s</div>
      <div class="sub">${status.monitored_pairs.length} par(es) monitorado(s)</div>
    </div>
  `;

  document.getElementById("mode-pill").className = "pill " + (status.kill_switch_engaged ? "halted" : "live");
  document.getElementById("mode-pill").textContent = status.kill_switch_engaged ? "PARADO" : "AO VIVO";
  document.getElementById("errors").textContent = status.errors.join("\\n");
}

function renderRadar(signals) {
  const wrap = document.getElementById("radar");
  document.getElementById("radar-empty").hidden = signals.length > 0;
  wrap.innerHTML = "";
  if (!signals.length) return;

  const w = wrap.clientWidth || 400;
  const h = 240;
  const now = Date.now() / 1000;

  // Background "dust": every recent tick, small and fading with age —
  // this is what gives the radar its density (matches the reference
  // video's particle field) using real evaluation history, not decoration.
  signals.forEach((s) => {
    const age = now - s.timestamp;
    const opacity = Math.max(0.06, 0.5 - age / 40);
    const color = s.approved ? COLOR.green : (s.net_alpha_bps > 0 ? COLOR.amber : COLOR.red);
    const x = hashJitter(s.id, w);
    const y = hashJitter(s.id.split("").reverse().join(""), h);
    const dot = document.createElement("div");
    dot.className = "particle";
    dot.style.width = dot.style.height = "5px";
    dot.style.left = x + "px";
    dot.style.top = y + "px";
    dot.style.background = color;
    dot.style.opacity = opacity;
    wrap.appendChild(dot);
  });

  // Foreground: one bright, labeled bubble per currently-monitored pair.
  const groups = groupByPair(signals);
  const pairs = Object.values(groups).map(g => g[0]); // newest per pair
  const cols = Math.max(1, Math.min(pairs.length, Math.floor(w / 130)));
  pairs.forEach((s, i) => {
    const size = Math.max(46, Math.min(100, 46 + Math.abs(s.net_alpha_bps) * 1.6));
    const color = s.approved ? COLOR.green : (s.net_alpha_bps > 0 ? COLOR.amber : COLOR.red);
    const glow = s.approved ? "rgba(63,230,160,0.5)" : (s.net_alpha_bps > 0 ? "rgba(255,201,63,0.4)" : "rgba(255,77,109,0.35)");
    const col = i % cols, row = Math.floor(i / cols);
    const x = (col + 0.5) * (w / cols) - size / 2;
    const y = row * 115 + 15;
    const el = document.createElement("div");
    el.className = "bubble";
    el.style.width = el.style.height = size + "px";
    el.style.left = Math.max(0, x) + "px";
    el.style.top = y + "px";
    el.style.background = `radial-gradient(circle at 35% 30%, ${color}33, ${color}11)`;
    el.style.boxShadow = `0 0 ${size * 0.4}px ${glow}`;
    el.style.color = color;
    el.title = `${s.symbol} ${s.exchange_buy}→${s.exchange_sell}: ${fmt(s.net_alpha_bps)} bps — ${s.approved ? 'aprovado' : (s.reason || 'reprovado')}`;
    el.innerHTML = `<div class="pair">${s.symbol}</div><div class="val">${fmt(s.net_alpha_bps, 1)}</div>`;
    wrap.appendChild(el);
  });
}

function renderChart(signals) {
  if (!signals.length) {
    document.getElementById("chart-empty").hidden = false;
    document.getElementById("chart").innerHTML = "";
    return;
  }
  // Focus on the pair with the most recent signal.
  const focusKey = pairKey(signals[0]);
  const focus = signals.filter(s => pairKey(s) === focusKey).slice(0, 120).reverse();
  document.getElementById("chart-pair-label").textContent = signals[0].symbol + " (" + signals[0].exchange_buy + "→" + signals[0].exchange_sell + ")";

  if (focus.length < 2) {
    document.getElementById("chart-empty").hidden = false;
    document.getElementById("chart").innerHTML = "";
    return;
  }
  document.getElementById("chart-empty").hidden = true;

  // Bucket into ~20 candles of net_alpha_bps (OHLC over each bucket).
  const W = 600, H = 220, PAD = 10;
  const bucketSize = Math.max(1, Math.floor(focus.length / 20));
  const candles = [];
  for (let i = 0; i < focus.length; i += bucketSize) {
    const chunk = focus.slice(i, i + bucketSize);
    const vals = chunk.map(s => s.net_alpha_bps);
    candles.push({
      open: vals[0], close: vals[vals.length - 1],
      high: Math.max(...vals), low: Math.min(...vals),
      approved: chunk.some(s => s.approved),
    });
  }

  const minAlpha = config ? config.min_alpha_bps : 15.0;
  const allVals = candles.flatMap(c => [c.high, c.low]);
  const lo = Math.min(...allVals, minAlpha) - 2;
  const hi = Math.max(...allVals, minAlpha) + 2;
  const range = (hi - lo) || 1;
  const yOf = v => H - PAD - ((v - lo) / range) * (H - PAD * 2);
  const slotW = (W - PAD * 2) / candles.length;
  const bodyW = Math.max(2, slotW * 0.55);
  const thresholdY = yOf(minAlpha).toFixed(1);

  const candleSvg = candles.map((c, i) => {
    const cx = PAD + (i + 0.5) * slotW;
    const color = c.approved ? COLOR.green : (c.close >= c.open ? COLOR.cyan : COLOR.pinkDim);
    const yHigh = yOf(c.high), yLow = yOf(c.low);
    const yOpen = yOf(c.open), yClose = yOf(c.close);
    const bodyTop = Math.min(yOpen, yClose), bodyH = Math.max(1, Math.abs(yClose - yOpen));
    return `<line x1="${cx.toFixed(1)}" y1="${yHigh.toFixed(1)}" x2="${cx.toFixed(1)}" y2="${yLow.toFixed(1)}" stroke="${color}" stroke-width="1.5" />
      <rect x="${(cx - bodyW / 2).toFixed(1)}" y="${bodyTop.toFixed(1)}" width="${bodyW.toFixed(1)}" height="${bodyH.toFixed(1)}" fill="${color}" />`;
  }).join("");

  document.getElementById("chart").innerHTML = `
    <line x1="0" y1="${thresholdY}" x2="${W}" y2="${thresholdY}" stroke="${COLOR.muted}" stroke-width="1" stroke-dasharray="4,4" />
    ${candleSvg}
  `;
}

function renderFeed(executions) {
  const list = executions.slice(0, 10);
  document.getElementById("feed-empty").hidden = list.length > 0;
  document.getElementById("feed").innerHTML = list.map(e => `
    <li>
      <span><span class="route">${e.symbol} ${e.buy_exchange}→${e.sell_exchange}</span>
        <span class="time"> · ${e.executed_at ? new Date(e.executed_at).toLocaleTimeString('pt-BR') : ''} · ${e.execution_status}</span></span>
      <span class="pnl ${(e.realized_pnl_usd || 0) >= 0 ? 'green' : 'red'}">${fmtUsd(e.realized_pnl_usd)}</span>
    </li>`).join("");
}

async function refresh() {
  if (!config) config = await j("/api/config");
  const [status, signals, executions] = await Promise.all([
    j("/api/status"),
    j("/api/signals?limit=300"),
    j("/api/executions?limit=200"),
  ]);
  renderTicker(signals);
  renderStats(status, signals, executions);
  renderRadar(signals);
  renderChart(signals);
  renderFeed(executions);
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
