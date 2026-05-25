# Numbers Docs

Numbers is the first API-first consolidation target.

## Active Docs

- `API_CONTRACT.md`: draft versioned Numbers API contract.
- `MINIAPP_MIGRATION_CHECKLIST.md`: current Telegram-to-Mini-App migration status.
- `TELEGRAM_FLOW_AUDIT.md`: what Telegram code can and cannot be deleted yet.
- `MINIAPP_VISUAL_QA.md`: manual visual QA checklist after deployments.
- `PROVIDER_DELIVERY_MATRIX.md`: provider webhook delivery/cutover status.
- `PROVIDER_TIMEOUT_RETRY_MATRIX.md`: provider timeout and retry policy.

## Current Direction

- Keep Telegram notifications and chat-thread workflows where they still fit.
- Move reusable purchase/refund/replacement/rental behavior into shared backend services.
- Expose stable APIs that can power the Mini App, future web dashboard, and customer-built bots.
- Never expose real provider names to customers unless the view is explicitly admin-only.
- Prefer provider webhooks for inbound SMS/code delivery. Provider polling is disabled by default and should only be re-enabled as a documented exception.
- Keep customer refund UX server-managed: the backend handles timeout checks, provider cancellation, wallet refund, and support-review escalation.

## Current Numbers API State

- Versioned base path: `/api/v1/numbers`.
- Mini App path: `/mini/numbers/api`.
- Customer API key scopes now include quotes, account read, order read/create/refresh/resend, webhook management, and API key management.
- Provider inbound callbacks use `https://phantom-app.net/api/v1/provider-webhooks/{provider}?token=<provider-webhook-token>`.
- Customer-facing webhooks support order creation, SMS/code received, resend requested, and refund events.
