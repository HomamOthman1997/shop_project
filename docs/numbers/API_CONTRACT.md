# Numbers API Contract

Status: draft, backed by the dedicated `services/numbers/api.py` route layer
Last updated: 2026-05-25

## Base Paths

Versioned API path:

- `/api/v1/numbers`

Legacy Mini App path:

- `/mini/numbers/api`

The versioned API path must not be a blind alias to Mini App handlers. New backend/API work should live in dedicated API modules and shared services, then the Mini App can be migrated to consume those endpoints.

## Auth

Current authentication is Telegram Mini App `initData` based.

Near-term requirement:

- keep Telegram initData auth for Mini App clients,
- add a scoped API-key/token auth path before exposing endpoints to customers,
- keep customer API auth separate from admin/operator auth.

## Public/Client Endpoints

### Health

`GET /api/v1/numbers/health`

Returns API health and version metadata.

### Bootstrap

`GET /api/v1/numbers/catalog/bootstrap`

Returns selector metadata:

- modes,
- default selection,
- services,
- countries,
- US states.

### Country Suggestions

Planned path:

`GET /api/v1/numbers/catalog/country-suggestions?mode=temp&service=telegram`

Returns ranked countries for a service/mode.

### Account

Planned path:

`GET /api/v1/numbers/account`

Returns user profile, wallet balance, and recent wallet activity.

Planned path:

`POST /api/v1/numbers/account/language`

Body:

```json
{"language": "ar"}
```

### Prices

Planned path:

`GET /api/v1/numbers/quotes?mode=temp&service=telegram&country=1&state=none`

Returns normalized provider rows with public provider IDs only. Real provider names must not be exposed to customers.

Currently supported modes:

- `temp`

Planned modes:

- `rental`
- `voice`

### Orders

Planned path:

`GET /api/v1/numbers/orders`

Returns active temp, rental, and voice orders for the authenticated user.

Planned path:

`POST /api/v1/numbers/orders`

Creates a temp, rental, or voice order depending on request payload.

Planned path:

`POST /api/v1/numbers/orders/{order_id}/refresh`

Refreshes order status/SMS/call state.

`GET /api/v1/numbers/orders/{order_id}/recording`

Downloads a call recording when available.

`POST /api/v1/numbers/orders/{order_id}/cancel`

Cancels/refunds an eligible order.

`POST /api/v1/numbers/orders/{order_id}/second-code`

Requests a second code when supported.

`POST /api/v1/numbers/orders/{order_id}/replace`

Retries/replaces using the current provider when eligible.

`POST /api/v1/numbers/orders/{order_id}/alternate`

Retries using an alternate provider when eligible.

### Rental Actions

`POST /api/v1/numbers/orders/{order_id}/sms`

Fetches rental SMS messages.

`POST /api/v1/numbers/orders/{order_id}/finish`

Finishes a rental when supported.

`POST /api/v1/numbers/orders/{order_id}/renew`

Renews a rental when supported.

`POST /api/v1/numbers/orders/{order_id}/wake`

Wakes/reactivates a rental when supported.

`POST /api/v1/numbers/orders/{order_id}/notes`

Fetches rental notes/tags when supported.

## Mini App Only For Now

These are still customer workflow endpoints but are not ready for public customer API exposure:

- `GET /api/v1/numbers/recharge`
- `POST /api/v1/numbers/recharge/submit`
- `GET /api/v1/numbers/support`
- `POST /api/v1/numbers/support/ticket`

Reason:

- recharge proof handling still depends on Telegram/operator review workflows,
- support replies still depend on Telegram chat threads.

## Required Before Customer API Exposure

- API key/token auth with scopes.
- Stable error code list.
- Idempotency keys for purchase, cancel/refund, replacement, and rental renewal.
- Rate limiting by user/API key.
- Optional webhooks for order status and SMS events.
- External docs with examples.
- Contract tests that assert response shape for `/api/v1/numbers`.
