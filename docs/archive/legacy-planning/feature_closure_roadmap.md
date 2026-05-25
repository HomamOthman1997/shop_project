# Feature Closure Roadmap

Last updated: 2026-03-23
Scope: current tracked source tree in `shop_project`

## Rating model

- `100%` = operationally closed for the current project scope
- `85-95%` = strong, usable, low-risk, but still has cleanup or polish debt
- `70-84%` = feature-complete core flow, but still needs hardening/tests/UX cleanup
- `50-69%` = partially implemented and usable in limited cases
- `<50%` = exploratory, placeholder, or missing key production requirements

Percentages below are engineering closure estimates from the current codebase, not business readiness metrics.

## Project-wide status

| Domain | Closure | State | Notes |
|---|---:|---|---|
| Runtime topology | 94% | Near closed | `bot.py` + `bot_manager.py` split is clear and stable with wider scheduler coverage |
| Owner/Admin panel | 91% | Near closed | Keyboard-first panel exists; main remaining debt is reporting/ops polish |
| Reseller panel | 92% | Near closed | Core panel exists; reporting coverage is now broad enough for ops use |
| Financial system | 95% | Near closed | Ledger model, audit, settlements, lock, export all present |
| Recharge/proof workflows | 90% | Near closed | Review, proof reupload, recovery, cleanup exist |
| Numbers subsystem | 87% | Near closed | Deep implementation; remaining debt is final UX/context polish rather than bulk text cleanup |
| Proxy subsystem | 88% | Near closed | Core catalog/rent/change flow exists with risk checks, telemetry, and validation sweeps |
| Custom services | 89% | Near closed | Tree builder and delivery flow exist; major text debt is now cleaned |
| Game store | 88% | Near closed | Catalog integration + pending-order recovery + validation sweeps are active |
| Translation/i18n layer | 88% | Near closed | Clean translation source exists; remaining debt is residual internal strings and ongoing copy maintenance |
| Logging/ops observability | 94% | Near closed | Telegram logs + alert routing + Sentry runtime wiring are active |
| Test coverage posture | 84% | Strong but open | Good targeted coverage with additional game-store recovery tests |

## Recent delta since 2026-03-20

- Added safe callback answer handling for old/invalid Telegram callback queries in `services/numbers/handlers/core_numbers_buy.py`.
- Tightened temp trust-gate activity checks to ignore stale waiting orders in `services/numbers/handlers/core_numbers_buy.py`.
- Hardened telegram error reporting shutdown flow (`_closing` guard, loop-closed checks, safe scheduling) in `utils/telegram_error_reporting.py`.
- Added DB-failure-safe fallback in `database/bot_logs_repo.py` so log routing does not raise during transient Mongo outage.
- Runtime inline router wiring is explicitly active in `bot_manager.py` for numbers/proxy inline flows.
- Removed `handlers/inline_query_handlers.py` (legacy, not wired in current runtime).
- Finalized testing-mode provider visibility behavior (show non-buyable providers when marked testing-visible).
- Enforced group-only routing for provider balance alerts in `bot_manager.py`.
- Added deployment operations guide in `docs/HOSTED_DEPLOYMENT_RUNBOOK.md`.

## Runtime and operations

| Feature | Main files | Closure | State | Gap to close |
|---|---|---:|---|---|
| Single owner bot runtime | `bot.py` | 92% | Near closed | Needs long-term hosted monitoring only |
| Multi-reseller polling manager | `bot_manager.py` | 93% | Near closed | Stable; main remaining risk is hosting/runtime environment |
| Polling singleton guard | `bot_manager.py` | 95% | Near closed | Good enough |
| Scheduler loop | `bot_manager.py` | 90% | Near closed | Jobs exist; no external scheduler dashboard |
| Index bootstrap on startup | `bot.py`, `bot_manager.py`, `database/*` | 92% | Near closed | Good enough |
| Telegram error reporting | `utils/telegram_error_reporting.py` | 82% | Strong but open | Useful, but still not full observability |
| Group/topic routing for logs | `database/bot_logs_repo.py`, `handlers/admin_services.py` | 88% | Near closed | Good enough for current phase |
| Provider balance alerts | `bot_manager.py`, `database/provider_balance_alert_repo.py` | 84% | Strong but open | Routing fixed; still basic alert logic |

## Owner/Admin

| Feature | Main files | Closure | State | Gap to close |
|---|---|---:|---|---|
| Unified owner panel | `handlers/admin_services.py` | 93% | Near closed | Main debt is command compatibility cleanup and richer ops reporting |
| Owner dashboard | `handlers/admin_services.py` | 88% | Near closed | Good snapshot; can still grow richer reporting |
| Finance category | `handlers/admin_services.py` | 92% | Near closed | Strong |
| Settlements category | `handlers/admin_services.py` | 93% | Near closed | Strong |
| Audit category | `handlers/admin_services.py` | 91% | Near closed | Strong |
| System category | `handlers/admin_services.py` | 86% | Near closed | Good, but operational UX can still improve |
| Quick reseller-scoped actions | `handlers/admin_services.py` | 85% | Near closed | Strong enough |
| Owner payment methods management | `handlers/admin_services.py`, `database/owner_payment_settings_repo.py` | 89% | Near closed | Strong |
| Bind owner notification target | `handlers/admin_services.py` | 88% | Near closed | Good enough |
| Bind logs topic | `handlers/admin_services.py`, `database/bot_logs_repo.py` | 87% | Near closed | Good enough |
| Bind provider alert target | `handlers/admin_services.py`, `database/provider_balance_alert_repo.py` | 86% | Near closed | Good enough |
| Legacy slash commands for owner | `handlers/admin_services.py` | 93% | Near closed | Legacy slash actions now redirect to Owner Panel; keyboard-first is primary |

## Reseller

| Feature | Main files | Closure | State | Gap to close |
|---|---|---:|---|---|
| Reseller main panel keyboard | `keyboards/reseller_main_menu.py` | 88% | Near closed | Good enough |
| Reseller dashboard | `handlers/reseller_recharge.py` | 85% | Strong but open | Stats good, but still can become more complete |
| Balance view | `handlers/reseller_recharge.py` | 88% | Near closed | Good enough |
| Stats view | `handlers/reseller_recharge.py` | 84% | Strong but open | Useful, but not yet exhaustive |
| Recharge requests review | `handlers/reseller_recharge.py`, `database/recharge_repo.py` | 91% | Near closed | Strong |
| Core topup flow | `handlers/reseller_recharge.py` | 89% | Near closed | Strong |
| Adjust user balance | `handlers/reseller_recharge.py`, `utils/financial_manager.py` | 83% | Strong but open | Sensitive path; policy/UX can improve |
| Reseller settings | `handlers/reseller_recharge.py`, `database/reseller_settings_repo.py` | 88% | Near closed | Functionally there; remaining gap is setup-policy clarity, not text debt |
| Payment method setup | `handlers/reseller_recharge.py` | 88% | Near closed | Strong |
| Payment topic bind | `handlers/reseller_recharge.py` | 89% | Near closed | Strong |
| Exchange rate setup | `handlers/reseller_recharge.py` | 86% | Near closed | Good enough |
| Setup readiness guard | `utils/reseller_setup_guard.py` | 89% | Near closed | Blocking policy is now explicit: usable payment methods + payment routing |

## End user

| Feature | Main files | Closure | State | Gap to close |
|---|---|---:|---|---|
| Main menu keyboard | `keyboards/main_menu_kb.py`, `handlers/main_menu.py` | 86% | Near closed | Good enough |
| Language selection | `handlers/language.py`, `keyboards/language_kb.py` | 86% | Near closed | Functionally fine; translation source is now clean enough |
| Subscription/channel gate | `handlers/subscription.py`, `keyboards/subscription_kb.py` | 78% | Open but usable | Good enough for current use, not deeply hardened |
| Start flow | `handlers/start.py` | 86% | Near closed | Handles active order notice and routing; remaining gap is onboarding policy clarity |
| Balance/recharge UX | `handlers/main_menu.py` | 86% | Near closed | Strong |
| Support/settings entrypoints | `handlers/main_menu.py` | 81% | Strong but open | Serviceable; major text debt is now cleaned |
| Create bot entry | `handlers/verify_reseller.py`, `keyboards/main_menu_kb.py` | 83% | Strong but open | Intake policy is clearer and approval follow-up is better; remaining gap is end-to-end UX polish |

## Financial

| Feature | Main files | Closure | State | Gap to close |
|---|---|---:|---|---|
| Wallet model | `database/financial_ledger.py` | 96% | Near closed | Strong |
| Immutable ledger entries | `database/financial_ledger.py` | 96% | Near closed | Strong |
| Core purchase accounting | `database/financial_ledger.py` | 95% | Near closed | Strong |
| Core refund accounting | `database/financial_ledger.py` | 94% | Near closed | Strong |
| Custom purchase accounting | `database/financial_ledger.py` | 94% | Near closed | Strong |
| Custom refund accounting | `database/financial_ledger.py` | 93% | Near closed | Strong |
| User recharge acceptance | `database/recharge_repo.py` | 94% | Near closed | Strong |
| Reseller main topup acceptance | `database/recharge_repo.py`, `database/financial_ledger.py` | 94% | Near closed | Strong |
| Recharge recovery/idempotency | `database/recharge_repo.py` | 95% | Near closed | Strong |
| Proof cleanup | `database/recharge_repo.py`, `bot_manager.py` | 92% | Near closed | Strong |
| Settlement preview/drafts | `database/financial_ledger.py`, `handlers/admin_services.py` | 94% | Near closed | Strong |
| Settlement confirm/payment confirm | `database/financial_ledger.py`, `handlers/admin_services.py` | 95% | Near closed | Strong |
| Financial lock middleware | `middlewares/financial_compliance.py` | 92% | Near closed | Strong |
| Financial anomaly scan | `database/financial_ledger.py`, `bot_manager.py` | 94% | Near closed | Includes recurring scheduler monitoring + owner alerts |
| CSV audit export | `scripts/export_financial_audit.py` | 85% | Near closed | Useful and sufficient |
| Manual financial adjustments policy | `docs/financial_model.md` | 82% | Strong but open | Policy documented, but operator UX can improve |

## Recharge and proof workflows

| Feature | Main files | Closure | State | Gap to close |
|---|---|---:|---|---|
| User recharge request creation | `handlers/main_menu.py`, `database/recharge_repo.py` | 89% | Near closed | Strong |
| Reseller topup request creation | `handlers/reseller_recharge.py`, `database/recharge_repo.py` | 89% | Near closed | Strong |
| Reseller review of user requests | `handlers/reseller_recharge.py` | 90% | Near closed | Strong |
| Need-more-proof path | `handlers/main_menu.py`, `handlers/reseller_recharge.py` | 91% | Near closed | Strong |
| Proof reupload to same request | `handlers/main_menu.py` | 88% | Near closed | Strong |
| Owner review of reseller topups | `handlers/admin_services.py` | 87% | Near closed | Strong |
| Processing timeout recovery | `database/recharge_repo.py`, `bot_manager.py` | 92% | Near closed | Strong |

## Numbers subsystem

| Feature | Main files | Closure | State | Gap to close |
|---|---|---:|---|---|
| Entry flow: temp vs rental | `services/numbers/handlers/core_numbers.py` | 89% | Near closed | Strong |
| Country/service/provider selection | `services/numbers/handlers/core_numbers.py`, `services/numbers/keyboards/core_numbers_kb.py` | 86% | Near closed | Strong |
| Temp number purchase | `services/numbers/handlers/core_numbers_buy.py` | 87% | Near closed | Strong |
| Temp SMS wait/recovery | `services/numbers/handlers/core_numbers_buy.py`, `bot_manager.py` | 90% | Near closed | Strong |
| Temp refund flow | `services/numbers/handlers/core_numbers_buy.py` | 88% | Near closed | Strong |
| Rental purchase | `services/numbers/handlers/core_numbers_buy.py` | 85% | Near closed | Strong |
| Rental protection sweep | `services/numbers/handlers/core_numbers_buy.py`, `bot_manager.py` | 90% | Near closed | Strong |
| Unprovisioned order recovery | `services/numbers/handlers/core_numbers_buy.py`, `bot_manager.py` | 89% | Near closed | Strong |
| Provider capability matrix | `services/numbers/manager.py` | 86% | Near closed | Strong |
| Provider balance filtering | `services/numbers/manager.py` | 88% | Near closed | Strong |
| Numbers pricing cache | `services/numbers/manager.py` | 85% | Near closed | Strong |
| Success-rate enrichment | `services/numbers/manager.py` | 84% | Strong but open | Solid, but still heuristic |
| TextVerified specialized flow | `services/numbers/handlers/core_numbers.py`, `services/numbers/providers/textverified_provider.py` | 87% | Near closed | Strong |
| SMSPool compatibility/fallbacks | `services/numbers/providers/smspool_provider.py` | 86% | Near closed | Strong |
| SMS-Man provider | `services/numbers/providers/smsman_provider.py` | 82% | Strong but open | Strong enough, still provider-risk dependent |
| TellABot provider | `services/numbers/providers/telabot_provider.py` | 78% | Open but usable | Sensitive to timeout/provider behavior |
| HeroSMS provider | `services/numbers/providers/herosms_provider.py` | 81% | Strong but open | Strong enough |
| Numbers inline search | `services/numbers/handlers/numbers_inline.py` | 85% | Near closed | Good enough |
| Numbers UX copy/text quality | `core_numbers*`, `utils/translations.py` | 92% | Near closed | Context and confirmation screens are now consistent and operator-facing strings are cleaner |

## Proxy subsystem

| Feature | Main files | Closure | State | Gap to close |
|---|---|---:|---|---|
| Proxy catalog aggregation | `services/proxies/manager.py` | 83% | Strong but open | Good enough |
| Provider normalization | `services/proxies/manager.py` | 80% | Strong but open | Good enough |
| 9Proxy provider | `services/proxies/providers/nine_proxy_provider.py` | 78% | Open but usable | Good enough for beta |
| 4G provider | `services/proxies/providers/fourg_proxy_provider.py` | 77% | Open but usable | Good enough for beta |
| Markup and hide-unpriced policy | `services/proxies/manager.py` | 84% | Strong but open | Good enough |
| Rent proxy flow | `services/proxies/handlers/proxy_flow.py`, `services/proxies/manager.py` | 76% | Open but usable | Needs wider operational validation |
| Refresh/change flow | `services/proxies/manager.py`, `services/proxies/handlers/proxy_flow.py` | 74% | Mid-open | Core logic exists but still provider-sensitive |
| Change+check billing | `services/proxies/manager.py` | 73% | Mid-open | Present, not deeply battle-tested |
| Quality gate | `services/proxies/risk_engine.py` | 84% | Strong but open | Blocks localhost/internal/private/invalid-port endpoints and supports IPQS reputation checks |
| Proxy inline flow | `services/proxies/handlers/proxy_inline.py` | 77% | Open but usable | Usable, with basic text cleanup done; still needs broader polish |

## Custom services

| Feature | Main files | Closure | State | Gap to close |
|---|---|---:|---|---|
| Catalog tree model | `database/custom_services_repo.py` | 90% | Near closed | Strong |
| Folder/endpoint builder | `handlers/custom_services.py` | 89% | Near closed | Strong |
| Move/rename/reorder | `database/custom_services_repo.py`, `handlers/custom_services.py` | 84% | Strong but open | Strong |
| Activate/deactivate | `database/custom_services_repo.py` | 88% | Near closed | Strong |
| Clone/template path | `database/custom_services_repo.py` | 82% | Strong but open | Good enough |
| Delivery text/file flow | `handlers/custom_services.py` | 87% | Near closed | Good enough |
| Builder UX/buttons | `handlers/custom_services.py` | 84% | Strong but open | Works; text debt is mostly cleaned, density/polish remains |

## Game store

| Feature | Main files | Closure | State | Gap to close |
|---|---|---:|---|---|
| G2Bulk client integration | `services/game_store/g2bulk_client.py` | 84% | Strong but open | Good enough with compatibility fallbacks |
| Catalog snapshot caching | `services/game_store/catalog_service.py` | 86% | Near closed | Good enough |
| Gift categories list | `services/game_store/catalog_service.py` | 76% | Open but usable | Good enough |
| Game topup list | `services/game_store/catalog_service.py` | 77% | Open but usable | Good enough |
| Store section entry flow | `handlers/store_sections.py` | 84% | Strong but open | Present; user-facing text debt is largely cleaned |
| Full order completion depth | `handlers/store_sections.py`, `services/game_store/*`, `services/game_store/recovery.py` | 80% | Strong but open | Includes background recovery for pending provider confirmations |

## Create bot / reseller onboarding

| Feature | Main files | Closure | State | Gap to close |
|---|---|---:|---|---|
| Bot creation request intake | `handlers/verify_reseller.py` | 80% | Strong but open | Core flow exists |
| Approval path | `handlers/verify_reseller.py`, `handlers/owner_requests.py` | 82% | Strong but open | Strong |
| Post-approval reseller setup | `handlers/start.py`, `utils/reseller_setup_guard.py` | 86% | Near closed | Policy is now explicit and tested; remaining gap is UI polish |
| Create Bot UI policy | `handlers/verify_reseller.py`, `keyboards/main_menu_kb.py` | 85% | Near closed | Flow is functionally stable and post-approval routing is clearer; remaining gap is final UX polish |

## Cross-cutting infrastructure

| Feature | Main files | Closure | State | Gap to close |
|---|---|---:|---|---|
| Mongo as source of truth | `database/mongo.py`, all repos | 95% | Near closed | Strong |
| Redis secondary user cache | `database/redis_client.py`, `utils/user_cache.py`, `middlewares/version_check.py` | 84% | Strong but open | Fixed wiring; now needs longer runtime observation |
| User cache invalidation | `utils/user_cache.py`, `database/user_repo.py` | 84% | Strong but open | Good enough |
| Interaction lock middleware | `middlewares/interaction_lock.py` | 86% | Near closed | Strong |
| Version gate middleware | `middlewares/version_check.py` | 80% | Strong but open | Functional; can still get cleaner policy separation |
| Permission layer | `utils/permissions.py` | 85% | Near closed | Strong |
| Beta mode toggles | `utils/beta_mode.py`, `config.py` | 80% | Strong but open | Good enough |
| Usage stats helpers | `utils/usage_stats_manager.py`, `database/usage_stats_repo.py` | 84% | Strong but open | Mongo-backed tracking is active with owner ops visibility |

## Main blockers to full closure

1. No critical blockers for current scope; remaining work is optional polish and long-horizon observation.

## Recommended closure order

### Phase 1: active closure blockers

1. Keep runtime observation dashboards active and review alerts weekly.

### Phase 2: medium-risk product gaps

1. Deepen reseller and owner statistics/reporting
2. Finish game-store operational depth
3. Validate observability flow in hosted deployment

### Phase 3: optional maturity work

1. Add richer dashboards/exports
2. Expand regression tests around onboarding and proxies
3. Continue internal-string cleanup only where it improves operator UX

## Practical reading of current closure

- `Closed enough to rely on now`: runtime, finance, recharge, owner finance panel
- `Strong and usable but still needs finishing`: optional reporting polish only
- `Usable for beta but not final`: long-horizon provider behavior observation
- `No longer a project-wide blocker`: hardcoded user-facing text migration
