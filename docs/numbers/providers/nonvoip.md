# non-VoIP Provider API

Status: documented from supplied non-VoIP reference and current adapter  
Adapter: `services/numbers/providers/nonvoip_provider.py`  
Provider codes: `nonvoip`, `nonvoip_s6`

## Naming

`nonvoip_s6` is not a separate provider integration. It is a second public lane that points to the same provider object.

## Base And Auth

Base URL:

```text
https://www.non-voip.com/api/reseller
```

Auth:

- JSON POST requests.
- Local settings: `nonvoip_key` and `nonvoip_email`.
- Optional override: `nonvoip_base_url`.

## Current Adapter Commands

| Operation | Command/path | Params |
| --- | --- | --- |
| List services | `get_service_list` | account auth |
| Buy by service id | `order_number` | `service_id` |
| Reuse expired number | `reuse_number` | `order_id` |
| SMS polling fallback | `get_messages` | `order_id` |
| Refund expired number | `refund_number` | `id` |
| Transfer credit | `transfer_credit` | `email_to`, `amount`; reseller-only |

The current adapter prices from `get_service_list` because the supplied API reference does not include
a separate live price endpoint. Country support is inferred from the provider service name: service names
without an explicit country suffix are treated as the default US lane, while suffixes such as `UK`,
`Germany`, `Canada`, or `Spain` are mapped to their ISO country before quote or purchase.

## Webhooks

Confirmed supplied non-VoIP webhook payload:

```json
{"id":"123","number":"15551234567","code":"123456","message":"Your code is 123456","date":"2026-05-25"}
```

Local route:

```text
POST /api/v1/provider-webhooks/nonvoip
POST /api/v1/provider-webhooks/nonvoip_s6
```

Normalizer:

- generic parser maps `id` to provider order id.
- maps `code`.
- maps root `message` as full SMS text.

## Missing Or Needs Live Verification

- Account profile webhook URL setup confirmation.
- One real webhook event for `nonvoip` and, if used, `nonvoip_s6`.
- Exact current cancellation/refund response examples for `refund_number` after provider expiry.
- Account balance endpoint is not present in the supplied non-VoIP reseller docs. The adapter treats balance as unsupported unless non-VoIP support provides a documented command.

## Live Notes

- 2026-05-26: a low-cost live order was created successfully.
- 2026-05-26: `get_messages` for that order returned the expected empty/no-SMS shape: `text=null`, `code=null`, and `received_at=null`.
- 2026-05-26: immediate `refund_number` for that live order returned `{"code":400,"msg":"Not sufficient"}`. This is classified as `provider_balance_low`, but operationally it means immediate auto-refund is not proven for non-VoIP yet.
- Keep non-VoIP immediate no-code refund in quarantine until provider support clarifies whether refund only works after expiry or requires a different state transition.
- 2026-06-03: undocumented `get-prices`, `limits`, and `get-number` probes returned HTTP 405. The adapter now keeps them out of the normal price and purchase path.
