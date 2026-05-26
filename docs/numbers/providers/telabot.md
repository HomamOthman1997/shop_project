# Tell A Bot Provider API

Status: documented from supplied provider docs and current adapter  
Adapter: `services/numbers/providers/telabot_provider.py`  
Provider code: `telabot`

## Base And Auth

Endpoint:

```text
https://www.tellabot.com/api_command.php
```

Auth:

- Query params: `user`, `api_key`.
- Local settings: `telabot_user`, `telabot_key`.

## One-Time MDNs

| Operation | `cmd` | Params |
| --- | --- | --- |
| List services | `list_services` | auth |
| Request MDN | `request` | `service`, optional `mdn`, optional `areacode`, optional `state`, optional `markup` |
| Request status | `request_status` | `id` |
| Reject MDN | `reject` | `id` |
| Read SMS | `read_sms` | optional `id`, optional `mdn`, optional `service` |
| Balance | `balance` | auth |

Current adapter behavior:

- `buy_number()` uses `cmd=request`.
- `state`, `areacode`, `mdn`, and `markup` are supported purchase kwargs.
- Success is accepted when request status is `Reserved` or `Awaiting MDN`.
- `get_sms()` uses `cmd=read_sms&id=...`.
- `cancel()` uses `cmd=reject&id=...`.

## Webhooks

Confirmed supplied incoming message payload:

```json
{
  "event": "incoming_message",
  "id": "10000001",
  "timestamp": "1600108956",
  "date_time": "2020-09-14 14:42:36 EDT",
  "from": "22000",
  "to": "18503814729",
  "service": "Google",
  "reply": "G-804036 is your Google verification code.",
  "pin": "G-804036",
  "price": 1.20
}
```

Confirmed priority request payload:

```json
{"event":"priority_request","status":"ok","id":"10000001","mdn":"15302286946","service":"Amazon","price":0.50}
```

Local route:

```text
POST /api/v1/provider-webhooks/telabot
```

Normalizer:

- generic parser maps `id` to provider order id.
- maps `pin` as code.
- maps `reply` as full SMS.

## Missing Or Needs Live Verification

- Real webhook sample after setting Account -> Profile webhook URL.
- Whether priority request assignment should update existing orders before SMS arrives.

