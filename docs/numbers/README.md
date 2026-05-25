# Numbers Docs

Numbers is the first API-first consolidation target.

## Active Docs

- `API_CONTRACT.md`: draft versioned Numbers API contract.
- `MINIAPP_MIGRATION_CHECKLIST.md`: current Telegram-to-Mini-App migration status.
- `TELEGRAM_FLOW_AUDIT.md`: what Telegram code can and cannot be deleted yet.
- `MINIAPP_VISUAL_QA.md`: manual visual QA checklist after deployments.
- `PROVIDER_TIMEOUT_RETRY_MATRIX.md`: provider timeout and retry policy.

## Current Direction

- Keep Telegram notifications and chat-thread workflows where they still fit.
- Move reusable purchase/refund/replacement/rental behavior into shared backend services.
- Expose stable APIs that can power the Mini App, future web dashboard, and customer-built bots.
- Never expose real provider names to customers unless the view is explicitly admin-only.
