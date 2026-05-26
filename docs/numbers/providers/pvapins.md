# PVAPins Provider API

Status: partial; current public docs show polling for SMS delivery  
Adapter: `services/numbers/providers/pvapins_provider.py`  
Provider code: `pvapins`

## Base And Auth

Base URL:

```text
https://api.pvapins.com/user/api
```

Auth:

- Authenticated endpoints send API key in `customer`.
- Local setting name: `pvapins_key`.
- Optional override: `pvapins_base_url`.

## Temporary Numbers

| Operation | Method | Endpoint | Params |
| --- | --- | --- | --- |
| Load countries | GET | `load_countries.php` | none |
| Load apps for country | GET | `load_apps.php` | `country_id` |
| Get rates | GET | `get_rates.php` | `customer`, `country` |
| Get number | GET | `get_number.php` | `customer`, `app`, `country`, optional `operator`, optional reuse `number` |
| Get SMS | GET | `get_sms.php` | `customer`, `number`, `country`, `app`, optional `operator` |
| Reject number | GET | `get_reject_number.php` | `customer`, `number`, `country`, `app`, optional `operator` |
| Balance | GET | `get_balance.php` | `customer` |
| History | GET | `get_history.php` | `customer` |

Operator/combine behavior:

- If `operator` is present, `app` must be the group/combine name.
- If `operator` is omitted, `app` must stay the full app name.
- Use the same `app` + `operator` pair on buy, SMS, and reject calls.

## Rental Numbers

The latest supplied PVAPins page documents rental purchase as:

```text
get_number.php?customer=YOUR_API_KEY&app=APP_NAME&country=COUNTRY_NAME&is_rent=1
```

Current adapter behavior:

- Rental countries: `load_countries.php?is_rent=1`.
- Rental apps: `load_apps.php?country_id=...&is_rent=1`.
- Rental purchase: `get_number.php` with `is_rent=1`.
- Rental SMS: `load_rent_code.php`.
- Rental info: `load_rent.php`.
- Rental reject/release: `reject_rent.php`.
- Rental renew: `rent_renew_number.php`.

The rental management endpoints above came from the previously supplied PVAPins API page. If PVAPins has replaced them with newer endpoints, bring that section.

## Webhooks

No PVAPins webhook was present in the supplied pages. The current page explicitly says to poll:

```text
get_sms.php
```

Local generic route exists, but it should not be considered usable until PVAPins confirms callback support:

```text
POST /api/v1/provider-webhooks/pvapins
```

## Missing Or Needs Live Verification

- PVAPins webhook/callback docs, if they exist.
- Current full rental reference for SMS, info, reject, and renew endpoints.
- One funded test to confirm `get_number.php` with `is_rent=1` returns the same shape we parse for rentals.

