# Code Audit — phantom-app.net

A line-by-line review. **Document first, fix later** — findings are logged here as we
read; nothing is changed during the read pass. Fixes happen only after review/agreement.

Severity: 🔴 bug/risk · 🟠 contradiction · 🟡 dead/unused · 🔵 refactor · 💡 idea
Status: `open` · `fixed` · `wontfix (intentional)` · `deferred`

---

## Coverage tracker

Big generated **data** files are skipped (not logic): `services/numbers/data/*_services.py`.

| Area | File | Lines | Reviewed |
|---|---|---|---|
| Config | `config.py` | 321 | ✅ |
| Auth | `services/platform/website_auth.py` | ~750 | ✅ (security pass) |
| Auth | `services/platform/api_auth.py` | 87 | ✅ |
| Money | `services/digital_products/api.py` | 1572 | ◑ core paths |
| eSIM | `services/digital_products/esim_web.py` | ~180 | ✅ (authored) |
| Notif | `database/notifications_repo.py` | ~120 | ✅ |
| Chat | `database/customer_conversations_repo.py` | ~140 | ✅ |
| Owner API | `services/platform/owner_api.py` | 3602 | ◑ partial |
| Numbers | `services/numbers/*` | ~big | ⬜ |
| Bot handlers | `handlers/*` | ~23k | ⬜ |
| DB repos | `database/*` | ~9k | ◑ partial |

Legend: ✅ done · ◑ partial · ⬜ not started

---

## Findings

### 🟠→✅ F1. Two divergent owner manual-execution keyboards — **intentional, NOT a bug**
`services/digital_products/api.py:723 _manual_execution_markup` omits the "⚡ Smart" button
that `handlers/store_sections.py:_manual_topup_notification_payload` shows.
**Verified (`create_order` 1410-1468):** the website auto-runs smart routing *before* notifying
the owner, so `_notify_owner_manual_order` only fires after smart already ran (future-redeem /
exhausted / manual fallback) — re-offering Smart would be pointless. The bot offers Smart because
it doesn't auto-run it. **Status: wontfix (intentional). Do not "align" them.**

### 🟡→✅ F2. Notifications collection grew unbounded
No TTL → storage grows forever. **Fixed** (commit e360748): TTL index on `read_at`
(read notifications purge 30d after read; unread kept). Status: fixed.

### 🟡 F3. Identity document size cap is unreachable
`website_auth.py _IDENTITY_DOC_MAX = 5MB`, but aiohttp's default `client_max_size` is 1MB,
so a >1MB JSON body is 413'd before the validator runs. Harmless (frontend compresses to <1MB),
but the 5MB cap is dead. Options: lower cap to ~900KB to match reality, or raise the route's
`client_max_size`. Low priority. Status: open.

### 🔵 F4. eSIM helper duplication (bot vs website)
`esim_web.py` re-implements `_esim_package_info_list` / `_esim_service_ref` / `_esim_price_to_units`
/ `_esim_extract_profiles` / `_esim_query_profiles_wait` that also live in
`handlers/store_sections.py`. Intentional (avoid importing aiogram into the web API) but a
divergence risk. Safe refactor: move the pure helpers to a shared `esim_route_service`-level
module and have the bot import them. Touches the live bot — do carefully. Status: deferred.

### 🔴 B1. Bare `except:` swallows everything
`utils/usage_stats_manager.py:16` — `except:` on a JSON load catches `KeyboardInterrupt`/`SystemExit`
too. Should be `except (json.JSONDecodeError, OSError):`. Minor (local-file fallback). Also: this whole
module is **file-based** (`data/usage_stats.json`) → on Railway's ephemeral FS it doesn't persist, and
the DB equivalent (`usage_stats_repo`) exists → likely **legacy/dead module**. Verify + consider removing. Status: open.

### ✅ Codebase cleanliness (positive)
Whole-repo scan: **1** bare except (above), **0** `== None`/`!= None` (all use `is None`), **0**
TODO/FIXME/HACK/XXX/BUG markers. No accumulated debt markers — tidy.

### ✅ Security posture (separate pass, commits 30f69de/6cf416e) — see [security-review] memory
Verified sound: scrypt+salt passwords w/ constant-time compare; hashed session tokens; double-submit
CSRF; principal derived server-side (no reseller_id spoofing); ObjectId/str id coercion (no `_id`
injection); HMAC-signed price quotes (no price tampering); every `owner_*` handler gates on
`require_website_owner`; path-traversal-safe static serving. Hardened: HSTS + Permissions-Policy +
session revocation on password change.

---

## Dead code (automated scan — 58 module-level functions with 0 references)

Method: AST-extract every module-level `def`/`async def` in `services/`, `database/`, `utils/`
(skip generated `data/*_services.py`, decorated handlers, `test_*`, dunders), then count
name occurrences across **all** `.py`. `refs=1` (or 0 external) = only the definition exists.
Sampled 7 → all confirmed 0 external refs. Reliable, but verify per-item before deleting
(dynamic dispatch / ops-cron / kept-as-API can hide a use).

### 🟡 D1. Confirmed dead, safe to remove (high confidence)
- `database/website_auth_repo.py:234 get_identity_document` + `:238 delete_identity_document`
  — **dead code I introduced**: `owner_api.py` serves/purges the doc via `db.identity_documents`
  **directly** (lines 2635, 2693), so these repo helpers are never called. (`store_identity_document` IS used.)
- `database/referral_config_repo.py:37 update_referral_config` — referral is a config-only scaffold; no caller.

### 🟡 D2. Dead inside the **disabled** numbers mini-app (`numbers_miniapp_enabled=False`)
~14 functions in `services/numbers/miniapp.py` (e.g. `_can_quote_temp_offer`, `_can_quote_voice_offer`,
`_can_quote_rental_option`, `_refresh_rental_order`, `_request_second_code_for_order`,
`_retry_pending_temp_refund`, `_miniapp_rental_option_candidates`, `_provider_status_text`,
`_provider_failure_should_retry`, `_rental_duration_label`, `_rental_option_match_key`,
`_miniapp_recommended_provider_code`, `_provider_raw_is_empty`, `_recharge_status_label`).
**Recommendation: leave until the mini-app's fate is decided** (don't gut a feature that may be re-enabled).

### 🟡 D3. Other dead candidates — review individually before removal
- `database/bots_repo.py:96 get_active_bots`, `:100 deactivate_bot`
- `database/cardex_repo.py:179 get_cardex_wallet`, `database/lifecycle_repo.py:48 get_last_cleanup_metrics`,
  `database/usage_stats_repo.py:31 get_top_usage`
- `services/digital_products/catalog_service.py:131 _looks_game`, `:540 _text_similarity`, `:548 _token_overlap`
- `services/digital_products/esim_route_service.py:327 _rows_from_source`, `:331 _coverage_map_from_source`,
  `:504 _single_country_best`, `:712 package_button_label`
- `services/digital_products/miniapp.py` (disabled): `_gift_service_key_legacy`, `_is_generic_chat_category`,
  `_is_generic_subscription_category`, `_provider_label`
- `services/numbers/api.py:210 _api_recharge_per_credit`, `services/numbers/manager.py:347 provider_supports_temp`,
  `services/numbers/pricing_policy.py:25 _configured_floors`
- keyboards: `core_numbers_kb.py` (`_provider_success_rate_label`, `_duration_price_label`, `rental_home_kb`,
  `state_kb`), `proxy_kb.py` (`_provider_success_label`, `proxy_period_kb`)
- proxies: `proxy_flow.py` (`_proxy_filters_text`, `_available_proxy_durations`, `_proxy_duration_hint`),
  `risk_engine.py:65 _extract_host`
- cards: `cards_bot/handlers.py` (`_is_owner`, `_pricing_rule_admin_line`, `_legacy_card_summary_text_without_price`),
  `cards_bot/lona_pricebook.py:131 _market_matches`
- `services/landing_page.py:1874 _showcase_tiles`, `utils/core_service_guard.py:9 core_service_paused_text`,
  `utils/fuzzy_search.py:3 fuzzy_find`
- ⚠️ **verify (may be ops/cron-invoked, don't assume):** `utils/sentry_ai_ops.py` (`ai_status_text`,
  `analyze_sentry_issues_with_ai`), `utils/sentry_issues.py:28 fetch_sentry_project_issues`,
  `services/platform/telegram_webapp_auth.py:106 optional_telegram_webapp_auth`

> Note: dead code doesn't *run*, so it's low-risk clutter — but it hides bugs and confuses readers.
> Removal is safe **only after** per-item ref-check + a green test run. Fix in the agreed fix-phase.

---

## Notes / open recommendations (not code-broken)
- HSTS also at Cloudflare edge (covers API responses).
- Dedicated secret for the digital quote signer (currently derived from bot token).
- Referral system is a config-only scaffold (`referral_config_repo.py` + flags) with no reward logic.
- Rotate API keys exposed earlier in chat (G2Bulk / SteamGridDB).
