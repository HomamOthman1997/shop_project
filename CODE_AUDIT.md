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

### ✅ Security posture (separate pass, commits 30f69de/6cf416e) — see [security-review] memory
Verified sound: scrypt+salt passwords w/ constant-time compare; hashed session tokens; double-submit
CSRF; principal derived server-side (no reseller_id spoofing); ObjectId/str id coercion (no `_id`
injection); HMAC-signed price quotes (no price tampering); every `owner_*` handler gates on
`require_website_owner`; path-traversal-safe static serving. Hardened: HSTS + Permissions-Policy +
session revocation on password change.

---

## Notes / open recommendations (not code-broken)
- HSTS also at Cloudflare edge (covers API responses).
- Dedicated secret for the digital quote signer (currently derived from bot token).
- Referral system is a config-only scaffold (`referral_config_repo.py` + flags) with no reward logic.
- Rotate API keys exposed earlier in chat (G2Bulk / SteamGridDB).
