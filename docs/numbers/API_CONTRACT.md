# Numbers API Contract

Status: draft, backed by the dedicated `services/numbers/api.py` route layer
Last updated: 2026-05-26

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
- `numbers:orders:replace`
- `numbers:orders:rental`
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
- `quote_expired`
- `unsupported_quote_mode`
- `offer_unavailable`
- `provider_unavailable`
- `provider_price_changed`
- `insufficient_balance`
- `provider_failed`
- `provider_purchase_failed`
- `provider_not_available`
- `missing_scopes`
- `invalid_mode`
- `unsupported_order_mode`
- `invalid_owner`
- `missing_idempotency_key`
- `replace_unavailable`
- `alternate_unavailable`
- `order_closed`
- `provider_order_missing`
- `finish_failed`
- `renew_not_supported`
- `renew_failed`
- `wake_failed`
- `notes_not_supported`
- `key_not_found`
- `order_not_found`
- `recording_not_ready`
- `recording_download_failed`
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
- `numbers:country-suggestions`: 60 requests per minute.
- `numbers:account:read`: 60 requests per minute.
- `numbers:orders:read`: 90 requests per minute.
- `numbers:orders:create`: 30 requests per minute.
- `numbers:orders:refresh`: 60 requests per minute.
- `numbers:orders:resend`: 30 requests per minute.
- `numbers:orders:replace`: 20 requests per minute.
- `numbers:orders:rental`: 30 requests per minute.
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
  "scopes": ["numbers:account:read", "numbers:quotes", "numbers:orders:read", "numbers:orders:create", "numbers:orders:refresh", "numbers:orders:resend", "numbers:orders:replace", "numbers:orders:rental", "webhooks:manage"]
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

Consumes generic provider SMS callbacks for providers whose payload contains common order/code fields such as `provider_order_id`, `order_id`, `activationId`, `requestId`, `reservationId`, `code`, `otp`, `pin`, `parsedCode`, `full_sms`, `text`, `reply`, `message`, `message.text`, `data.message`, or `data.smsContent`. This route is intentionally generic so provider dashboards can be switched to webhook delivery without adding a bespoke route for every provider.

Provider webhook processing now updates temporary orders and rental orders by `provider + provider_order_id`, logs an inbound audit event, and forwards customer-facing `numbers.order.sms` webhooks. Provider support and remaining verification work are tracked in `docs/numbers/PROVIDER_DELIVERY_MATRIX.md`.

## Public/Client Endpoints

### Health

`GET /api/v1/numbers/health`

Returns API health and version metadata.

### Bootstrap

`GET /api/v1/numbers/catalog/bootstrap`

Returns selector metadata and API discovery metadata:

- modes,
- default selection,
- services,
- countries,
- US states,
- `api.base_path`,
- `api.capabilities`,
- `api.actions`.

`api.actions` is the global versioned API action catalog for customer-built bots and partner clients. It lists stable endpoint templates, methods, required scopes, disabled reasons, and whether `Idempotency-Key` is required. It must not expose Mini App URLs.

Example:

```json
{
  "api": {
    "base_path": "/api/v1/numbers",
    "quote_ttl_sec": 300,
    "capabilities": {
      "modes": ["temp", "rental", "voice"],
      "provider_identity_public": false,
      "manual_customer_refund_enabled": false,
      "server_managed_refunds": true,
      "customer_webhooks": true
    },
    "actions": {
      "api_docs": {"endpoint": "/api/v1/numbers/docs", "method": "GET", "scope": "public"},
      "openapi": {"endpoint": "/api/v1/numbers/openapi.json", "method": "GET", "scope": "public"},
      "quotes": {"endpoint": "/api/v1/numbers/quotes", "method": "GET", "scope": "numbers:quotes"},
      "create_order": {
        "endpoint": "/api/v1/numbers/orders",
        "method": "POST",
        "scope": "numbers:orders:create",
        "requires_idempotency_key": true
      },
      "submit_recharge": {
        "enabled": false,
        "endpoint": "/api/v1/numbers/recharge/submit",
        "method": "POST",
        "reason": "miniapp_only"
      }
    }
  }
}
```

### API Documentation

`GET /api/v1/numbers/docs`

Returns self-hosted human-readable HTML documentation for the public Numbers API. The page is generated from the runtime OpenAPI schema and the same `api.actions` discovery catalog used by bootstrap, so endpoint rows, scopes, idempotency hints, disabled submit flows, and capabilities stay aligned with backend behavior.

This is the preferred quick reference for customer-built bots and partner clients. It must remain dependency-free, noindex, and must not include `/mini/...` URLs or Telegram Mini App action metadata.

### OpenAPI Schema

`GET /api/v1/numbers/openapi.json`

Returns a generated OpenAPI 3.1 contract for the public Numbers API. The schema is built from the same action discovery catalog used by bootstrap, so endpoint templates, methods, scopes, idempotency requirements, and disabled submit flows stay aligned with runtime behavior.

This endpoint is public documentation metadata. It must expose only versioned API routes and must not include `/mini/...` URLs or Telegram-specific action metadata.

Key fields:

- `paths`: versioned public API routes under `/api/v1/numbers`.
- `components.securitySchemes.BearerAuth`: customer API key auth.
- `x-phantom-api-discovery`: the same global API discovery contract returned under bootstrap `api`.

### Country Suggestions

Versioned API path:

`GET /api/v1/numbers/country-suggestions?mode=temp&service=telegram&limit=10`

Mini App path:

`GET /mini/numbers/api/country-suggestions?mode=temp&service=telegram`

Returns ranked countries for a service/mode. The versioned API requires `numbers:quotes`, accepts `mode=temp|rental|voice`, canonicalizes service aliases, caps `limit` at 20, and returns an empty list for missing services or voice mode. The ranking service is shared with the Mini App so public API clients and the Telegram Mini App see the same country suggestions.

Response:

```json
{
  "ok": true,
  "mode": "temp",
  "service": "telegram",
  "countries": [
    {"code": "1", "name": "USA", "price": 0.44, "price_label": "$0.44"}
  ]
}
```

### Account

`GET /api/v1/numbers/account`

Returns user profile, wallet balance, and recent wallet activity.

Currently returns API-safe identity and wallet balance:
`recent_activity` contains sanitized ledger rows. It intentionally does not expose raw ledger `reason`, metadata, actor ids, provider names, or debug details.

```json
{
  "ok": true,
  "user": {"id": 123, "username": "customer", "language": "en", "joined_at": "2026-05-25T12:00:00+00:00"},
  "reseller": {"id": 123},
  "wallet": {"balance": 10.5, "currency": "USD", "balance_label": "$10.50"},
  "recent_activity": [
    {
      "id": "tx-1",
      "kind": "numbers_purchase",
      "label": "Numbers purchase",
      "direction": "debit",
      "amount": -0.44,
      "amount_label": "-$0.44",
      "balance_after": 10.5,
      "balance_label": "$10.50",
      "created_at": "2026-05-25T12:05:00+00:00",
      "order_id": "order-id"
    }
  ]
}
```

Mini App path:

`POST /mini/numbers/api/account/language`

Body:

```json
{"language": "ar"}
```

### Recharge Options

`GET /api/v1/numbers/recharge`

Scope: `numbers:account:read`.

Returns wallet balance, enabled payment methods, and a public capability/action contract for future web/API clients. This endpoint is intentionally read-only for now: recharge proof submission still requires the authenticated Telegram Mini App review flow. Payment-method normalization is shared with the Mini App through `services/numbers/customer_flows.py`, so the read-only API and Mini App form do not drift.

```json
{
  "ok": true,
  "wallet": {"balance": 10.5, "currency": "USD", "balance_label": "$10.50"},
  "methods": [
    {
      "code": "usdt",
      "title": "USDT",
      "currency": "USD",
      "target": "T_WALLET",
      "support": "@support",
      "rate": 1,
      "rate_label": "1 credit = $1.00",
      "instructions": "Send payment to T_WALLET."
    }
  ],
  "actions": {
    "submit_recharge": {
      "enabled": false,
      "endpoint": "/api/v1/numbers/recharge/submit",
      "method": "POST",
      "reason": "miniapp_only"
    }
  },
  "capabilities": {"submit_recharge_proof": false}
}
```

### Support Options

`GET /api/v1/numbers/support`

Scope: `numbers:account:read`.

Returns the customer-safe support categories and a public capability/action contract. Ticket submission is still Mini App-only until support replies no longer depend on Telegram chat threads. Category normalization is shared with the Mini App through `services/numbers/customer_flows.py`.

```json
{
  "ok": true,
  "categories": [
    {"key": "numbers", "label": "Numbers orders"},
    {"key": "user_balance", "label": "Balance and payments"}
  ],
  "actions": {
    "submit_ticket": {
      "enabled": false,
      "endpoint": "/api/v1/numbers/support/ticket",
      "method": "POST",
      "reason": "miniapp_only"
    }
  },
  "capabilities": {"submit_ticket": false}
}
```

### Prices

`GET /api/v1/numbers/quotes?mode=temp&service=telegram&country=1&state=none`

`GET /api/v1/numbers/quotes?mode=rental&service=telegram&country=1&state=NY`

`GET /api/v1/numbers/quotes?mode=voice&service=telegram&country=1&state=CA`

Returns normalized provider rows with public provider IDs and obfuscated display names only. Real provider names must not be exposed to customers. Quote tokens are signed but not encrypted, so they must carry only public provider IDs (`provider_id`), never internal provider codes.

Currently supported modes:

- `temp`
- `rental`
- `voice`

Temporary and voice quote rows contain a direct `quote_token` per provider. Rental quote rows contain `options[]`; each rental option has its own `quote_token`, `duration_label`, `price_label`, and safe state/renewal metadata. Provider raw option payloads and internal provider codes are not returned.

Mini App price rows also include `purchase_action` on buyable temp/voice rows and on buyable rental options. `purchase_action` contains `enabled`, `label_key`, `endpoint`, `method`, `body`, and `reason`; the Mini App frontend should execute purchases through that action contract and treat direct `quote_token` usage as fallback compatibility only. The versioned public API should keep using `quote_token` directly with `POST /api/v1/numbers/orders`.

Voice quotes are US call-number quotes. The API normalizes voice quote country to `1` and supports optional US state targeting through `state`.

### Orders

`GET /api/v1/numbers/orders`

Returns recent temp, rental, and voice orders for the authenticated user.
Order payloads expose `provider_id` plus an obfuscated `provider` display name. They must not expose internal provider codes.
Order payloads must not expose internal cost fields such as `base_price` or `base_price_label`.
Refund payload reasons are customer-safe only: `automatic_refund`, `refund_pending`, or empty string. Raw provider/refund diagnostics belong in internal logs or support-review endpoints, not public customer payloads.
Order payloads include `customer_state`, the canonical customer-facing state for the public API and Mini App UI. Clients should use this object instead of inferring webhook, code, refund, or support-review behavior from provider-specific fields.
Voice order payloads include `calls_count`, `recording_available`, and `recording_url` when a recording exists. The recording URL points to the versioned backend endpoint, not the upstream provider URL.

Order payloads include `api_actions`, a server-owned action discovery contract for customer-built bots and partner API clients. It uses versioned API endpoints only and must never expose `/mini/...` URLs or Telegram-specific metadata.

`customer_state` fields:

- `key`: stable UI state such as `awaiting_provider_webhook`, `code_received`, `refund_pending`, `support_review_pending`, `refunded`, `waiting_for_recording`, or `call_received`.
- `tone`: one of `waiting`, `success`, `pending-refund`, `refunded`, or `danger`.
- `status_label_key`, `receive_label_key`, `message_key`, `recommended_action_key`: translation keys for API clients and the Mini App.
- `provider_reference`: the public route id (`S1`, `S2`, ...), never the upstream provider name.
- `show_provider_identity`: always `false` for customer payloads.
- `awaiting_webhook`: true when the backend expects provider webhook delivery instead of app polling.
- `auto_refund_managed`: true when timeout/no-code refund handling is server-managed.
- `manual_refund_available`: currently always `false`; there is no customer manual refund endpoint.
- `support_review_open`: true only when support must review a refund case.

`api_actions` fields:

- `enabled`: whether the action can be called for the current order state.
- `endpoint`: versioned API endpoint to call, such as `/api/v1/numbers/orders/{order_id}/refresh`.
- `method`: HTTP method.
- `scope`: API key scope required for the action.
- `reason`: customer-safe reason when disabled.
- `requires_idempotency_key`: true when clients should send an `Idempotency-Key` header.

Current public `api_actions` keys:

- `refresh`
- `resend`
- `replace`
- `alternate_provider`
- `download_recording`
- `rental_sms`
- `rental_finish`
- `rental_renew`
- `rental_wake`
- `rental_notes`

Mini App order payloads also include an `actions` object. This is separate from public `api_actions` and is the server-owned UI action contract for the Mini App. The frontend should render order controls from this object, execute server-backed actions through each action's `endpoint`/`method`, and treat legacy `can_*` flags as fallback compatibility only.

Action object fields:

- `enabled`: whether the customer can see/use the action now.
- `label_key`: Mini App translation key.
- `endpoint`: Mini App endpoint or recording URL for server-backed actions; empty for client-only copy actions.
- `method`: `POST`, `GET`, or `CLIENT`.
- `reason`: optional customer-safe machine reason when disabled.
- `confirm_label_key`: optional Mini App translation key for confirmation text.
- `busy_label_key`: optional Mini App translation key for busy overlay title.
- `success_label_key`: optional Mini App translation key for fallback success text.
- `idempotency_key`: optional server-provided idempotency key for mutating actions.

The Mini App frontend must not synthesize `/mini/numbers/api/orders/{id}/...` paths or action idempotency keys for order controls. If an order action is server-backed, its `endpoint` and `method` must be present in the order `actions` payload; if it needs idempotency, the backend provides `idempotency_key`. Legacy `can_*` fields may only help render older payloads; they are not an execution contract.

Current action keys:

- `copy_number`
- `copy_code`
- `refresh`
- `second_code`
- `replace`
- `alternate_provider`
- `preview_recording`
- `download_recording`
- `rental_sms`
- `rental_renew`
- `rental_wake`
- `rental_notes`
- `rental_finish`

Rental order payloads include customer-safe rental metadata and action flags:

- `duration_label`
- `end_date`
- `notes`
- `tags`
- `can_finish`
- `can_renew`
- `can_wake`
- `can_notes`

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

Creates a temporary-number, rental-number, or voice call-number order from a `quote_token`.

Headers:

- `Authorization: Bearer <api-key>` with `numbers:orders:create` scope.
- `Idempotency-Key`: strongly recommended for temporary, rental, and voice orders.

Body:

```json
{"quote_token": "quoted-offer-token", "language": "en"}
```

Rules:

- `mode=temp` quote tokens create temporary-number orders.
- `mode=rental` option quote tokens create rental-number orders.
- `mode=voice` quote tokens create US call-number orders.
- Rental creation charges the wallet, reserves the rental with the provider, stores webhook delivery/protection metadata, and returns the public order payload.
- Voice creation charges the wallet, reserves a call-capable number through the provider, stores webhook delivery metadata, and returns the public order payload.
- Quote tokens are revalidated against current provider prices/options before charge.

Response:

```json
{"ok": true, "order": {"id": "order-id", "status": "success"}}
```

`POST /api/v1/numbers/orders/{order_id}/refresh`

Refreshes order status/SMS/call state.

For temporary-number orders, refresh is webhook-first. It never polls providers when the order is marked for provider webhook delivery or when global provider polling is disabled, except for explicitly confirmed polling-only providers (`pvapins`, `vaksms`, `smspool`). On timeout, the backend runs the provider-aware auto-refund path and returns the current refund state.

For rental and voice orders, refresh returns the current persisted state only and records `api_last_refresh_at` / `api_last_refresh_mode=provider_webhook`. It does not call provider polling APIs; delivery is expected through provider webhooks or already stored order state.

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

`POST /api/v1/numbers/orders/{order_id}/replace`

Requests a new temporary or voice number after the original order is closed/refunded/expired without a received code or call recording. This endpoint requires `numbers:orders:replace` and an `Idempotency-Key`.

Rules:

- Only `temp` and `voice` orders are accepted.
- The original order lookup is scoped to the authenticated API key owner/reseller.
- The backend revalidates the current provider offer before charging.
- The replacement order stores `temp_retry_source_order_id` and `temp_retry_reason=replace_request`.

Response:

```json
{"ok": true, "order": {"id": "replacement-order-id", "public_status": "waiting"}}
```

`POST /api/v1/numbers/orders/{order_id}/alternate`

Requests a replacement temporary number from a different provider. This endpoint requires `numbers:orders:replace` and an `Idempotency-Key`.

Rules:

- Only `temp` orders are accepted.
- If no alternate provider is already stored on the original order, the backend evaluates current quoteable providers and stores a customer-safe alternate suggestion.
- Internal provider codes and raw provider metadata are not returned.
- The replacement order stores `temp_retry_source_order_id` and `temp_retry_reason=alternate_provider_request`.

Common replacement errors:

- `400 invalid_mode` when the order mode is not supported.
- `400 missing_idempotency_key` when `Idempotency-Key` is missing.
- `404 order_not_found` when the order is missing or outside the caller scope.
- `409 replace_unavailable` when the original order is not eligible.
- `409 alternate_unavailable` when no alternate provider is available.
- `409 provider_unavailable` when the selected provider offer is no longer buyable.

`GET /api/v1/numbers/orders/{order_id}/recording`

Downloads a call recording when available.

Required scope: `numbers:orders:read`.

Rules:

- Order lookup is scoped to the authenticated API key owner/reseller.
- Only `voice` orders are accepted.
- The backend delegates validation, provider download, and attachment filename selection to `order_recording_service`, then returns a no-store attachment.

Responses:

- `200` with audio bytes and `Content-Disposition: attachment`.
- `400 invalid_mode` when the order is not a voice order.
- `404 order_not_found` when the order is missing or outside the caller scope.
- `404 recording_not_ready` when no recording URI is stored yet.
- `502 recording_download_failed` when the upstream recording download fails.

There is no public customer refund/cancel endpoint. Refunds are server-managed: the backend verifies that no code was received, checks the provider/order timeout policy, attempts provider cancellation, refunds through the ledger, and leaves failures for support review.

### Rental Actions

These endpoints require `numbers:orders:rental` and are scoped to the authenticated API key owner/reseller.

`POST /api/v1/numbers/orders/{order_id}/rental/sms`

Returns the current stored rental SMS state. This endpoint is webhook-first/state-read only: it records `api_last_rental_sms_check_at` and `api_last_rental_sms_check_mode=provider_webhook`, but it does not poll upstream provider SMS APIs.

Response:

```json
{"ok": true, "messages": ["Your code is 123456"], "order": {"id": "order-id", "mode": "rental"}}
```

`POST /api/v1/numbers/orders/{order_id}/rental/finish`

Finishes/closes an active rental through the provider when supported, stores `rental_finished_at`, and returns a public order payload. Replays after a stored finish return the current finished state.

`POST /api/v1/numbers/orders/{order_id}/rental/renew`

Renews a renewable rental through the provider. This endpoint requires `Idempotency-Key`; repeated requests with the same key and order return the saved response without calling the provider again.

Headers:

- `Idempotency-Key`: required.

`POST /api/v1/numbers/orders/{order_id}/rental/wake`

Requests provider wake/reactivation for an active rental when supported.

`POST /api/v1/numbers/orders/{order_id}/rental/notes`

Loads provider notes/tags for an active rental when supported, stores sanitized notes/tags on the order, and returns only customer-safe `notes`, `tags`, and public order payload. Provider raw responses are never returned.

Common rental action errors:

- `400 invalid_mode` when the order is not rental.
- `400 missing_idempotency_key` for renew without an idempotency key.
- `404 order_not_found` when the order is missing or outside caller scope.
- `409 order_closed` when the rental is no longer active.
- `409 provider_order_missing` when provider reservation data is incomplete.
- `409 finish_failed`, `renew_not_supported`, `renew_failed`, `wake_failed`, or `notes_not_supported` for provider capability/action failures.

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

`GET /api/v1/numbers/ops/provider-readiness`

Lists the production readiness policy for every upstream provider. The response includes `status`, `quote_enabled`, `purchase_enabled`, `auto_refund_enabled`, `webhook_documented`, `webhook_verified`, and the latest webhook audit event unless `include_events=0` is passed. Status `polling_required` means the provider is intentionally enabled through a provider-level polling exception because its current account/docs do not support provider webhooks.

The quote and order APIs enforce this policy server-side. Quarantined providers are not returned to customers, and disabled-provider quote tokens are rejected before wallet charge or provider calls.

Runtime override:

- Env var: `NUMBERS_PROVIDER_READINESS_OVERRIDES`
- JSON object keyed by provider code.
- Supported fields: `status`, `quote_enabled`, `purchase_enabled`, `auto_refund_enabled`, `webhook_documented`, `webhook_verified`, `reason`.

Example:

```json
{"smsready":{"status":"webhook_pending","quote_enabled":true,"purchase_enabled":true,"auto_refund_enabled":true,"reason":"verified from Railway network"}}
```

`POST /api/v1/numbers/ops/provider-webhook-events/{event_id}/replay`

Replays a stored provider webhook payload through the current parser and order matching logic. This is intended for `unmatched` or `ignored` events after a parser/mapping fix. It does not call the upstream provider and does not poll SMS.

### Mini App Action Equivalents

The Mini App still exposes workflow-specific action endpoints under `/mini/numbers/api/orders/{order_id}/...` for UI-specific flows. Country suggestions, rental quote/create, voice quote/create, replacement/alternate-provider retry, rental SMS/finish/renew/wake/notes, and voice recording download are now available through the versioned API. Public API exposure for any remaining Mini App-only action should happen only after the action has a stable request/response contract, scope, rate limit, and provider capability matrix.

Mini App purchase, refresh, replacement, alternate-provider, recharge, support, and rental action endpoints are UI wrappers over shared backend services. Mini App price rows use the same signed quote-token format for temp/rental/voice where possible, `/mini/numbers/api/purchase` routes those tokens through `create_number_order_from_quote(...)`, refresh routes through `order_refresh_service.refresh_number_order(...)`, recharge reads `/mini/numbers/api/recharge` and submits payment proof through `customer_flows.submit_recharge_request(...)`, support can attach customer-safe order context from `/mini/numbers/api/orders` and creates tickets through `customer_flows.submit_support_ticket(...)`, rental SMS/finish/renew/wake/notes routes call `order_rental_service`, and rental no-SMS protection/cancel/refund guards call `order_rental_protection_service`. Action calls use Telegram `initData` authentication. Order responses start from `order_service.public_order_payload(...)` and then add only Mini App UI fields such as localized labels/detail rows, Mini App recording URL, refresh flags, and second-code price labels. Legacy/non-API Mini App quote tokens are rejected by the purchase route, and the old Mini App-only quote resolver/direct provider purchase helpers have been removed; direct provider purchase fallbacks must not be reintroduced.

`GET /mini/numbers/api/bootstrap` also owns the Mini App surface contract under `client`. The frontend should render navigation from `client.tabs` and execute global screen actions from `client.actions` instead of hardcoding endpoint strings for country suggestions, prices, purchase, account, orders, recharge, support, language switching, recharge proof submission, or support ticket submission. Account, recharge, and support responses may repeat the relevant action subset so the UI can merge fresh endpoint/method settings after authenticated loads. This keeps the Mini App controllable from the backend while preserving Telegram `initData` authentication at the edge.

Telegram rental SMS/finish/renew/wake/notes callbacks use the same `order_rental_service` backend. Telegram-specific code should only handle callback ownership, localized messages, chat edits, and the temporary Hero no-SMS finish safety pre-check.

API/Mini App order creation and Telegram temp/voice/rental purchase callbacks call `order_purchase_service` for provider reservation and provider-failure refund handling. Telegram-specific code should keep only state validation, wallet charge trigger, chat edits, localized messages, and waiter startup. Do not reintroduce provider adapter calls into Telegram, Mini App, or public API route handlers.

Temporary replacement/alternate-provider order creation is centralized in `order_service.request_replacement_order(...)`. API, Mini App, and Telegram callbacks pass a client source (`numbers_api`, `numbers_miniapp`, or `numbers_telegram`) plus optional Telegram wait metadata. The service owns provider revalidation, alternate-provider selection, idempotent order creation, charging, provider provisioning, and replacement event logging. Telegram callbacks should not create replacement orders, charge wallets, or call provider provisioning directly.

`order_service.py` owns quote resolution, order creation, replacement creation, idempotency, and customer webhook enqueueing. `order_lifecycle_service.py` owns the API/Mini App money-moving lifecycle for temp/voice/rental order creation: charge first, run provider provisioning second, preserve expected provider-failure refund semantics from `order_purchase_service`, and roll back unexpected post-charge provisioning exceptions through one shared path. `order_charge_service.py` owns wallet charge + charge-failure status/event handling; `order_purchase_service.py` owns provider reservation and expected provider-failure refund handling. API/Mini App order creation, API/Mini App temp resend, Telegram temp/voice/rental purchase/replacement callbacks, and Telegram second-code resend use the shared charge helper. Resend still keeps provider-resend-specific semantics in `shared/temp_second_code.py` through an injected `charge_order_fn`.

Rental action events/check markers should include a client source. Versioned API calls use `numbers_api`; Mini App wrappers use `numbers_miniapp`; Telegram callbacks use `numbers_telegram`.

`/mini/numbers/api/orders/{order_id}/cancel` is intentionally not registered. Customer cancellation/refund remains server-managed through timeout/provider-aware backend policy, not a manual Mini App API action.

Mini App voice recording download is also webhook-first/state-read: it delegates to `order_recording_service`, downloads only a recording URI already stored on the order, and does not poll the upstream provider for call status during the download request. Telegram voice recording URI parsing and file sending use the same service.

Telegram voice call waiting/manual check uses `order_voice_service` for provider call reads and recording URI extraction. This remains a Telegram notification wrapper, not a public API behavior. Versioned API and Mini App refresh routes must continue to read persisted state and must not poll provider call APIs.

## Mini App Submit Flows Only For Now

These customer workflow submits are not ready for public customer API exposure:

- `POST /api/v1/numbers/recharge/submit`
- `POST /api/v1/numbers/support/ticket`

Reason:

- recharge proof handling still depends on Telegram/operator review workflows,
- support replies still depend on Telegram chat threads.

Read-only `GET /api/v1/numbers/recharge` and `GET /api/v1/numbers/support` are exposed so future web/API clients can discover available methods, categories, and current submit capabilities without depending on Mini App internals. The submit business logic has been extracted to `customer_flows.py`; the public submit endpoints should only be enabled after non-Telegram proof storage/review delivery and non-Telegram support reply delivery are designed.

## Required Before Customer API Exposure

- External customer docs with copy/paste examples for temp, rental, voice, webhooks, and error handling.
- Live provider webhook verification for every active upstream provider.
- Contract tests should continue to assert response shape for every newly exposed `/api/v1/numbers` endpoint.
