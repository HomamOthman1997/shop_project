# Project Context

## Purpose

This repository powers a multi-bot Telegram commerce system centered around:

- Main public services bot
- Reseller-owned cloned bots
- Cards bot
- Digital products/store flows
- Numbers/temp-rental flows
- Proxy rental flows
- Owner and reseller operational tooling

The project is built around long-running `aiogram` polling bots managed by [`bot_manager.py`](/Users/CyberZone/PycharmProjects/shop_project/bot_manager.py).

## Main Runtime Shape

Core runtime entrypoint:

- [`bot_manager.py`](/Users/CyberZone/PycharmProjects/shop_project/bot_manager.py)

Key responsibilities:

- Start and supervise the public/main/admin/cards dispatchers
- Bootstrap indexes and startup jobs
- Run recurring sweeps and recovery tasks
- Refresh proxy catalog cache
- Run provider alerting and subscription notice cycles
- Keep multiple bot contexts active inside one process

## Main Functional Areas

### Numbers

Primary files:

- [`services/numbers/handlers/core_numbers.py`](/Users/CyberZone/PycharmProjects/shop_project/services/numbers/handlers/core_numbers.py)
- [`services/numbers/handlers/core_numbers_buy.py`](/Users/CyberZone/PycharmProjects/shop_project/services/numbers/handlers/core_numbers_buy.py)
- [`services/numbers/handlers/numbers_inline.py`](/Users/CyberZone/PycharmProjects/shop_project/services/numbers/handlers/numbers_inline.py)
- [`services/numbers/manager.py`](/Users/CyberZone/PycharmProjects/shop_project/services/numbers/manager.py)

Capabilities:

- Temp numbers
- Rental numbers
- Unlimited rental variants
- Inline country/state/service search
- Provider comparison
- Markup handling
- Balance-aware provider filtering

Current provider naming in UX:

- `Alpha`
- `Bravo`
- `Charlie`
- `Delta`
- `Echo`
- `Foxtrot`

### Proxies

Primary files:

- [`services/proxies/handlers/proxy_flow.py`](/Users/CyberZone/PycharmProjects/shop_project/services/proxies/handlers/proxy_flow.py)
- [`services/proxies/handlers/proxy_inline.py`](/Users/CyberZone/PycharmProjects/shop_project/services/proxies/handlers/proxy_inline.py)
- [`services/proxies/keyboards/proxy_kb.py`](/Users/CyberZone/PycharmProjects/shop_project/services/proxies/keyboards/proxy_kb.py)
- [`services/proxies/catalog_cache.py`](/Users/CyberZone/PycharmProjects/shop_project/services/proxies/catalog_cache.py)
- [`services/proxies/manager.py`](/Users/CyberZone/PycharmProjects/shop_project/services/proxies/manager.py)

Capabilities:

- Country/state/city style location selection
- Inline search for countries and sub-locations
- Unlimited and consumptive proxy flows
- Provider-specific ordering and reconfiguration
- Proxy telemetry and validation jobs

### Cards Bot

Primary files:

- [`services/cards_bot/handlers.py`](/Users/CyberZone/PycharmProjects/shop_project/services/cards_bot/handlers.py)

Current status:

- Live bot area exists and is in use
- Future phone verification feature is intended for this bot only

### Owner / Reseller Operations

Primary files:

- [`handlers/admin_services.py`](/Users/CyberZone/PycharmProjects/shop_project/handlers/admin_services.py)
- [`handlers/reseller_recharge.py`](/Users/CyberZone/PycharmProjects/shop_project/handlers/reseller_recharge.py)
- [`handlers/verify_reseller.py`](/Users/CyberZone/PycharmProjects/shop_project/handlers/verify_reseller.py)

Capabilities:

- Owner panel
- Reseller recharge and wallet operations
- Broadcast posting to the configured bot channel
- Provider alerts
- Support routing
- Bot/channel verification for reseller bots

## Deployment Notes

Current deployment paths discussed and used:

- Local development and manual bot runs
- Railway background deployment from GitHub `main`

Important constraint:

- Only one live polling instance per bot token should run at once
- If local and Railway both run the same token, Telegram returns `TelegramConflictError`

## Sentry

Sentry is configured through:

- [`.env`](/Users/CyberZone/PycharmProjects/shop_project/.env)
- [`utils/sentry_reporting.py`](/Users/CyberZone/PycharmProjects/shop_project/utils/sentry_reporting.py)
- [`utils/sentry_issues.py`](/Users/CyberZone/PycharmProjects/shop_project/utils/sentry_issues.py)

Usage:

- Runtime error ingestion
- Manual issue review and resolution through Sentry API

## Current Engineering Direction

The project direction in this phase is:

- Keep existing features intact
- Improve UX consistency
- Reduce noisy operational errors
- Keep inline search reliable
- Improve deployment discipline
- Add tightly scoped new features only when they do not destabilize current flows

## Near-Term Priorities

- Verify Railway deploy is picking up the latest `main`
- Keep proxy inline flows stable
- Keep reply keyboard removal consistent before inline-keyboard flows
- Avoid duplicate bot polling instances
- Continue documenting product decisions inside `docs/`
