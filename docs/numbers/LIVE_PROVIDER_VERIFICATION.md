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
| `smsready` | Unsupported by supplied docs | Confirmed: `new_sms`, `ltr_renewal` | Passed: route/token/parser accepted synthetic payload | Pending | Pending | Core API errors documented; no balance API | Use after one real webhook event |
| `pvadeals` | Supported; live balance returned | Confirmed in supplied docs | Passed | Pending | Pending | Needs live purchase error samples | Use after one real webhook event |
| `textverified` | Supported; live balance returned | Confirmed: `v2.sms.received` | Passed | Pending | Pending | Needs signature/event sample validation | Use after one real webhook event |
| `herosms` | Supported; live balance returned | Confirmed incoming SMS webhook | Passed | Pending | Pending | Needs live purchase error samples | Use after one real webhook event |
| `telabot` | Supported; live balance returned as provider payload | Confirmed: `incoming_message` | Passed | Pending | Pending | Needs priority/no-stock/live status samples | Use after one real webhook event |
| `nonvoip` | Unsupported by supplied docs | Confirmed profile webhook | Passed | Negative probes returned provider `500` for invalid ids | Pending | `Not sufficient` maps to balance-low; provider `500` remains unknown/provider error | Use after one real webhook event and one known failure sample |
| `pvapins` | Supported; adapter parser verified | Not confirmed; supplied docs emphasize polling | Route exists but not trusted | Pending | Not trusted | Needs webhook docs or dashboard callback proof | Quarantine for webhook-only mode |
| `vaksms` | Supported; live balance returned | Not confirmed; supplied docs are polling/read endpoints | Route exists but not trusted | Pending | Not trusted | Factory fixed; needs webhook docs | Quarantine for webhook-only mode |
| `smspool` | Supported; live balance returned | Not confirmed in reviewed docs | Route exists but not trusted | Pending | Not trusted | Needs webhook docs or account-manager confirmation | Quarantine for webhook-only mode |

## Findings So Far

- `smsready` and `nonvoip` do not expose account balance endpoints in the supplied docs. Their adapters intentionally return `None` for balance.
- `vaksms` is now registered in `ProviderFactory`.
- `pvapins` balance parsing is covered by tests and live adapter checks returned a numeric value.
- non-VoIP negative probes with invalid ids returned provider `500 Internal Server Error`; this must remain `PROVIDER_ERROR`, not provider balance.
- non-VoIP documented insufficient-funds text is `Not sufficient`; it maps to `PROVIDER_BALANCE_LOW`.
- Authenticated provider webhook routes now return HTTP 200 for `order_not_found` so provider dashboards do not disable callbacks after valid test/race events.

## Next Live Steps

1. Configure/confirm dashboard webhook URL for each confirmed webhook provider.
2. For each confirmed provider, run one low-cost live purchase with the helper script or through the Mini App API.
3. Trigger/receive one real SMS callback.
4. Confirm `provider_webhook_events` status is `processed`.
5. If callback is `unmatched` or `ignored`, capture raw payload, update normalizer, and replay.
6. Only after processed real callback, mark provider production-trusted.
