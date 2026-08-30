# Private Degen Scanner

Private, owner-only Telegram market scanner and paper-performance tracker for Solana, Ethereum, BNB Chain, and Base. It records every alert, reference price, milestone, observed ATH, drawdown, and losing call. It never requires wallet credentials.

The desk does **not** spam every coin. Auto-alerts and `/scan` keep only the best degen setups. Paste a contract to see the live card, charts, and — if this bot already called it — the exact pump after that call.

## What it does

- 🏆 **Best degen only** — ranks live pairs and keeps the elite 1–3, not a junk list
- 🔵 **Base network** — same degen flow as Solana, Ethereum, and BNB
- 📥 **Contract paste** — DexScreener URL or CA lookup with after-call pump (`4.20X / +320%`)
- 📈 **Charts** — DexScreener, GeckoTerminal, DexTools, and Birdeye buttons plus an ASCII mini-tape
- 🚨 **Louder alerts** — emoji-rich call, milestone, and recovery notifications
- 📌 **Paper tracking** — reference price locked forever, ATH, drawdown, one-time milestone crosses

## Data honesty

The included provider uses public DexScreener endpoints for discovery, pairs, prices, liquidity, volume, price changes, and transaction counts. DexScreener does not supply authoritative holder concentration, token authorities, tax, liquidity-lock, or contract-verification data. Those fields remain unavailable and risk is labeled `UNKNOWN`; the application does not infer or invent them. Provider interfaces are isolated under `app/market` so paid RPC, security, or holder-data providers can be added later.

## Optional AI analysis

AI is optional and is never required for scanning, scoring, alerts, or tracking. With no `AI_API_KEY`, it remains off even when `AI_ENABLED=true`. With a key, the scanner attempts the configured AgentRouter model using the standard `chat/completions` interface. A successful GLM 5.3 response is included in the alert. A timeout, unsupported model, rate limit, malformed response, or router outage disables AI temporarily for `AI_FAILURE_COOLDOWN_SECONDS`; deterministic scanning and alert delivery continue without waiting for AI. Verify the exact GLM model identifier in AgentRouter's current documentation.

## Railway deployment

Use the included `railway-template.json` when creating the Railway project. It declares the four application services and links the database variables automatically:

```text
DATABASE_URL = ${{Postgres.DATABASE_URL}}
REDIS_URL     = ${{Redis.REDIS_URL}}
```

After importing the template:

1. Add Railway PostgreSQL using the service name `Postgres` and Redis using the service name `Redis`.
2. Connect this GitHub repo (`Pintu64/Degen`) to the four application services: `bot`, `scanner`, `tracker`, and `telegram`.
3. Set these **shared** variables on every app service (or project-level):
   - `TELEGRAM_BOT_TOKEN`
   - `OWNER_TELEGRAM_ID` (numeric)
   - `FLUXRPC_API_KEY` / `FLUXRPC_URL` / `FLUX_SHIELD_URL` (Solana mint/freeze/holders)
   - `BIRDEYE_API_KEY` (holder count)
   - `ETHEREUM_API_KEY` / `BSC_API_KEY` (optional EVM)
4. Set `AI_API_KEY` only if you want GLM analysis through AgentRouter; AI remains harmlessly inactive without it.
5. Deploy. Each service runs `alembic upgrade head` before starting; a PostgreSQL advisory lock serializes concurrent migration attempts.

Do **not** put tokens in git. Railway variables only.

Railway does not infer secrets from `.env.example`. Telegram and optional AI keys must remain manually entered as protected variables. Railway's PostgreSQL URL may begin with `postgresql://`; the application converts it to the async driver URL automatically.

Do not expose multiple `bot` replicas because Telegram long polling permits one consumer. Scanner/tracker duplicate protection uses Redis cooldown locks and atomic PostgreSQL milestone claims.

## Local start

```bash
cp .env.example .env
docker compose up -d --build
```

Set the real Telegram token and numeric owner ID in `.env` first. No private key, seed phrase, wallet password, or exchange credential belongs in this project.

## Commands

`/start`, `/help`, `/status`, `/active`, `/history`, `/stats`, `/call <id>`, `/close <id>`, `/scan`, `/scan sol`, `/scan eth`, `/scan bsc`, `/scan base`, `/scan all`, `/best`, `/ca`, `/check`, `/track`, `/mytracks`, `/chains`, `/settings`.

The persistent reply keyboard and inline controls provide the same scan, track, refresh, close, chart, history, status, and settings flows without requiring commands.

Paste a contract address or DexScreener URL in the private chat. The card shows live momentum, charts, and the pump since this bot's call when a paper call already exists.

Every handler requires both the configured numeric `from_user.id` and that owner's private chat. Group/channel use and other users receive no bot functionality.

## Architecture

- `bot`: private Telegram command polling
- `scanner`: centralized discovery, filters, risk, scoring, degen ranker, cooldown, call creation — alerts only the best pick(s) each cycle
- `tracker`: centralized active-call price refresh, anomaly checks, ATH and milestone claims
- `telegram`: single outbound queue consumer for alerts and milestones
- PostgreSQL: durable tokens, calls, milestones, snapshots, audit corrections
- Redis: cooldown locks, service heartbeats, reliable FIFO outbound queue, and failed-message dead-letter queue

## Tests

```bash
python -m pytest -q
```

Tests cover multiples, one-time crossing behavior, ATH, drawdown, invalid/stale prices, anomaly detection, filters, risk uncertainty, score bounds, Base addresses, degen ranking, and after-call pump copy. Production migration and restart recovery derive from persisted `ACTIVE` calls, recorded milestones, and ATH fields in PostgreSQL.

## Operational notes

The default scanner intentionally remains conservative, then the degen ranker throws away anything that already went vertical, looks too large, or fails filters. Tune thresholds with environment variables only after observing the provider's coverage. A `HIGH RISK`, data-conflicted, invalid-price, stale, duplicate, cooldown-blocked, below-threshold, or non-elite candidate is not alerted. Snapshot retention is enforced by the tracker. Historical calls and milestones are never deleted by retention cleanup.
