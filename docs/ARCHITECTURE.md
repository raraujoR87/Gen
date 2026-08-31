# Documentação Técnica e Arquitetural: Plataforma de Arbitragem Cripto de Alta Frequência Bimodal

> Espelho do documento de arquitetura original (Google Docs) que fundamenta este
> repositório. As unidades de implementação (`backend/security`, `backend/marketdata`,
> `backend/ml`, `backend/execution`, `backend/api`, `backend/db`, `android/...`)
> implementam as seções correspondentes abaixo. Onde o código-fonte deste documento
> continha erros de sintaxe/bugs (comum em texto extraído de Google Docs — barras de
> escape sobrando, `_` virando `\_`, etc.), as unidades corrigem ao implementar.

## 1. Arquitetura Geral do Sistema

Topologia híbrida e desacoplada: cliente nativo Android (Kotlin/Jetpack Compose) como
interface de governança, parametrização de risco e monitoramento de telemetria; núcleo
computacional serverless de baixa latência com aceleração por GPU no Modal.com.

Componentes do backend: Gateway de API & Autenticação (FastAPI serverless, JWT, rate
limit) → Key Vault Criptográfico (KMS + AES-256-GCM efêmero) e Market Data Ingestion L2
(CCXT Pro WS workers, Redis) → Motor de IA Bimodal (PyTorch, GPU T4/A10G: Stream 1
Bi-LSTM/OFI + Stream 2 ViT/heatmap L2, fusão cross-attention, P(Alpha)) → Motor de Risco
& Execução Concorrente (dispatch IOC/FOK assíncrono, auto-hedge, rebalanceamento
dinâmico) → Exchanges (Binance, Bybit, OKX, Kraken, Mercado Bitcoin).

## 2. Protocolo de Segurança e Criptografia de Credenciais

Zero-Knowledge Application Secret Storage com criptografia de envelope.

1. Validação de permissão restrita: a API key do usuário deve ter Saque e
   Transferência Externa desativados na exchange, permitindo só Spot Trading e leitura
   de saldo.
2. Derivação de chave local (client-side): PIN mestre ou biometria (BiometricPrompt +
   CryptoObject); chave intermediária derivada com Argon2id, salt único no
   Secure Element/StrongBox do dispositivo.
3. Criptografia em trânsito: payload = AES-256-GCM(K_session, api_secrets), K_session
   negociada via TLS 1.3 com certificate pinning.
4. Armazenamento e descriptografia efêmera no Modal: chaves salvas encriptadas com
   chave mestra do KMS do Modal (`modal.Secret`); a memória do worker descriptografa só
   no escopo da execução da ordem e faz zeroing de buffers ao final.

## 3. Pipeline de Ingestão de Microestrutura e Market Data

Sem polling REST — WebSockets L2/L3 persistentes multi-par.

- **VWAP** para uma quantidade `Q` a arbitrar (lado ask):
  `VWAP_ask(Q) = Σ P_i * min(q_i, Q - Σ_{j<i} q_j) / Q`
- **Micro-price**: `P_micro = P_bid * (V_ask / (V_bid + V_ask)) + P_ask * (V_bid / (V_bid + V_ask))`
- **Order Flow Imbalance (OFI_t)**: fluxo líquido de ordens no instante `t`, combinando
  indicadores de mudança de preço/volume no bid e no ask entre `t-1` e `t`.

## 4. Arquitetura da Inteligência Artificial Bimodal

Stream 1 (Quant/Temporal): janela de 100 ticks, 12 features (spread, OFI, VWAP drift,
aceleração de volume) → Bi-LSTM. Stream 2 (Visuoespacial): matriz 2D 50x50 (eixo X =
níveis de preço, eixo Y = tempo, intensidade = volume) → CNN/ViT mini. Fusão por
cross-attention (`Z = softmax(QK^T/√d)V`) produz três cabeças: probabilidade de sucesso
`P(Alpha > Custo)`, alpha esperado (spread líquido em bps) e risco de cauda/MEV
(adverse selection). Implementação de referência: `BimodalArbitrageNet` em
`backend/ml/model.py`.

## 5. Motor de Execução Assíncrona e Gestão de Risco

Alpha líquido:

```
AlphaLiquido = (VWAP_bid_B*(1-tau_B) - VWAP_ask_A*(1+tau_A)) / (VWAP_ask_A*(1+tau_A))
               - S_est - C_transf / Q_usd
```

Execução autorizada apenas se `AlphaLiquido > AlphaMinimo` **e**
`P(Alpha) > 0.85` **e** `Hazard < 0.20`.

**Broken Leg Mitigation**: disparo paralelo de ordens IOC; se uma perna for rejeitada,
auto-hedge imediato — em baixa volatilidade via limit order com re-peg na melhor fila de
bid, em alta volatilidade/ruptura via ordem a mercado de liquidação instantânea com stop
rígido no break-even.

## 6. Backend Serverless no Modal.com

FastAPI + `modal.App`, GPU T4, `modal.Secret` para segredos, endpoint
`process_arbitrage_intent` que valida JWT, ingere livros via CCXT Pro, avalia o modelo
bimodal e despacha ordens concorrentes via `asyncio.gather` quando os limiares de risco
são satisfeitos. Ver `backend/api/` e `modal_app.py`.

## 7. Modelagem do Banco de Dados Relacional (PostgreSQL)

Tabelas `users`, `exchange_accounts` (chaves de API sempre encriptadas em repouso) e
`arbitrage_executions` (histórico de execuções com spread bruto/líquido, PnL realizado,
score de confiança do modelo, status). Ver `db/schema.sql`.

## 8. Arquitetura do Cliente Android (Kotlin + Jetpack Compose)

Clean Architecture + MVVM com StateFlows reativos:

```
data/        (Android KeyStore, EncryptedSharedPreferences, Ktor SSE/Retrofit, repository)
domain/      (models, use cases: ExecuteTradeUseCase, StreamTelemetryUseCase)
presentation/ (DashboardScreen, KeyManagementScreen, theme)
```

## 9. Roteiro de Implantação e Validação

1. **Coleta de dados L2 e treinamento**: 30 dias de order book + trades (BTC/USDT,
   ETH/USDT, SOL/USDT) em Parquet, treino da `BimodalArbitrageNet` avaliando Precision
   sobre falso spread.
2. **Paper trading contínuo**: bot conectado a WebSockets ao vivo com ordens fictícias;
   monitorar Latency Slippage.
3. **Deploy gradual em produção**: micro-lotes (ex. $50/perna) em duas exchanges com
   liquidez comprovada, medindo taxa de execução simultânea e calibrando exposição
   direcional máxima. `TRADING_MODE=live` só depois de validar as fases 1 e 2.
