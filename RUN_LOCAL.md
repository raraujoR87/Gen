# Running the local paper-trading service

This is the local-first mode chosen for the initial validation phase: a
single Python process, on your own machine, that

1. connects to **real** exchange market data (order books, via `ccxt`/
   `ccxt.pro`),
2. feeds that real data into the bimodal ML model to decide whether an
   arbitrage opportunity is worth taking, and
3. **simulates** the resulting trade (paper trading) — it prices the fill
   against the real order book but never sends a real order to any
   exchange.

The Android app is deliberately deferred: if this local loop shows the
signals would have been profitable over time, the app becomes worth
building. Until then, a local web dashboard (`/dashboard`) replaces it.

No real money is ever at risk running this. The one path that *would* place
real orders (`backend/execution/broken_leg.dispatch_orders`) is explicitly
unimplemented (`raise NotImplementedError`) and this runner never calls it —
only `backend/execution/paper_exchange.PaperExchangeClient` is used.

This guide runs everything as native local processes — no Docker, and the
database is a plain SQLite file (no server to install or manage). Postgres
is still what production/CI use (see `docker-compose.yml` and `alembic/`
if you ever want that instead), but for local paper-trading validation
SQLite is simpler and the models already support it — see
`backend/db/models.py`'s `GUID` type.

## 1. Install and start Redis (native, not Docker)

The order-book cache (`backend/marketdata/orderbook_cache.py`) is
Redis-backed, so Redis itself still needs to be running — just not via
Docker. Install it with your OS package manager and start it as a normal
background process:

```bash
# Debian/Ubuntu
sudo apt-get install redis-server
redis-server --daemonize yes

# macOS (Homebrew)
brew install redis
brew services start redis
```

Confirm it's up: `redis-cli ping` should print `PONG`.

## 2. Configure environment

```bash
cp .env.example .env
```

Edit `.env`:

```
DATABASE_URL=sqlite+aiosqlite:///./local.db
MONITORED_PAIRS=BTC/USDT:binance:kraken,ETH/USDT:binance:bybit
```

(`REDIS_URL` can stay at its default, `redis://localhost:6379/0`, matching
step 1.)

Each `MONITORED_PAIRS` entry is `SYMBOL:exchange_buy:exchange_sell` using
[ccxt exchange ids](https://github.com/ccxt/ccxt/wiki/Exchange-Markets). No
API keys are needed for this mode — order books are public market data,
and no orders are ever placed.

`ccxt.pro` (real-time websocket order books) is not installed by default,
since it ships under CCXT's commercial Pro license — see
`requirements.txt`. Without it, the runner automatically falls back to
polling `fetch_order_book` over plain `ccxt` REST every `POLL_INTERVAL_S`
seconds (`backend/marketdata/ws_ingestion.CcxtRestPollingFeed`). This works
out of the box but is materially higher latency; install `ccxt.pro`
yourself and it will be used automatically if present
(`backend/marketdata/ws_ingestion.get_default_feed`).

## 3. Install dependencies and create the database

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python scripts/init_db.py
```

`scripts/init_db.py` creates the `users` / `exchange_accounts` /
`arbitrage_executions` tables straight from the SQLAlchemy models
(`Base.metadata.create_all`) into the SQLite file named by `DATABASE_URL`.
It's the SQLite-compatible equivalent of `alembic upgrade head` — the
Alembic migration under `alembic/versions/` is Postgres-specific (native
`UUID` columns, the `uuid-ossp` extension), so it does not run against
SQLite; use it only if you switch `DATABASE_URL` back to a real Postgres
instance.

## 4. Start the service

```bash
uvicorn backend.api.main:app --reload
```

On startup this launches the paper-trading runner as a background task
(`backend/api/main.py`'s lifespan handler calling
`backend.marketdata.runner.run_forever`), bootstraps a single local user
(`LOCAL_USER_EMAIL` in `.env`), and begins ingesting real order books for
every pair in `MONITORED_PAIRS`.

Open **http://localhost:8000/dashboard** to watch it live: kill-switch
control, every model evaluation (approved or rejected, with the reasons),
and every simulated execution actually persisted to `local.db`.

To stop trading without stopping the process, click **Engage** on the
dashboard, or `POST /api/kill-switch/engage`.

## What this does and doesn't prove

- **Does**: exercise the real market-data ingestion, feature engineering,
  ML inference, and risk-gate code paths against live prices, and measure
  whether the model's approved signals would have been net-profitable, with
  the paper exchange's optimistic fill assumption (every accepted order
  fills in full at the requested price — no partial fills, latency, or
  slippage beyond what `compute_net_alpha`'s `slippage_est` already
  accounts for).
- **Doesn't**: prove profitability under real execution conditions (queue
  position, partial fills, real slippage, exchange downtime) — that's what
  a subsequent real-money pilot, with tight `RiskLimits`, would need to
  validate before scaling up or building the Android app.
- **Model weights are untrained** (`backend/ml/model_cache.py` constructs
  `BimodalArbitrageNet` with random initialization). Signals right now
  reflect an untrained model, not a validated trading strategy — training
  on real historical data (`backend/ml/train.py`) is a prerequisite before
  this run's results mean anything. `RUN_LOCAL.md` intentionally does not
  paper over that: the dashboard shows exactly what the model outputs, so
  it's visible when it's not doing anything useful yet.
