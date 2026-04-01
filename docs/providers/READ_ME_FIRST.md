# Provider Docs Access Notes (2026-03-12)

## SMSPool (S1)
- Postman docs link confirmed as SMSPool reference:
  - https://documenter.getpostman.com/view/30155063/2s9YXmZ1JY
- Local manual file (generated from Postman collection): `docs/providers/manual/smspool_api_reference.json`
- Raw local sources:
  - `docs/providers/raw/smspool_postman_documenter.html`
  - `docs/providers/raw/smspool_postman_collection.json`

## SMS-Man (S4)
- Official URL: https://sms-man.com/api
- Direct automated fetch still blocked in this environment (HTTP 403 / Cloudflare challenge).
- Integrated from user-provided v2 + compatible dumps into:
  - `docs/providers/manual/smsman_api_reference.json`
- Merged strategy saved: v2 primary + compatible additions (getStatusV2 + legacy setStatus semantics).

## Tell A Bot (S5)
- Command reference integrated locally:
  - `docs/providers/manual/telabot_api_reference.json`
- Source links:
  - https://www.tellabot.com/api_command.php

## HeroSMS (S3)
- Imported local OpenAPI file:
  - `docs/providers/raw/herosms_openapi_en.json`
- Manual summary:
  - `docs/providers/manual/herosms_api_reference.json`

## TextVerified (S2)
- OpenAPI file:
  - `docs/providers/raw/textverified_openapi_v2.json`
- Latest official swagger checked on 2026-03-12:
  - `https://backend.textverified.com/swagger/v2/swagger.json`
  - SHA256: `5ec5683bbeba26e8f1d513f70b09c2e470b414ffcfa9610b14ababc0a61c0f73`
  - Local mirror: `docs/providers/raw/textverified_openapi_v2_latest.json`
- Manual summary:
  - `docs/providers/manual/textverified_api_reference.json`

## Reloadly (DP1)
- Airtime / top-up local manual reference:
  - `docs/providers/manual/reloadly_api_reference.json`
- Official sources used:
  - https://documenter.getpostman.com/view/3428998/2sAYXCkJe9
  - https://developers.reloadly.com/
  - https://support.reloadly.com/locating-your-api-credentials
- Scope intentionally limited to:
  - OAuth for top-ups
  - airtime countries/operators
  - pricing/fx/discounts/promotions
  - top-up transaction execution and reporting
- Explicitly excluded for now:
  - gift cards
  - utility payments
  - other Reloadly product families

## eSIM Access (DP2)
- eSIM reseller local manual reference:
  - `docs/providers/manual/esimaccess_api_reference.json`
- Official source used:
  - https://docs.esimaccess.com/
- Current local scope:
  - package listing
  - profile ordering/query
  - balance query
  - usage check
  - top-up
  - lifecycle actions and webhook registration
- Auth shape captured locally as:
  - API key header `RT-AccessCode`
