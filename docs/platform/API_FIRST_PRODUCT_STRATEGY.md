# API-First Product Strategy

Status: active decision
Last updated: 2026-05-25

## Decision

Every major product area must be built as an API-first product, not as a bot-only feature.

This applies to:

- Numbers
- Cards
- Digital products
- Proxies
- Future product lines

Each product can have multiple clients:

- Telegram bot
- Telegram Mini App
- Web dashboard on `phantom-app.net`
- Admin panel
- Customer-built bots or external integrations

The backend/API must be the stable product surface. Telegram and web screens are clients of that surface.

## Why

The same business workflows should be reusable by:

- our own Telegram bots,
- our own web dashboard,
- customer integrations,
- reseller or partner bots,
- future automation agents.

If business logic stays locked inside Telegram handlers, every new UI repeats purchase, refund, wallet, and provider rules. That increases bugs and makes customer-facing APIs harder to provide later.

## API Requirements

Public or partner-facing APIs must be designed so a customer can build a bot on top of them.

Minimum API qualities:

- stable endpoint names and request parameters,
- predictable JSON responses,
- documented error codes/messages,
- idempotency for money-moving and order-changing operations,
- no leaked internal provider names unless explicitly admin-only,
- clear auth model using API keys or scoped tokens,
- rate limits and abuse protection,
- customer-facing webhooks for asynchronous state changes,
- provider inbound webhooks where upstream delivery supports it,
- polling only as a documented fallback or explicit provider exception,
- versioning before external customers depend on it.

## Product Boundaries

Keep docs and plans separated by product area:

- `docs/numbers/`
- `docs/cards/`
- `docs/digital/`
- `docs/proxies/`
- `docs/platform/`

Shared decisions belong in `docs/platform/`.
Provider source material belongs in `docs/providers/`.
Old plans that no longer drive work belong in `docs/archive/`.

## Near-Term Build Rule

When adding or moving a workflow:

1. Put core business behavior in a service/shared module.
2. Expose that behavior through an HTTP/API layer where appropriate.
3. Make Telegram bots, Mini Apps, and future web pages call the same behavior.
4. Add tests against the shared behavior, not only against one UI.

## Current First Target

Numbers is the first API-first consolidation target because it already has:

- Telegram bot flows,
- Telegram Mini App flows,
- provider aggregation,
- wallet/ledger effects,
- refund/replacement/renewal behavior,
- future web dashboard demand.

Current Numbers backend direction:

- `/api/v1/numbers` is the versioned customer/API surface.
- `/mini/numbers/api` remains the Telegram Mini App client surface and should delegate to shared/API services where practical.
- Provider inbound SMS/code delivery is webhook-first through `phantom-app.net`.
- Customer webhooks are available for order creation, SMS/code, resend requested, and refund events.
- Refund UX should be server-managed, not a customer manual action.

After Numbers, apply the same pattern to Digital products, Cards, and Proxies.
