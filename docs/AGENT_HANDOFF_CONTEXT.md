# Agent Handoff Context

This file is a compact project memory for future Codex/AI sessions. It should be referenced instead of pasting the full conversation.

## Current Product Direction

We are building the whole commerce system as an API-first platform.

Active product areas:
- Numbers
- Cards
- Digital products
- Proxies
- Owner/reseller operations

Primary UI today:
- Telegram bots
- Telegram Mini App for Numbers ordering and account workflows.

Architecture decision:
- Do not rewrite everything into a standalone website first.
- Every major product area must eventually have a web surface on `phantom-app.net`.
- Every major product area must expose or be ready to expose an API suitable for:
  - Telegram bots
  - Telegram Mini App
  - future web dashboard
  - admin panel
  - customer-built bots and partner integrations
- Build shared backend/API layers first, then use them from every client.

Canonical decision doc:
- `docs/platform/API_FIRST_PRODUCT_STRATEGY.md`

## Current Repo State Summary

Repository:
- `shop_project`
- main branch is used for production-oriented work.

Important recent commits:
- `11f1f7e Add SMS-Ready and PVA Pins providers`
- `ba23fe9 feat: add landing page handler at root path for phantom-app.net`
- `efc905f Obfuscate new provider display names`

Numbers provider decisions:
- Provider real names should not be shown to end users unless explicitly approved.
- `smsman` and `smsman_s6` display as `NonVoIP`.
- Newly added providers are internally named:
  - `smsready`
  - `pvapins`
- Their user-facing display names are obfuscated:
  - `smsready` -> `Golf`
  - `pvapins` -> `Hotel`
- Internal provider names, env vars, logs, tests, and class names may keep real/internal names for maintainability.

Provider credentials:
- Never commit provider keys or API secrets.
- Use environment variables/settings only.
- Relevant settings currently include:
  - `SMSREADY_KEY`
  - `SMSREADY_BASE_URL`
  - `PVAPINS_KEY`
  - `PVAPINS_BASE_URL`

## Current Domain Work

New domain:
- `phantom-app.net`

Current goal:
- It has or will have a simple landing page.
- Future direction is a complete web dashboard, but only after the backend/API is clean.

## Recommended Next Step

Start with Numbers API layer consolidation.

Goal:
- Create or formalize stable internal API endpoints for numbers workflows.
- Telegram Mini App should consume these APIs or shared service handlers instead of duplicating business flow logic.

Suggested API areas:
- Account/wallet:
  - user profile
  - balance
  - ledger entries
- Numbers catalog:
  - services
  - countries/states
  - temp price quotes
  - rental price quotes
- Orders:
  - create temp order
  - create rental order
  - refresh SMS
  - cancel/refund
  - replacement/alternate provider
  - rental finish/renew/wake/notes
- Admin:
  - provider health
  - provider balances
  - failed orders
  - manual refunds
  - user/order lookup

Implementation preference:
- Reuse existing business logic in `services/numbers/miniapp.py`, `services/numbers/manager.py`, and shared modules.
- Avoid creating duplicate purchase/refund logic.
- Extract shared service functions first where needed, then expose HTTP endpoints.

## Important Existing Files

Numbers:
- `services/numbers/miniapp.py`
- `services/numbers/manager.py`
- `services/numbers/provider_factory.py`
- `services/numbers/providers/`
- `services/numbers/shared/`
- `services/numbers/keyboards/core_numbers_kb.py`

Provider alias/display:
- `utils/provider_alias.py`

Provider docs/runtime matrix:
- `docs/providers/runtime_provider_matrix.md`
- `scripts/provider_matrix_report.py`

Migration/context docs:
- `docs/platform/API_FIRST_PRODUCT_STRATEGY.md`
- `docs/numbers/MINIAPP_MIGRATION_CHECKLIST.md`
- `docs/numbers/TELEGRAM_FLOW_AUDIT.md`
- `docs/PROJECT_CONTEXT.md`

## How To Use This File In Future Requests

In a new Codex request, write:

```text
Read docs/AGENT_HANDOFF_CONTEXT.md first and use it as the project context.
Continue from the API-first platform step.
```

If the UI supports file mentions, mention:

```text
[@docs/AGENT_HANDOFF_CONTEXT.md] Read this before starting.
```

If the session is outside this repo, paste only the relevant sections from this file, not the whole old conversation.

## Notes For Future Agents

- User prefers Arabic conversation.
- Be direct and pragmatic.
- Do not reveal real provider names in user-facing UI.
- Do not commit runtime data files unless explicitly requested.
- Run targeted tests after provider/UI changes.
- Run full `pytest` before pushes when touching shared numbers logic.
