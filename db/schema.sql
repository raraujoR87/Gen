-- Shared Postgres schema contract (unit 6 owns migrations, this file is the
-- reference all units can read to know column names/types).
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

CREATE TABLE IF NOT EXISTS users (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    email VARCHAR(255) UNIQUE NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS exchange_accounts (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID REFERENCES users(id) ON DELETE CASCADE,
    exchange_name VARCHAR(50) NOT NULL,
    encrypted_api_key TEXT NOT NULL,
    encrypted_api_secret TEXT NOT NULL,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS arbitrage_executions (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID REFERENCES users(id),
    symbol VARCHAR(20) NOT NULL,
    buy_exchange VARCHAR(50) NOT NULL,
    sell_exchange VARCHAR(50) NOT NULL,
    gross_spread_pct NUMERIC(6, 4) NOT NULL,
    net_spread_pct NUMERIC(6, 4) NOT NULL,
    executed_volume_usd NUMERIC(12, 2) NOT NULL,
    realized_pnl_usd NUMERIC(12, 4) NOT NULL,
    ml_confidence_score NUMERIC(4, 3) NOT NULL,
    execution_status VARCHAR(30) NOT NULL, -- 'SUCCESS', 'PARTIAL_FILL', 'HEDGED', 'REJECTED'
    executed_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_executions_user_time
    ON arbitrage_executions(user_id, executed_at DESC);
