# Private Degen Scanner

Private, owner-only Telegram market scanner and paper-performance tracker for Solana, Ethereum, and BNB Chain. It records every alert, reference price, milestone, observed ATH, drawdown, and losing call. It never requires wallet credentials.

## Data honesty

The included provider uses public DexScreener endpoints for discovery, pairs, prices, liquidity, volume, price changes, and transaction counts. DexScreener does not supply authoritative holder concentration, token authorities, tax, liquidity-lock, or contract-verification data. Those fields remain unavailable and risk is labeled `UNKNOWN`; the application does not infer or invent them. Provider interfaces are isolated under `app/market` so paid RPC, security, or holder-data providers can be added later.

## Optional AI analysis

AI is optional and is never required for scanning, scoring, alerts, or tracking. With no `AI_API_KEY`, it remains off even when `AI_ENABLED=true`. With a key, the scanner attempts the configured AgentRouter model using the standard `chat.completions` interface. A successful GLM 5.3 response is included in the alert. A timeout, unsupported model, rate limit, malformed response, or router outage disables AI temporarily for `AI_FAILURE_COOLDOWN_SECONDS`; deterministic scanning and alert delivery continue without waiting for AI. Verify the exact GLM model identifier in AgentRouter's current documentation.

## Railway deployment

1. Push this repository to GitHub and create a Railway project.
2. Add Railway PostgreSQL and Redis services.
3. Create four services from the same repository: `bot`, `scanner`, `tracker`, and `telegram`.
4. Set `SERVICE_ROLE` to the corresponding name on each service.
5. Add the shared variables from `.env.example`. Railway's PostgreSQL URL may begin with `postgresql://`; it is converted automatically to the async driver URL.
6. Set `TELEGRAM_BOT_TOKEN` and the numeric `OWNER_TELEGRAM_ID` on `bot` and `telegram`.
7. Deploy. The start command runs `alembic upgrade head` before starting each process; migrations are idempotent.

Do not expose multiple `bot` replicas because Telegram long polling permits one consumer. Scanner/tracker duplicate protection uses Redis cooldown locks and atomic PostgreSQL milestone claims.

## Local start

```bash
cp .env.example .env
docker compose up -d --build
```

Set the real Telegram token and numeric owner ID in `.env` first. No private key, seed phrase, wallet password, or exchange credential belongs in this project.

## Commands

`/start`, `/help`, `/status`, `/active`, `/history`, `/stats`, `/call <id>`, `/scan`, `/scan sol`, `/scan eth`, `/scan bsc`, `/settings`.

Every handler is protected by a numeric `from_user.id` check. Other users receive no bot functionality.

## Architecture

- `bot`: private Telegram command polling
- `scanner`: centralized discovery, filters, risk, scoring, cooldown, call creation
- `tracker`: centralized active-call price refresh, anomaly checks, ATH and milestone claims
- `telegram`: single outbound queue consumer for alerts and milestones
- PostgreSQL: durable tokens, calls, milestones, snapshots, audit corrections
- Redis: cooldown locks and outbound queue

## Tests

```bash
python -m pytest -q
```

Tests cover multiples, one-time crossing behavior, ATH, drawdown, invalid/stale prices, anomaly detection, filters, risk uncertainty, and score bounds. Production migration and restart recovery derive from persisted `ACTIVE` calls, recorded milestones, and ATH fields in PostgreSQL.

## Operational notes

The default scanner intentionally remains conservative. Tune thresholds with environment variables only after observing the provider's coverage. A `HIGH RISK`, data-conflicted, invalid-price, stale, duplicate, cooldown-blocked, or below-threshold candidate is not alerted. Snapshot retention is enforced by the tracker. Historical calls and milestones are never deleted by retention cleanup.
