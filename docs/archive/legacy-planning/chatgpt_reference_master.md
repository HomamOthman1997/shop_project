# PINNED WORKSPACE (DO NOT CHANGE)
# Canonical project path: C:\Users\CyberZone\PycharmProjects\shop_project
# Rule: verify this path before any edit/run.

# CHATGPT REFERENCE LOG (MASTER)
# Project: shop_project
# Repository: https://github.com/HomamOthman1997/shop_project
# Last code+docs reconciliation: 2026-03-19

====================================================
1) Scope
====================================================
This file is the canonical reference for the current project state.
It supersedes older chat dumps for active implementation guidance.

Historical files kept only as archive/reference:
- docs/archive/chatgpt.txt
- docs/archive/chatgpt_backup_2026-03-09.txt

====================================================
2) Current Runtime Topology
====================================================
Primary runtime entrypoints:
- bot_manager.py
- bot.py

Runtime model:
- bot_manager.py runs the reseller/customer bots through one dispatcher and scheduler loop.
- bot.py runs the owner/admin bot separately.
- MongoDB is the primary datastore.
- Redis is optional and used as a secondary cache layer.

bot_manager responsibilities:
- load verified reseller bots
- start/stop polling safely
- recharge recovery sweep
- recharge proof cleanup
- monthly settlement draft generation
- monthly settlement policy enforcement
- provider balance alerts
- rental protection sweeps
- temp recovery sweeps
- unprovisioned number order recovery

====================================================
3) Current Architecture By Domain
====================================================
A) Owner/Admin
- Canonical owner panel logic lives in handlers/admin_services.py.
- Owner access is enforced by OWNER_ID via utils/permissions.py.
- Owner panel is button-driven with categories:
  - Dashboard
  - Finance
  - Settlements
  - Audit
  - System
- Owner quick actions exist for reseller-scoped finance/settlement flows.
- Owner can bind notification targets, provider balance alert targets, and bot log targets.

B) Reseller
- Reseller flows are handled mainly in handlers/reseller_recharge.py and handlers/main_menu.py.
- Reseller panel is button-driven from keyboards/reseller_main_menu.py.
- Current reseller panel includes:
  - Dashboard
  - Balance
  - Stats
  - Recharge Requests
  - Core Topup
  - Custom Services
  - Adjust User Balance
  - Settings
- Reseller setup readiness still depends on payment method + private group routing.

C) Financial
- Financial source of truth is:
  - wallets
  - ledger_entries
  - settlements
- Canonical implementation:
  - database/financial_ledger.py
  - database/recharge_repo.py
  - utils/financial_manager.py
- Current financial model:
  - user wallet
  - reseller main wallet
- reseller custom-profit wallet
  - owner fees tracking
- Supported flows:
  - core purchase + refund
  - custom purchase + refund
  - user recharge approval
  - reseller main topup approval
  - settlement draft/preview/confirm/payment confirm
  - financial lock enforcement per reseller + bot
- Financial audit/anomaly scanning exists and is exposed in owner panel.

D) Numbers
- Numbers are a first-class subsystem under services/numbers.
- Main handlers:
  - services/numbers/handlers/core_numbers.py
  - services/numbers/handlers/core_numbers_buy.py
  - services/numbers/handlers/numbers_inline.py
- Main orchestration:
  - services/numbers/manager.py
- Current provider set in code:
  - smspool
  - textverified
  - herosms
  - telabot
  - nonvoip
- Current feature coverage includes:
  - temp purchase
  - rental purchase
  - provider choice
  - state-aware flows
  - success-rate enrichment
  - temp recovery/refund logic
  - rental protection logic
  - TextVerified rental/verification specialized flow

E) Proxies
- Proxy subsystem exists under services/proxies.
- Current active provider registry in code:
  - 9proxy
  - 4g
- Current proxy logic includes:
  - unified catalog aggregation
  - markup support
  - quality gate
  - change-only cooldown
  - change+check pricing
  - my proxies/order management flows
- Risk engine is local placeholder logic:
  - maxmind-style local gate first
  - ipqs placeholder second for gray path

F) Custom Services
- Custom catalog tree is implemented in database/custom_services_repo.py and handlers/custom_services.py.
- Supports folder/endpoint tree, endpoint inventory, delivery text/file, move/rename/deactivate, and template cloning.

G) Game Store
- Current game store integration is built around G2Bulk:
  - services/game_store/catalog_service.py
  - services/game_store/g2bulk_client.py

====================================================
4) Verified Current State From Code
====================================================
A) Owner/Admin hardening
- Owner action logic is unified in handlers/admin_services.py.
- /owner and /owner_panel open the same owner panel.
- owner_only depends on OWNER_ID only.
- Owner dashboard exists and summarizes:
  - active reseller owners
  - active bots
  - open numbers orders
  - wallet totals
  - pending recharge counts
  - settlement lock counts
  - routing status

B) Logging and notifications
- Telegram error reporting exists in utils/telegram_error_reporting.py.
- It is installed in:
  - bot.py
  - bot_manager.py
- Bot log target storage exists in database/bot_logs_repo.py.
- Owner panel system actions currently include:
  - Bind Logs Here
  - Logs Status
  - Send Test Log
- Provider balance alerts no longer fall back to owner DM by default.
- Provider balance alerts now require owner-group/topic routing and log an error if no valid group target exists.

C) Financial compliance and settlements
- Financial middleware is bot-aware and reseller-aware.
- Financial anomaly scanning exists:
  - negative wallets
  - orders missing ledger
  - accepted recharges missing ledger
- Financial reporting/export support exists in:
  - database/financial_ledger.py
  - scripts/export_financial_audit.py

D) Recharge and proof workflow
- /bind_payment_topic is implemented.
- Recharge requests are routed to reseller topic/group.
- Need More Proof workflow is implemented.
- Re-uploading proof on same request is implemented.
- Proof cleanup job is implemented.
- Owner reseller topup review workflow is implemented.

E) Numbers
- Numbers UX already contains context-building lines in the screen composition layer.
- TextVerified rental flow includes:
  - duration selection
  - renewable vs non-renewable
  - billing cycle label
  - state targeting
  - wake request
- Rental protection sweeps and temp recovery sweeps are active in bot_manager.py.
- Provider balance gating and caching exist in the manager layer.

F) Proxies
- Proxy product model is currently split by billing type:
  - fixed
  - bandwidth
- 9Proxy and 4G are the current implemented providers.
- Verify-before-delivery and change/check billing scaffolding exists.

====================================================
5) Current Keyboard-First Access Model
====================================================
Owner:
- Start command opens owner entry button.
- Main owner operations are reachable by inline keyboard categories.
- Legacy slash commands still exist for owner operations as compatibility/admin shortcuts.

Reseller:
- Main reseller actions are reachable through inline keyboard buttons.
- Settings remain reachable from reseller panel.
- Recharge routing and exchange routing are managed from reseller settings flow.

User:
- Main menu remains reply-keyboard driven.
- Numbers/proxies/services/store/balance/settings/support are reachable from main menu.

====================================================
6) Current Provider/API Documentation Inventory
====================================================
Primary local provider index:
- docs/providers/index.json

Read-first provider meta:
- docs/providers/READ_ME_FIRST.md

Current locally tracked provider references:
- G2Bulk:
  - docs/providers/manual/g2bulk_api_reference.json
- SMSPool:
  - docs/providers/manual/smspool_api_reference.json
  - docs/providers/raw/smspool_postman_collection.json
  - docs/providers/raw/smspool_postman_documenter.html
- TextVerified:
  - docs/providers/manual/textverified_api_reference.json
  - docs/providers/raw/textverified_openapi_v2.json
- HeroSMS:
  - docs/providers/manual/herosms_api_reference.json
  - docs/providers/raw/herosms_openapi_en.json
- Non-VoIP:
  - docs/numbers/providers/nonvoip.md
- Tellabot:
  - docs/providers/manual/telabot_api_reference.json

====================================================
7) Current Open Items
====================================================
These remain open after reading the current codebase.

A) Translations / mojibake cleanup
- utils/translations.py still contains mojibake-corrupted Arabic strings.
- Some UI strings still rely on runtime repair instead of clean source text.

B) Hardcoded text migration
- Many owner/reseller/numbers/custom texts are still hardcoded in handlers.
- translations.py is not yet the sole source for UI copy.

C) Documentation lag outside this file
- docs/archive/chatgpt.txt and docs/archive/chatgpt_backup_2026-03-09.txt are historical and no longer reflect the full current state.

D) Test alignment
- Tests exist across core/database/numbers/proxies.
- Full suite status was not revalidated during this documentation-only pass.
- Historical notes about test drift are no longer sufficient as the sole truth; re-run is required before release freeze.

E) Proxy risk/compliance depth
- Proxy risk engine is still placeholder-grade, not full external reputation integration.

====================================================
8) Product and Implementation Decisions Still Active
====================================================
A) Proxy product model
- Keep two proxy product lines:
  - unlimited/fixed-style
  - usage/bandwidth-style

B) Proxy quality sequence
- maxmind stage first
- ipqs stage only for gray/uncertain path

C) Numbers / TextVerified
- Voice capability remains included in the intended product direction.
- Billing cycle remains mandatory in renewable rental path.
- Wake requests remain important.
- Webhooks remain deferred.

D) Financial safety
- No direct balance mutations outside wallet/ledger logic.
- Auditability and idempotent recharge acceptance remain required.

====================================================
9) Operational Notes
====================================================
Canonical workspace:
- C:\Users\CyberZone\PycharmProjects\shop_project

Main local run commands:
- python bot_manager.py
- python bot.py

Git repository:
- https://github.com/HomamOthman1997/shop_project

If polling conflicts appear:
- stop old bot_manager processes first
- keep only one active polling manager process

====================================================
10) Security Notes
====================================================
- Keep provider keys/tokens in .env only.
- Do not commit .env.
- Do not log secrets.
- Rotate leaked credentials from old chats/files if any were ever exposed.
- Telegram log topic should be used for operational diagnostics only, not secret material.

====================================================
11) Document Control
====================================================
- This file is the primary implementation reference.
- Older chat dump files are archival only.
- Any new agreement that changes production behavior should be reflected here.
