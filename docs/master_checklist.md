# Master Checklist

Last updated: 2026-03-24
Source: `docs/feature_closure_roadmap.md`

## How to read this file

- `[ ]` not closed
- `[~]` in progress / usable but still open
- `[x]` closed enough for current project scope

This checklist is for engineering closure, not marketing release status.

## 1. Runtime and operations

- [x] Separate runtime entrypoints exist for owner bot and reseller/customer manager
- [x] Single-instance protection exists for `bot_manager.py`
- [x] Polling restart logic exists when bot set changes
- [x] Scheduler loop exists for recurring maintenance jobs
- [x] Startup index bootstrap exists
- [x] Telegram error log routing is working (DB failure-safe + loop-safe shutdown)
- [x] Telegram error logger shutdown is loop-safe (no noisy `event loop is closed` crash cascade)
- [x] Sentry or equivalent hosted error tracking is integrated
- [x] Provider balance alerts are routed to owner group/topic (group-only target enforcement)
- [x] Hosted deployment runbook is finalized

## 2. Owner/Admin panel

- [x] Unified owner panel exists
- [x] Owner dashboard exists
- [x] Finance category exists
- [x] Settlements category exists
- [x] Audit category exists
- [x] System category exists
- [x] Reseller-scoped quick actions exist
- [x] Owner payment methods management exists
- [x] Owner exchange rate management exists
- [x] Log target bind exists
- [x] Balance alert target bind exists
- [x] Owner panel copy/text is clean and consistent
- [x] Legacy slash-command dependency is fully reduced

## 3. Reseller panel

- [x] Reseller keyboard-first panel exists
- [x] Reseller dashboard exists
- [x] Balance view exists
- [x] Stats view exists
- [x] Recharge request review exists
- [x] Core topup flow exists
- [x] Adjust user balance flow exists
- [x] Settings flow exists
- [x] Payment method setup exists
- [x] Payment topic bind exists
- [x] Exchange rate setup exists
- [x] Reseller panel reporting is complete enough
- [x] Reseller panel copy/text is clean and consistent

## 4. End-user surface

- [x] Main menu keyboard exists
- [x] Language selection flow exists
- [x] Subscription gate exists
- [x] Start flow exists
- [x] Balance/recharge user flow exists
- [x] Settings/support UX is finalized
- [x] User-facing text quality is finalized

## 5. Financial system

- [x] Mongo wallets are the source of truth
- [x] Immutable ledger entries exist
- [x] Core purchase accounting exists
- [x] Core refund accounting exists
- [x] Custom purchase accounting exists
- [x] Custom refund accounting exists
- [x] User recharge credit flow exists
- [x] Reseller main topup credit flow exists
- [x] Recharge idempotency and stuck-processing recovery exist
- [x] Proof cleanup exists
- [x] Settlement draft generation exists
- [x] Settlement preview exists
- [x] Settlement confirmation exists
- [x] Settlement payment confirmation exists
- [x] Financial lock middleware exists
- [x] Financial anomaly scan exists
- [x] Financial CSV export exists
- [x] Manual adjustment operator UX is finalized
- [x] Long-term anomaly monitoring is finalized

## 6. Recharge and proof workflows

- [x] User recharge request creation exists
- [x] Reseller main topup request creation exists
- [x] Reseller review flow exists
- [x] Need-more-proof flow exists
- [x] Proof reupload-on-same-request exists
- [x] Owner review of reseller topups exists
- [x] Recovery for stuck processing requests exists
- [x] Recharge UI copy is finalized

## 7. Numbers subsystem

- [x] Temp vs rental entry exists
- [x] Country selection exists
- [x] Service selection exists
- [x] Provider selection exists
- [x] Temp purchase exists
- [x] Temp SMS wait flow exists
- [x] Temp recovery sweep exists
- [x] Temp refund flow exists
- [x] Rental purchase exists
- [x] Rental protection sweep exists
- [x] Unprovisioned order recovery exists
- [x] Provider capability matrix exists
- [x] Provider balance filtering exists
- [x] Numbers pricing cache exists
- [x] Success-rate enrichment exists
- [x] TextVerified specialized flow exists
- [x] SMSPool compatibility/fallback exists
- [x] SMS-Man provider integration exists
- [x] TellABot provider integration exists
- [x] HeroSMS provider integration exists
- [x] Numbers inline search exists
- [x] Stale temp-order trust gate no longer blocks new requests incorrectly
- [x] Callback answer path tolerates `query is too old / invalid` safely
- [x] Numbers UX copy/context lines are fully polished
- [x] Numbers Arabic text is fully clean enough for current scope
- [x] Numbers hardcoded text is fully migrated to translations for user-facing flows

## 8. Proxy subsystem

- [x] Proxy catalog aggregation exists
- [x] Provider normalization exists
- [x] 9Proxy provider integration exists
- [x] 4G provider integration exists
- [x] Proxy markup policy exists
- [x] Hide-unpriced-offers policy exists
- [x] Rent proxy flow exists
- [x] Refresh/change flow exists
- [x] Change+check pricing exists
- [x] Quality gate exists
- [x] Risk/compliance engine is production-grade
- [x] Proxy UI/UX is finalized
- [~] Proxy flows are deeply validated against live provider behavior

## 9. Custom services

- [x] Tree data model exists
- [x] Folder/endpoint builder exists
- [x] Move/rename/reorder exists
- [x] Activate/deactivate exists
- [x] Clone/template path exists
- [x] Delivery text/file flow exists
- [x] Builder UX is finalized
- [x] Builder copy/text is finalized

## 10. Game store

- [x] G2Bulk client exists
- [x] Catalog snapshot cache exists
- [x] Gift categories list exists
- [x] Game topup listing exists
- [x] Store section entry exists
- [~] Full order depth is finalized
- [x] Game store UX is finalized
- [~] Game store is hardened to the same level as numbers/finance

## 11. Create bot / onboarding

- [x] Bot creation request intake exists
- [x] Approval path exists
- [x] Post-approval setup path exists
- [x] Create Bot policy is frozen
- [x] Reseller setup readiness rules are frozen
- [x] Create Bot UX is finalized end-to-end

## 12. Cross-cutting infrastructure

- [x] Mongo primary datastore is stable
- [x] Redis secondary user cache wiring is fixed
- [x] User cache invalidation exists for critical user fields
- [x] Interaction lock middleware exists
- [x] Version gate middleware exists
- [x] Permission layer exists
- [x] Beta mode toggles exist
- [x] Usage stats layer is complete enough
- [x] Translation layer is clean enough for current scope
- [x] Hardcoded UI text migration is complete for user-facing flows
- [x] Testing-mode provider visibility policy is finalized (show-all includes non-buyable/test-visible providers)

## 16. Legacy and cleanup candidates

- [x] Removed unused legacy inline router file (`handlers/inline_query_handlers.py`)

## 13. Release blockers

- [x] Harden proxy risk/compliance path
- [x] Decide hosted observability stack: Telegram logs + optional Sentry
- [x] Finish numbers UX/context polish
- [x] Refine Create Bot/onboarding UX around the frozen policy

## 14. Close-now priorities

- [x] Owner/reseller/numbers UX polish pass
- [x] Proxy hardening pass
- [x] Create-bot UX polish pass
- [x] Sentry deployment activation pass

## 15. Current practical verdict

- `Closed enough now`: runtime, finance, recharge, owner finance operations
- `Strong but still open`: proxy/game-store live-provider behavior validation
- `Beta-ready but not closed`: operational hardening backlog below
- `Main shared blocker`: production operations maturity (CI, backups, observability depth)

## 17. Post-Closure Engineering Backlog (New)

### 17.1 Testing and quality gates

- [x] Add integration tests for owner/reseller handlers (`handlers/admin_services.py`, `handlers/reseller_recharge.py`) with callback flows
- [x] Add end-to-end tests for Create Bot flow (`handlers/verify_reseller.py`) with approval/rejection branches
- [x] Add regression tests for custom services builder edge cases (move/reorder/delete races)
- [x] Add game-store voucher/topup tests for delayed provider confirmation and missing delivery payload
- [x] Standardize fuzzy matching dependencies (prefer one engine; remove redundant `fuzzywuzzy`/Levenshtein path if unused)
- [x] Add CI workflow to run lint + selected pytest suite on every push

### 17.2 Production operations

- [x] Add health-check endpoint or command for Mongo/Redis/provider connectivity snapshot
- [x] Add backup/restore runbook for Mongo data and perform a documented restore drill
- [x] Add log retention/rotation policy for local runtime logs and alert artifacts
- [x] Add incident response playbook (who, where, first 15 minutes)

### 17.3 Security and secrets

- [x] Rotate exposed API keys/tokens and enforce periodic rotation cadence
- [x] Move sensitive runtime secrets to deployment secret manager (avoid long-lived `.env` on prod hosts)
- [x] Add startup guard that warns/fails on placeholder/weak secrets in production mode

## 18. Deferred Wishlist (Not Near-Term)

- [x] Deferred proxy product/scheduling ideas are tracked in:
`docs/WISHLIST_DEFERRED.md`
- [x] Confirmed project decision: advanced proxy queueing/rotation/fairness monetization ideas are postponed and not planned for near-term implementation.

### 17.4 Performance and resilience

- [x] Add provider timeout/retry matrix docs and enforce per-provider jitter/backoff policy
- [x] Add load test scenario for polling loop + scheduler jobs under multi-bot load
- [x] Add idempotency/duplicate-processing audit for critical callbacks with simulated rapid user clicks

### 17.5 Data and lifecycle hygiene

- [x] Add archival policy for stale orders/events/telemetry collections
- [x] Add periodic cleanup job metrics (rows deleted, duration, failures) to owner ops report
- [x] Add schema/version marker for critical collections to ease future migrations
