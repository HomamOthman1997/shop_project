# Numbers Live Provider Verification

Status: active checklist  
Last updated: 2026-05-26

Purpose: verify every Numbers provider with real upstream behavior before production cutover. Unit tests and synthetic webhooks prove our code paths; this matrix tracks provider-generated orders, errors, and SMS callbacks.

## Rules

- Default verification must be dry-run only.
- Live purchases require an explicit `--purchase` flag.
- If a live purchase returns an order id, cancel/refund immediately unless intentionally testing SMS delivery.
- Never classify an unknown provider error as provider balance. Only documented balance strings such as `Not sufficient` or `Insufficient balance` map to `PROVIDER_BALANCE_LOW`.
- A provider is production-trusted for webhook delivery only after a real provider-generated webhook is recorded as `processed` in `provider_webhook_events`.
- Providers without confirmed webhook docs stay quarantined for webhook-only operation.

## Helper Script

Dry-run:

```powershell
python scripts/live_provider_verification.py nonvoip --country US
```

Explicit live purchase with auto-cancel:

```powershell
python scripts/live_provider_verification.py nonvoip --service 1567 --country US --purchase
```

The script prints JSON lines and scrubs secrets. It checks balance support, service catalog, price, normalized error, and optionally purchase/cancel.

## Current Matrix

| Provider | Balance API | Webhook docs | Route smoke | Live order | Real webhook | Error taxonomy state | Production decision |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `smsready` | Unsupported by supplied docs | Confirmed: `new_sms`, `ltr_renewal` | Passed: route/token/parser accepted synthetic payload | Blocked by local/provider network failure to `api.sms-ready.com` | Pending | Connect failure maps to `provider_unknown_error` and remains retryable | Retry from Railway and use after one real webhook event |
| `pvadeals` | Supported; live balance returned | Confirmed in supplied docs | Passed | Passed: low-cost order created and immediate flag/cancel call succeeded | Pending | Purchase/cancel success path verified; no SMS callback yet | Use after one real webhook event |
| `textverified` | Supported; live balance returned | Confirmed: `v2.sms.received` | Passed | Passed: low-cost order created and immediate cancel succeeded | Pending | Signature secret configured in dashboard; real signature sample still pending | Use after one real webhook event |
| `herosms` | Supported; live balance returned | Confirmed incoming SMS webhook | Passed | Attempted; provider returned `NO_NUMBERS` for low-cost US service | Pending | `NO_NUMBERS` maps to `provider_no_stock`; numeric country mapping fixed/preserved | Use after one real webhook event |
| `telabot` | Supported; live balance returned as provider payload | Confirmed: `incoming_message` | Passed | Passed: low-cost order created and immediate reject succeeded | Pending | Purchase/reject success path verified; priority/no-stock samples still useful | Use after one real webhook event |
| `nonvoip` | Unsupported by supplied docs | Confirmed profile webhook | Passed | Passed: low-cost order created; immediate refund returned `Not sufficient` | Pending | `Not sufficient` maps to `provider_balance_low`; provider `500` remains unknown/provider error | Quarantine immediate auto-refund until refund semantics are clarified |
| `pvapins` | Supported; adapter parser verified | Confirmed unavailable by account/docs | Generic route exists but normal delivery is polling | Not applicable | Polling required | Explicit polling exception; no webhook expected | Verify polling/no-code refund live |
| `vaksms` | Supported; live balance returned | Confirmed unavailable by account/docs | Generic route exists but normal delivery is polling | Not applicable | Polling required | Factory fixed; no webhook expected | Verify polling/no-code refund live |
| `smspool` | Supported; live balance returned | Confirmed unavailable by account/docs | Generic route exists but normal delivery is polling | Not applicable | Polling required | No webhook expected | Verify polling/no-code refund live |

## Live Run 2026-05-26

Provider order ids and phone numbers were intentionally omitted from this file. Raw command output was scrubbed by `scripts/live_provider_verification.py`.

| Provider | Service/country tested | Result | Cancel/refund result | Notes |
| --- | --- | --- | --- | --- |
| `textverified` | `apple` / `US` | Order created | Cancel succeeded | Webhook delivery still requires a real SMS or dashboard test event captured as `processed`. |
| `telabot` | `Apple` / `US` | Order created | Reject succeeded | No SMS arrived during this run, so webhook remains unproven. |
| `pvadeals` | low-cost US service | Order created | Provider returned flag/cancel success | Treat as cancel path verified, not a proven refund settlement. |
| `herosms` | `gp` / `US` | No order; provider returned `NO_NUMBERS` | Not applicable | Adapter now preserves `NO_NUMBERS` instead of falling back to an invalid no-country request. |
| `nonvoip` | low-cost UK service id via US request path | Order created | Refund returned `Not sufficient` | `get_messages` shows no SMS yet. Do not trust immediate auto-refund for this provider until clarified. |
| `smsready` | `PayPal` / `United States` | Not reached | Not applicable | Local attempts failed connecting to `api.sms-ready.com:443`; retry from Railway/prod network. |

## Error Taxonomy

The shared normalizer returns legacy uppercase `code` plus API-facing `taxonomy_code`:

| Taxonomy code | Meaning | Typical raw examples |
| --- | --- | --- |
| `provider_balance_low` | Provider account cannot pay for the operation | `Insufficient balance`, `Not sufficient`, `no_balance` |
| `provider_no_stock` | Provider has no number for the requested service/country | `NO_NUMBERS`, `out of stock`, `unavailable` |
| `provider_auth_error` | Bad or unauthorized provider credential | `Wrong token`, `bad_key`, `unauthorized` |
| `provider_timeout` | Retryable upstream/network timeout class | `timeout`, `request_error`, temporary failures |
| `provider_unknown_error` | Raw response is not classified yet | Provider `500`, unexpected validation or malformed response |

## Production Readiness Gate

Runtime policy lives in `services/numbers/provider_readiness.py` and is exposed through:

```text
GET /api/v1/numbers/ops/provider-readiness
```

Production can override this policy without a code deploy through `NUMBERS_PROVIDER_READINESS_OVERRIDES`, for example:

```json
{"smsready":{"status":"webhook_pending","quote_enabled":true,"purchase_enabled":true,"auto_refund_enabled":true,"reason":"verified from Railway network"}}
```

Policy effects:

- quote APIs hide providers where `quote_enabled=false`;
- order creation rejects quote tokens where `purchase_enabled=false` before wallet charge;
- no-code auto-refund skips providers where `auto_refund_enabled=false` and sends the order to support review;
- provider webhook audit events remain the source of truth for moving `webhook_verified` to true.

Current policy summary:

| Provider | Status | Quote | Purchase | Auto-refund |
| --- | --- | --- | --- | --- |
| `textverified` | `webhook_pending` | yes | yes | yes |
| `telabot` | `webhook_pending` | yes | yes | yes |
| `pvadeals` | `webhook_pending` | yes | yes | yes |
| `herosms` | `webhook_pending` | yes | yes | yes |
| `nonvoip` | `refund_risk` | yes | yes | no |
| `smsready` | `disabled` | no | no | no |
| `pvapins` | `polling_required` | yes | yes | no |
| `vaksms` | `polling_required` | yes | yes | no |
| `smspool` | `polling_required` | yes | yes | no |

## Findings So Far

- `smsready` and `nonvoip` do not expose account balance endpoints in the supplied docs. Their adapters intentionally return `None` for balance.
- `vaksms` is now registered in `ProviderFactory`.
- `pvapins` balance parsing is covered by tests and live adapter checks returned a numeric value.
- `pvapins`, `vaksms`, and `smspool` are confirmed polling-only for current accounts and are explicit provider-level polling exceptions. They should not require `NUMBERS_PROVIDER_SMS_POLLING_ENABLED=true` globally.
- non-VoIP negative probes with invalid ids returned provider `500 Internal Server Error`; this must remain `PROVIDER_ERROR`, not provider balance.
- non-VoIP documented insufficient-funds text is `Not sufficient`; it maps to `PROVIDER_BALANCE_LOW`.
- non-VoIP live immediate `refund_number` after a successful order returned `Not sufficient`; do not assume no-code refund is production-safe for this provider yet.
- HeroSMS `US` now resolves to provider country id `187` in price output. Buy failures for exhausted inventory remain `NO_NUMBERS`/`provider_no_stock`.
- Authenticated provider webhook routes now return HTTP 200 for `order_not_found` so provider dashboards do not disable callbacks after valid test/race events.

## Next Live Steps

1. Configure/confirm dashboard webhook URL for each confirmed webhook provider.
2. For each confirmed provider, run one low-cost live purchase with the helper script or through the Mini App API.
3. Trigger/receive one real SMS callback.
4. Confirm `provider_webhook_events` status is `processed`.
5. If callback is `unmatched` or `ignored`, capture raw payload, update normalizer, and replay.
6. Only after processed real callback, mark provider production-trusted.
