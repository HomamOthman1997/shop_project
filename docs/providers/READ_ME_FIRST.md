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
