# Deploy

Guia de implantação do backend (Modal.com) e do app Android, com checklist de
segurança operacional obrigatório antes de ligar `TRADING_MODE=live`.

> Leia primeiro `docs/ARCHITECTURE.md` (seções 2, 6 e 9) e `.env.example`. Este
> documento assume que você já tem o repositório clonado e o ambiente Python de
> `requirements.txt` instalado.

## 1. Pré-requisitos

- **Conta no Modal.com** e CLI autenticada:

  ```bash
  pip install modal
  modal token new
  ```

- **PostgreSQL gerenciado** para produção (ex.: [Neon](https://neon.tech),
  [Supabase](https://supabase.com) ou Amazon RDS). Anote a connection string
  no formato `postgresql+asyncpg://...` (mesmo formato de `DATABASE_URL` em
  `.env.example`).
- **Redis gerenciado** para o cache de order book (ex.: [Upstash](https://upstash.com)).
  Anote a `REDIS_URL`.
- **Uma conta em cada exchange** que o bot vai operar (Binance, Bybit, OKX,
  Kraken, Mercado Bitcoin — conforme seção 1 de `docs/ARCHITECTURE.md`), com
  uma API key dedicada criada para este sistema.

  > **Ao criar cada API key, desabilite explicitamente a permissão de Saque
  > (Withdrawal) e Transferência Externa.** Habilite somente Spot Trading e
  > leitura de saldo/posições. Isso é exigido pelo protocolo de segurança da
  > seção 2 de `docs/ARCHITECTURE.md` — sem isso o backend deve recusar a
  > chave, mas a verificação manual na própria exchange é a linha de defesa
  > que não depende do nosso código.

## 2. Configuração de secrets no Modal

O backend lê segredos de produção a partir de um `modal.Secret` chamado
`arbitrage-secrets` (nome configurável via `KMS_SECRET_NAME` em
`.env.example`). Preencha os valores a partir do seu `.env` de produção
(nunca commite o `.env` real — use `.env.example` só como template):

```bash
modal secret create arbitrage-secrets \
  KMS_KEY=<chave mestra de envelope encryption, ver docs/ARCHITECTURE.md seção 2> \
  DATABASE_URL=postgresql+asyncpg://user:password@host:5432/arbitrage \
  JWT_SECRET=<segredo forte, nunca o valor de exemplo "change-me"> \
  REDIS_URL=redis://:<password>@host:6379/0 \
  ENVELOPE_KEY_ID=<id da chave usada para encriptar exchange_accounts>
```

Notas:

- `KMS_KEY` é a chave mestra que decripta as credenciais de exchange
  armazenadas em `exchange_accounts` (envelope encryption — seção 2 do
  documento de arquitetura). Gere-a com um gerador criptograficamente seguro
  (ex. `openssl rand -base64 32`), nunca reaproveite uma chave de outro
  ambiente.
- `JWT_SECRET` deve ser único de produção; nunca reutilize o valor de
  `.env.example`.
- Para atualizar secrets depois de criados, use `modal secret create
  arbitrage-secrets ... ` novamente (sobrescreve) ou o painel web do Modal.
- Os demais valores de `.env.example` que controlam limites de risco
  (`MIN_ALPHA_BPS`, `MAX_NOTIONAL_USD_PER_TRADE`, `MAX_DAILY_NOTIONAL_USD`
  etc.) podem ficar como variáveis de ambiente do próprio `modal.App` (não
  precisam ir no `Secret`), mas devem ser revisados antes do primeiro deploy
  em produção — ver checklist na seção 5.

## 3. Deploy do backend

1. **Rode as migrações Alembic contra o Postgres de produção antes do
   primeiro deploy** (nunca deixe o schema ser criado implicitamente pela
   primeira request):

   ```bash
   DATABASE_URL=postgresql+asyncpg://user:password@host:5432/arbitrage \
     alembic upgrade head
   ```

   Confirme que as tabelas `users`, `exchange_accounts` e
   `arbitrage_executions` (seção 7 de `docs/ARCHITECTURE.md`, schema de
   referência em `db/schema.sql`) foram criadas antes de seguir.

2. **Deploy do app Modal**:

   ```bash
   modal deploy modal_app.py
   ```

   Isso publica o `modal.App` (FastAPI + GPU T4, seção 6 de
   `docs/ARCHITECTURE.md`) e o endpoint `process_arbitrage_intent`. O
   comando imprime a URL pública do deployment — guarde-a, ela é usada na
   configuração do Android (seção 4).

3. Redeploys subsequentes usam o mesmo comando; secrets e migrações não
   precisam ser refeitos a menos que o schema ou os segredos mudem.

## 4. Build e deploy do Android

1. **Gere um keystore de release** (uma vez, guarde em local seguro — nunca
   commite no repositório):

   ```bash
   keytool -genkey -v -keystore release.keystore -alias arbitrage-release \
     -keyalg RSA -keysize 2048 -validity 10000
   ```

2. **Configure o `BuildConfig`** do módulo `android/app` apontando para a URL
   pública do deployment do Modal obtida no passo anterior (ex. em
   `android/app/build.gradle.kts`, `buildConfigField` para `BASE_URL`, ou via
   `local.properties` não versionado):

   ```kotlin
   buildConfigField("String", "BASE_URL", "\"https://<seu-workspace>--<app>-process-arbitrage-intent.modal.run\"")
   ```

3. **Gere o APK/AAB de release**:

   ```bash
   ./gradlew assembleRelease
   # ou, para publicação na Play Store:
   ./gradlew bundleRelease
   ```

   Assine com o keystore gerado no passo 1 (via `signingConfigs` no Gradle ou
   `apksigner` manualmente).

## 5. Checklist de segurança operacional — obrigatório antes de `TRADING_MODE=live`

Não pule nenhum item. `TRADING_MODE` controla se o motor de execução
(`backend/execution`) está autorizado a despachar ordens reais nas
exchanges; até aqui tudo deve ter rodado em `testnet`.

1. **API key sem permissão de saque.**
   - O backend valida isso automaticamente ao cadastrar a `exchange_account`
     (seção 2 de `docs/ARCHITECTURE.md`), mas **confirme visualmente também
     no painel da exchange** que a permissão de Withdrawal/Transferência
     Externa está desligada para cada key usada em produção. Não confie
     apenas na validação automatizada — é a última barreira antes de capital
     real ficar exposto.

2. **Fase 1 completa: coleta de dados + treinamento** (seção 9,
   item 1, de `docs/ARCHITECTURE.md`).
   - No mínimo 30 dias de order book L2 + trades para os pares operados
     (BTC/USDT, ETH/USDT, SOL/USDT, ou os pares reais do seu deployment).
   - `BimodalArbitrageNet` (`backend/ml/model.py`) treinada e avaliada
     especificamente quanto a **Precision sobre falso spread** — um modelo
     com boa acurácia agregada mas muitos falsos positivos de spread é
     inaceitável, pois cada falso positivo é uma ordem real disparada.

3. **Fase 2 completa: paper trading contínuo** (seção 9, item 2).
   - Bot conectado às WebSockets ao vivo das exchanges, com ordens
     fictícias, rodando por um período representativo de mercado (inclua
     pelo menos um período de alta volatilidade).
   - Monitore **Latency Slippage** de ponta a ponta: tempo entre sinal do
     modelo e confirmação simulada de execução. Se o slippage medido em
     paper trading já corrói a maior parte do `AlphaLiquido` esperado (seção
     5 de `docs/ARCHITECTURE.md`), **não avance para a Fase 3** — recalibre
     `MIN_ALPHA_BPS` ou revise a infraestrutura de latência antes.

4. **Nunca pule direto para capital real.** Fases 1 e 2 são pré-requisito
   formal de `docs/ARCHITECTURE.md` (seção 9) para `TRADING_MODE=live`.

5. **Fase 3: comece com micro-lotes.**
   - Volume inicial recomendado no documento de arquitetura: **~$50 por
     perna** (`MAX_NOTIONAL_USD_PER_TRADE=50.0` já é o default de
     `.env.example` — não aumente antes de ter dados reais de produção).
   - Opere inicialmente em duas exchanges com liquidez comprovada.
   - Meça taxa de execução simultânea das duas pernas (broken-leg rate) e só
     então calibre a exposição direcional máxima para cima.

6. **Monitore `max_daily_notional_usd` e o kill switch continuamente.**
   - `RiskLimits.max_daily_notional_usd` (default `500.0` em
     `.env.example`) é o teto agregado de notional por dia — trate qualquer
     aproximação desse teto como sinal para revisar manualmente antes de
     subir o limite.
   - `RiskLimits.kill_switch_engaged` (`backend/schemas.py`) deve ser
     verificado como `False` (motor operando normalmente) e testado — engaje
     e desengaje o kill switch em ambiente de testnet antes de ir para
     produção, para confirmar que o motor de execução realmente para de
     despachar ordens quando ele está `True`.

7. **Tenha um plano de rollback documentado e testado** (ver seção 6 abaixo)
   antes de ligar `live` pela primeira vez — não é algo para improvisar
   durante um incidente.

## 6. Rollback / kill switch de emergência

Em caso de comportamento anômalo (ordens inesperadas, spread líquido
negativo sistemático, taxa de broken-leg alta, latência degradada, etc.), aja
nesta ordem:

1. **Engate o kill switch imediatamente.**
   - Defina `kill_switch_engaged=true` para o(s) `RiskLimits` afetado(s) —
     via endpoint administrativo exposto por `backend/api` (gateway FastAPI,
     seção 6 de `docs/ARCHITECTURE.md`) ou, se o endpoint ainda não estiver
     disponível para o seu deployment, diretamente no banco de produção
     (`UPDATE` na configuração de risco do usuário/conta) e reiniciando o
     deployment do Modal para forçar a releitura:

     ```bash
     modal app stop <nome-do-app>
     ```

     Parar o app do Modal interrompe todo o despacho de ordens
     imediatamente — é o freio de emergência mais bruto e mais rápido
     disponível, use-o sem hesitar se o kill switch a nível de aplicação não
     responder a tempo.

2. **Revogue as API keys diretamente na exchange.** Esta é a última linha de
   defesa e não depende do nosso backend estar respondendo ou não:
   - Acesse o painel de gerenciamento de API keys de cada exchange afetada.
   - Revogue/delete a key comprometida ou associada ao comportamento
     anômalo. Isso invalida a key mesmo que o worker do Modal ainda tenha
     credenciais decriptadas em memória para uma ordem em voo.
   - Gere uma nova key (com Withdrawal desabilitado, como sempre) somente
     depois de identificada e corrigida a causa raiz do incidente.

3. **Depois do incidente:** documente o que aconteceu, reavalie se é preciso
   voltar a Fase 2 (paper trading) antes de reengajar `live`, e só desengate
   o kill switch depois de confirmar a correção.
