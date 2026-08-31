# Bimodal Arbitrage Platform

Plataforma de arbitragem cripto de alta frequência: cliente Android nativo
(governança/telemetria) + backend serverless com GPU no Modal.com (ingestão de
mercado, IA bimodal, motor de execução/risco).

Arquitetura completa em `docs/ARCHITECTURE.md` (espelho da documentação original).

## Estrutura

```
backend/
  schemas.py        # contrato de tipos compartilhado — ler antes de mexer em qualquer módulo
  security/          # key vault, envelope encryption, validação de API keys
  marketdata/         # ingestão CCXT Pro WS, VWAP/micro-price/OFI
  ml/                 # BimodalArbitrageNet (Bi-LSTM + CNN + cross-attention)
  execution/           # motor de risco/execução, broken-leg mitigation
  api/                 # FastAPI gateway + contracts.py
  db/                  # modelos SQLAlchemy + migrações Alembic
db/schema.sql         # schema Postgres de referência
android/               # app Kotlin/Jetpack Compose (Clean Architecture + MVVM)
tests/                 # pytest
.github/workflows/     # CI
```

## Segurança operacional

- `TRADING_MODE` (`.env`) começa em `testnet`. Trocar para `live` exige que a
  API key da exchange tenha sido validada como **sem permissão de saque**
  (checagem obrigatória em `backend/security`).
- Todo limite de risco (`RiskLimits`) tem default conservador e é
  configurável por usuário; existe kill switch.
- Nenhuma chave de exchange é logada ou mantida em texto plano além do
  escopo mínimo de execução da ordem (zeroing de buffers).

## Desenvolvimento

```bash
pip install -r requirements.txt
pytest
uvicorn backend.api.main:app --reload   # requer Postgres/Redis locais, ver .env.example
```

## Deploy

Deploy do backend no Modal.com (secrets, migrações Alembic, `modal deploy`),
build/assinatura do app Android e o checklist de segurança obrigatório antes
de `TRADING_MODE=live` (incluindo plano de rollback e kill switch) estão em
[`DEPLOY.md`](DEPLOY.md).
