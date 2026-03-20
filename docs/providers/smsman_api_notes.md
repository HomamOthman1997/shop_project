# SMS-Man API Notes (Integrated Provider)

Base:
- `https://api.sms-man.com/control`

Auth:
- `token` query parameter (from `SMSMAN_KEY` / `settings.smsman_key`)

Implemented endpoints:
- `get-balance`
- `countries`
- `applications`
- `get-prices`
- `get-number`
- `get-sms`
- `set-status`

Temporary number flow:
1. Resolve service -> `applications`
2. Resolve country -> `countries`
3. Price -> `get-prices`
4. Buy -> `get-number`
5. Poll SMS -> `get-sms`
6. Cancel/close -> `set-status` (`reject`, fallback `close`)

Notes:
- Integrated as **temporary numbers only** (not rental).
- Country mapping translates project country codes to SMS-Man country IDs.
- Service mapping supports ID/code/name matching with fuzzy fallback.

Important pricing note (must-read):
- SMS-Man `get-prices` cost units may differ by account/provider behavior (RUB vs USD vs cents-like values).
- We currently apply configurable conversion in code, but this is **not considered fully verified** without live purchase calibration.
- Final validation must be done by funded real tests:
  1) read balance before
  2) buy real number
  3) read balance after
  4) compare actual deducted amount vs displayed bot price
- Until this live calibration is completed on funded account, SMS-Man shown prices are treated as provisional.
