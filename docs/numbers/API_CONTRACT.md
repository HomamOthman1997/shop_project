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
- `numbers:orders:refresh`
- `numbers:orders:resend`
- `numbers:account:read`
- `webhooks:manage`
- `numbers:support:review` for internal/support API keys only.
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
- `missing_resolution`
- `review_not_found`
- `invalid_reseller`
- `event_not_found`

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
- `numbers:orders:refresh`: 60 requests per minute.
- `numbers:orders:resend`: 30 requests per minute.
- `webhooks:manage`: 30 requests per minute.
- `numbers:support:review`: 60 requests per minute.
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
  "scopes": ["numbers:account:read", "numbers:quotes", "numbers:orders:read", "numbers:orders:create", "numbers:orders:refresh", "numbers:orders:resend", "webhooks:manage"]
}
```

Only customer-safe scopes are accepted. Management scopes are not grantable through this endpoint unless we later add an explicit owner-only flow.

`POST /api/v1/api-keys/{key_id}/revoke`

Revokes a key in the authenticated reseller scope.

## Webhooks

Webhook management requires `webhooks:manage`.

`GET /api/v1/webhooks`

Lists configured endpoints for the authenticated reseller scope. Secrets are never returned.

`POST /api/v1/webhooks`

Creates a webhook endpoint. The `secret` is returned once.

Body:

```json
{
  "url": "https://example.com/numbers-webhook",
  "events": ["numbers.order.created", "numbers.order.sms", "numbers.order.resend_requested", "numbers.order.refunded"]
}
```

Allowed events:

- `numbers.order.created`
- `numbers.order.sms`
- `numbers.order.resend_requested`
- `numbers.order.refunded`

Queued delivery payloads are signed as `sha256=<hex-hmac>` over the canonical JSON body.

Delivery details:

- `Content-Type: application/json`
- `X-Webhook-Event`: event type.
- `X-Webhook-Id`: stable event id.
- `X-Webhook-Signature`: `sha256=<hex-hmac>`.
- Any `2xx` response marks delivery as complete.
- Non-`2xx` responses and network errors are retried with exponential backoff, up to the configured platform max attempts.

`POST /api/v1/webhooks/{webhook_id}/revoke`

Revokes a webhook endpoint in the authenticated reseller scope.

## Provider Inbound Webhooks

Provider inbound webhooks are server-to-server endpoints. They are not customer APIs and do not use customer API keys.

Production provider callback base for the new domain:

- `https://phantom-app.net/api/v1/provider-webhooks/{provider}?token=<provider-webhook-token>`

`POST /api/v1/provider-webhooks/smsready?token=<provider-webhook-token>`

Consumes SMSReady `new_sms` callbacks:

```json
{
  "event": "new_sms",
  "message": {
    "order_id": 50,
    "number": "18583056127",
    "code": "245646",
    "full_sms": "Here is your code: 245646"
  }
}
```

The backend matches `message.order_id` to `provider_order_id`, writes the code onto the order, logs the number event, and enqueues the customer-facing `numbers.order.sms` webhook.

`POST /api/v1/provider-webhooks/pvadeals?token=<provider-webhook-token>`

Consumes PVADeals `sms_received` callbacks:

```json
{
  "event": "sms_received",
  "timestamp": "2026-01-28T22:57:35.001Z",
  "requestId": "697a90d25ef1873ef44f48bc",
  "serviceId": "697139f7fe5460ddc2f27214",
  "number": "+13130001234",
  "message": "Your Airbnb verification code is 2200."
}
```

The backend matches `requestId` to `provider_order_id`, extracts the OTP from `message`, writes the code onto the order, logs the number event, and enqueues the customer-facing `numbers.order.sms` webhook.

`POST /api/v1/provider-webhooks/{provider}?token=<provider-webhook-token>`

Consumes generic provider SMS callbacks for providers whose payload contains common order/code fields such as `provider_order_id`, `order_id`, `activationId`, `requestId`, `code`, `otp`, `full_sms`, `text`, `message.text`, or `data.message`. This route is intentionally generic so provider dashboards can be switched to webhook delivery without adding a bespoke route for every provider.

Provider webhook processing now updates temporary orders and rental orders by `provider + provider_order_id`, logs an inbound audit event, and forwards customer-facing `numbers.order.sms` webhooks. Provider support and remaining verification work are tracked in `docs/numbers/PROVIDER_DELIVERY_MATRIX.md`.

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

Mini App path:

`GET /mini/numbers/api/country-suggestions?mode=temp&service=telegram`

Returns ranked countries for a service/mode.

### Account

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

Mini App path:

`POST /mini/numbers/api/account/language`

Body:

```json
{"language": "ar"}
```

### Prices

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

`POST /api/v1/numbers/orders/{order_id}/refresh`

Refreshes order status/SMS/call state.

For temporary-number orders, refresh is webhook-first. It never polls providers when the order is marked for provider webhook delivery or when global provider polling is disabled. On timeout, the backend runs the provider-aware auto-refund path and returns the current refund state.

Response:

```json
{"ok": true, "order": {"id": "order-id", "wait_state": "code_received", "code": "123456", "codes": ["123456"]}}
```

`POST /api/v1/numbers/orders/{order_id}/resend`

Requests another SMS/code from the provider for a temporary-number order that already received a code and is still inside the resend/reuse window. The API charges the configured resend price, resets the order to waiting, and relies on the provider webhook to deliver the next code.

Required scope: `numbers:orders:resend`.

Response:

```json
{"ok": true, "second_order_id": "billing-order-id", "order": {"id": "order-id", "public_status": "waiting", "can_resend": false}}
```

`GET /api/v1/numbers/orders/{order_id}/recording`

Downloads a call recording when available.

There is no public customer refund/cancel endpoint. Refunds are server-managed: the backend verifies that no code was received, checks the provider/order timeout policy, attempts provider cancellation, refunds through the ledger, and leaves failures for support review.

## Support Operations Endpoints

These endpoints require `numbers:support:review`. This scope is internal-only and is not grantable through customer API key creation.

`GET /api/v1/numbers/ops/refund-reviews`

Lists API temp-number orders that need support review after server-managed auto-refund could not finish safely. Non-super keys are scoped to their reseller. Super keys may pass `reseller_id`.

Query:

- `limit`: 1-200, default 50.
- `include_resolved`: `true` to include resolved review records.
- `reseller_id`: super-key only filter.

`POST /api/v1/numbers/ops/refund-reviews/{order_id}/resolve`

Marks a review as resolved after support investigation. It does not trigger a refund or provider action.

Body:

```json
{
  "resolution": "provider confirmed already cancelled; wallet adjustment handled in ledger review",
  "notes": "Ticket SUP-1234"
}
```

`GET /api/v1/numbers/ops/provider-webhook-events`

Lists provider inbound webhook audit events. This is used to verify webhook cutover and investigate unmatched provider callbacks.

Query:

- `provider`: optional provider code filter, e.g. `pvadeals`.
- `status`: optional event status filter: `processed`, `duplicate`, `ignored`, `unmatched`.
- `limit`: 1-200, default 50.

`POST /api/v1/numbers/ops/provider-webhook-events/{event_id}/replay`

Replays a stored provider webhook payload through the current parser and order matching logic. This is intended for `unmatched` or `ignored` events after a parser/mapping fix. It does not call the upstream provider and does not poll SMS.

### Mini App Action Equivalents

The Mini App still exposes workflow-specific action endpoints under `/mini/numbers/api/orders/{order_id}/...` for replacement, alternate provider retry, rental SMS/finish/renew/wake/notes, and voice recordings. These are not public versioned customer API endpoints yet. Public API exposure should happen only after each action has a stable request/response contract, scope, rate limit, and provider capability matrix.

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
