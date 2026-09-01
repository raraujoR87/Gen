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

router = APIRouter()


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
<html lang="en">
<head>
<meta charset="utf-8">
<title>Bimodal Arbitrage — Local Paper Trading</title>
<style>
  body { font-family: -apple-system, Segoe UI, Roboto, sans-serif; margin: 0; padding: 24px;
         background: #0b0f14; color: #dbe2ea; }
  h1 { font-size: 18px; margin: 0 0 4px; }
  .subtitle { color: #7f8b99; font-size: 13px; margin-bottom: 20px; }
  .cards { display: flex; gap: 16px; margin-bottom: 24px; flex-wrap: wrap; }
  .card { background: #131a22; border: 1px solid #212b36; border-radius: 8px; padding: 14px 18px; min-width: 160px; }
  .card .label { font-size: 11px; color: #7f8b99; text-transform: uppercase; letter-spacing: .04em; }
  .card .value { font-size: 22px; margin-top: 4px; }
  .ok { color: #3fd68c; } .bad { color: #ff5c5c; } .warn { color: #ffb84d; }
  table { width: 100%; border-collapse: collapse; font-size: 13px; margin-bottom: 28px; }
  th, td { text-align: left; padding: 6px 10px; border-bottom: 1px solid #1b232c; white-space: nowrap; }
  th { color: #7f8b99; font-weight: 500; font-size: 11px; text-transform: uppercase; }
  tr:hover { background: #101720; }
  .approved { color: #3fd68c; } .rejected { color: #7f8b99; }
  button { background: #1b232c; color: #dbe2ea; border: 1px solid #2c3a48; border-radius: 6px;
           padding: 6px 14px; cursor: pointer; font-size: 13px; }
  button:hover { background: #24303c; }
  button.danger { border-color: #6b2530; color: #ff8080; }
  section h2 { font-size: 14px; color: #a9b4c0; margin: 0 0 8px; }
  .errors { color: #ff8080; font-size: 12px; white-space: pre-wrap; }
</style>
</head>
<body>
  <h1>Bimodal Arbitrage — Local Paper Trading</h1>
  <div class="subtitle">Real market data, simulated execution. No real order is ever sent from this view.</div>

  <div class="cards" id="cards"></div>

  <section>
    <h2>Kill switch</h2>
    <button id="engage" class="danger">Engage (halt trading)</button>
    <button id="disengage">Disengage</button>
  </section>

  <section>
    <h2>Signals (live model evaluations)</h2>
    <table id="signals"><thead><tr>
      <th>Time</th><th>Pair</th><th>Route</th><th>Net α (bps)</th><th>P(exec)</th>
      <th>Hazard</th><th>Approved</th><th>Reason</th><th>Exec status</th><th>PnL</th>
    </tr></thead><tbody></tbody></table>
  </section>

  <section>
    <h2>Executions (persisted)</h2>
    <table id="executions"><thead><tr>
      <th>Time</th><th>Symbol</th><th>Route</th><th>Notional</th><th>Net spread %</th>
      <th>PnL</th><th>Status</th>
    </tr></thead><tbody></tbody></table>
  </section>

  <div class="errors" id="errors"></div>

<script>
async function j(url, opts) { const r = await fetch(url, opts); return r.json(); }
function fmt(n, d) { return (n === null || n === undefined) ? "-" : Number(n).toFixed(d ?? 2); }
function fmtTime(t) { return new Date(t * 1000).toLocaleTimeString(); }

async function refresh() {
  const status = await j("/api/status");
  document.getElementById("cards").innerHTML = `
    <div class="card"><div class="label">Kill switch</div>
      <div class="value ${status.kill_switch_engaged ? 'bad' : 'ok'}">${status.kill_switch_engaged ? 'ENGAGED' : 'off'}</div></div>
    <div class="card"><div class="label">Uptime</div><div class="value">${Math.floor(status.uptime_s)}s</div></div>
    <div class="card"><div class="label">Pairs</div><div class="value">${status.monitored_pairs.join(', ') || '-'}</div></div>
    <div class="card"><div class="label">Mode</div><div class="value" style="font-size:13px">${status.mode}</div></div>
  `;
  document.getElementById("errors").textContent = status.errors.join("\\n");

  const signals = await j("/api/signals?limit=100");
  document.querySelector("#signals tbody").innerHTML = signals.map(s => `
    <tr>
      <td>${fmtTime(s.timestamp)}</td><td>${s.symbol}</td>
      <td>${s.exchange_buy}→${s.exchange_sell}</td>
      <td>${fmt(s.net_alpha_bps)}</td><td>${fmt(s.execution_probability, 3)}</td>
      <td>${fmt(s.adverse_hazard, 3)}</td>
      <td class="${s.approved ? 'approved' : 'rejected'}">${s.approved ? 'yes' : 'no'}</td>
      <td>${s.reason || ''}</td><td>${s.execution_status || ''}</td>
      <td>${fmt(s.realized_pnl_usd)}</td>
    </tr>`).join("");

  const executions = await j("/api/executions?limit=50");
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
