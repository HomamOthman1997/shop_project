# Numbers Provider API Docs

Status: working reference  
Last updated: 2026-05-25

This folder is the local provider API reference for the Numbers backend. It exists so we do not need to fetch or re-read provider documentation on every provider task.

Rules:

- Never store real API keys, account IDs, webhook secrets, emails, or tokens in these files.
- Document the upstream API shape and the local adapter behavior separately when they differ.
- If a provider changes docs, update the provider file first, then update code/tests.
- Provider names are internal only. Customer-facing views must continue using public aliases.

## Active Provider Inventory

| Provider code | Upstream | Local adapter | Products | Delivery status | Local doc | Missing documentation |
| --- | --- | --- | --- | --- | --- | --- |
| `smspool` | SMSPool | `services/numbers/providers/smspool_provider.py` | Temp, unlimited rental catalog/purchase | Confirmed polling-only; provider-level exception | `smspool.md` | Rental refund response examples and refund window policy |
| `telabot` | Tell A Bot | `services/numbers/providers/telabot_provider.py` | Temp | Webhook confirmed in supplied docs | `telabot.md` | Live webhook sample after dashboard configuration |
| `textverified` | TextVerified v2 | `services/numbers/providers/textverified_provider.py` | Temp, voice, rental | Webhook confirmed in official v2 docs | `textverified.md` | Decide whether to validate `X-Webhook-Signature` in addition to our shared provider token |
| `herosms` | HeroSMS | `services/numbers/providers/herosms_provider.py` | Temp, rental | Webhook confirmed in supplied docs | `herosms.md` | Live webhook sample and callback dashboard screenshot/settings |
| `nonvoip` | non-VoIP reseller API | `services/numbers/providers/nonvoip_provider.py` | Temp | Webhook confirmed in supplied non-VoIP docs | `nonvoip.md` | Live webhook sample after profile URL setup |
| `nonvoip_s6` | Alias for `nonvoip` | Same object as `nonvoip` | Temp second lane only | Same as `nonvoip` | `nonvoip.md` | Do not document separately unless it becomes a real separate upstream |
| `pvadeals` | PVADeals v3 | `services/numbers/providers/pvadeals_provider.py` | Temp, rental, unlimited rental | Webhook confirmed in supplied docs | `pvadeals.md` | Live webhook sample and exact rental refund/cancel policy |
| `smsready` | SMSReady | `services/numbers/providers/smsready_provider.py` | Temp, long-term rental | Webhook confirmed in supplied docs | `smsready.md` | Live webhook sample for one-time and LTR flows |
| `pvapins` | PVAPins | `services/numbers/providers/pvapins_provider.py` | Temp, rental | Confirmed polling-only; provider-level exception | `pvapins.md` | Current full rental endpoint response examples |
| `vaksms` | VAK-SMS | `services/numbers/providers/vaksms_provider.py` | Temp | Confirmed polling-only; provider-level exception | `vaksms.md` | Current response examples for SMS/cancel/resend |

## What We Still Need From You

Bring these only if you can find them in provider dashboards/support. Do not send keys.

1. PVADeals exact rental cancel/refund documentation. We have purchase, renew, request read, and webhooks, but the refund/cancel policy should be confirmed.
2. Live webhook payload samples for `smsready`, `pvadeals`, `herosms`, `textverified`, `nonvoip`/non-VoIP, and `telabot` after account-level callback URLs are configured.
3. Live polling/no-code refund verification notes for `smspool`, `vaksms`, and `pvapins`.

## Provider Webhook URL

Use this shape in provider dashboards:

```text
https://phantom-app.net/api/v1/provider-webhooks/{provider}?token=<provider-webhook-token>
```

Do not configure webhook URLs for `smspool`, `vaksms`, or `pvapins` unless the provider adds webhook support later. They are confirmed polling-only for the current accounts.

Named routes exist for:

- `/api/v1/provider-webhooks/smsready`
- `/api/v1/provider-webhooks/pvadeals`

All other providers use:

- `/api/v1/provider-webhooks/{provider}`

The local handler currently authenticates provider webhooks with the shared query/header token from `numbers_provider_webhook_token` or `provider_webhook_token`.
