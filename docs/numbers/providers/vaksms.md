# VAK-SMS Provider API

Status: adapter documented; public docs reviewed as polling-only  
Adapter: `services/numbers/providers/vaksms_provider.py`  
Provider code: `vaksms`

## Base And Auth

Base URL:

```text
https://vak-sms.com/api
```

Site/backend helper base:

```text
https://vak-sms.com/backend
```

Auth:

- API requests include the configured API key.
- Local setting name: `vaksms_key`.
- Optional overrides: `vaksms_base_url`, `vaksms_site_base_url`, `vaksms_docs_url`.

## Endpoints Used By The Adapter

| Operation | Endpoint/action | Params |
| --- | --- | --- |
| Countries | `getCountryList` | no key required in adapter |
| Services/catalog | docs URL / service list parsing | docs endpoint |
| Account/balance | `getBalance` | API key |
| Country stats | backend `country/stats` | `serviceId` |
| Price/count | `getCountNumber` | `service`, `country`, `price=1` |
| Buy number | `getNumber` | `service`, `country` |
| Poll SMS | `getSmsCode` | `idNum` |
| Cancel/end | `setStatus` | `idNum`, `status=end` |
| Resend | `setStatus` | `idNum`, `status=send` |

## Webhooks

No webhook/callback support was found in reviewed VAK-SMS V0/V1/V2 docs. The documented SMS retrieval path is polling/status based.

Local generic route exists only for future support:

```text
POST /api/v1/provider-webhooks/vaksms
```

## Missing Or Needs Live Verification

- VAK-SMS webhook/callback docs, if support can provide them.
- Current official response examples for `getSmsCode`, `setStatus=end`, and `setStatus=send`.
- Whether rental/long-term endpoints exist for our account; local adapter currently supports temp only.

