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

Versioned API authentication uses API keys.

Accepted headers:

- `Authorization: Bearer <api-key>`
- `X-API-Key: <api-key>`

API keys are stored hashed and must carry scopes. Current scopes:

- `numbers:quotes`
- `numbers:orders:read`
- `numbers:orders:create`
- `numbers:account:read`
- `api_keys:manage`
- `*` for internal/admin keys only.

Mini App authentication remains Telegram `initData` based and is separate from customer API authentication.

## Response Format And Errors

Successful responses return:

```json
{"ok": true}
```

Errors return:

```json
{"ok": false, "code": "error_code", "message": "Human readable message."}
```

Stable error codes currently emitted by the versioned API:

- `missing_quote`
- `missing_service`
- `unsupported_mode`
- `invalid_quote`
- `expired_quote`
- `provider_unavailable`
- `provider_price_changed`
- `insufficient_balance`
- `provider_purchase_failed`
- `provider_not_available`
- `missing_scopes`
- `invalid_owner`
- `key_not_found`
- `order_not_found`

Auth middleware may also return standard HTTP `401`, `403`, and `429` responses.

## Rate Limits

Authenticated API responses include:

- `X-RateLimit-Bucket`
- `X-RateLimit-Limit`
- `X-RateLimit-Remaining`
- `X-RateLimit-Reset`

Current limits:

- `numbers:quotes`: 120 requests per minute.
- `numbers:account:read`: 60 requests per minute.
- `numbers:orders:read`: 90 requests per minute.
- `numbers:orders:create`: 30 requests per minute.
- `api_keys:manage`: 30 requests per minute.

When a limit is exceeded, the API returns HTTP `429` with `Retry-After`.

## API Key Management

These endpoints manage customer/partner API keys. They require an existing key with `api_keys:manage`.

`GET /api/v1/api-keys`

Lists keys for the authenticated reseller scope. Raw secrets are never returned.

`POST /api/v1/api-keys`

Creates a key. The raw `api_key` is returned once and must be stored by the caller.

Body:

```json
{
  "name": "customer bot",
  "scopes": ["numbers:account:read", "numbers:quotes", "numbers:orders:read", "numbers:orders:create"]
}
```

Only customer-safe scopes are accepted. Management scopes are not grantable through this endpoint unless we later add an explicit owner-only flow.

`POST /api/v1/api-keys/{key_id}/revoke`

Revokes a key in the authenticated reseller scope.

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

Currently returns API-safe identity and wallet balance:

```json
{
  "ok": true,
  "user": {"id": 123, "username": "customer", "language": "en", "joined_at": "2026-05-25T12:00:00+00:00"},
  "reseller": {"id": 123},
  "wallet": {"balance": 10.5, "currency": "USD", "balance_label": "$10.50"}
}
```

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

`GET /api/v1/numbers/orders`

Returns recent temp, rental, and voice orders for the authenticated user.

Query:

- `mode=all|temp|voice|rental`, default `all`.
- `limit=1..50`, default `20`.

Response:

```json
{"ok": true, "mode": "all", "orders": [{"id": "order-id", "status": "success", "mode": "temp"}]}
```

`GET /api/v1/numbers/orders/{order_id}`

Returns one order owned by the authenticated API key owner/reseller scope.

Response:

```json
{"ok": true, "order": {"id": "order-id", "status": "success", "mode": "temp"}}
```

Planned path:

`POST /api/v1/numbers/orders`

Creates a temporary-number order from a `quote_token`.

Headers:

- `Authorization: Bearer <api-key>` with `numbers:orders:create` scope.
- `Idempotency-Key`: strongly recommended for every money-moving request.

Body:

```json
{"quote_token": "quoted-offer-token", "language": "en"}
```

Response:

```json
{"ok": true, "order": {"id": "order-id", "status": "success"}}
```

Planned expansion:

- rental orders,
- voice/call orders,
- scoped customer API tokens.

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

- Idempotency keys for cancel/refund, replacement, and rental renewal.
- Optional webhooks for order status and SMS events.
- External docs with examples.
- Contract tests that assert response shape for `/api/v1/numbers`.
