# Numbers Mini App Visual QA

Use this checklist after each Railway deploy that touches `/mini/numbers`.

## Devices

- [ ] Telegram mobile, Arabic user language
- [ ] Telegram mobile, English user language
- [ ] Desktop browser smoke check

## Buy Flow

- [ ] First load shows splash until the app is ready.
- [ ] Arabic screens are RTL and contain no English fallback text.
- [ ] Provider cards keep provider name, star badge, price, and Buy button separated.
- [ ] Best provider takes the full row.
- [ ] Other providers render two per row without overflow.
- [ ] Temp/voice Buy buttons and rental option buttons execute the backend `purchase_action` payload.
- [ ] Country cannot be opened before service selection.
- [ ] State appears only for United States and resets when switching modes.
- [ ] Call number locks country to United States.
- [ ] Check prices scrolls to results.

## Orders

- [ ] Temporary number waiting state shows receive panel, countdown, and refresh/status action.
- [ ] Temporary number code state shows code and copy actions.
- [ ] Resend/second-code action appears only after a code is received and shows the resend price.
- [ ] Refund state is visible when an order is refunded or pending support review.
- [ ] No primary manual refund button appears for temporary orders.
- [ ] Order action buttons match the backend `actions` payload; disabled/unavailable actions do not render, and button execution uses the backend-provided endpoint/method.
- [ ] Order actions still work if the frontend has no local knowledge of `/mini/numbers/api/orders/{id}/...` paths or action idempotency keys; endpoints, confirmation labels, busy labels, success labels, and idempotency keys come from the order payload.
- [ ] Call number waiting state shows timeline and Check call action.
- [ ] Call recording can be played in-app and downloaded.
- [ ] Rental number shows SMS, finish, renew, wake, and notes actions when supported.
- [ ] Order cards show public provider IDs only, never real provider names.

## Webhook Delivery

- [ ] A real provider callback to `https://phantom-app.net/api/v1/provider-webhooks/{provider}?token=...` creates a `processed` provider webhook audit event.
- [ ] A received provider code updates the open Mini App order after refresh/reopen without provider polling.
- [ ] Resend request resets the order to waiting and the next webhook-delivered code appears in the receive panel.
- [ ] Rental SMS delivered through a provider webhook appears in the rental order card and SMS action.
- [ ] Timeout/no-code orders show refunded or pending-refund state after backend auto-refund handling.

## Account And Support

- [ ] Bottom tabs render from the bootstrap `client.tabs` payload and still show Buy, Orders, Recharge, Account, and Support.
- [ ] Country suggestions, prices, purchase, Account, Orders, Recharge, Support, language, recharge submit, and support submit calls use the backend `client.actions` endpoint/method contract where they are not order-specific actions.
- [ ] Bottom Recharge tab opens the in-app recharge form.
- [ ] Recharge methods, payment target, rate, amount input, proof upload, and submit button render without overlap.
- [ ] Recharge request submit creates a pending request and updates the recent recharge list.
- [ ] Balance pill opens the in-app Recharge tab.
- [ ] Account recharge shortcut opens the same in-app Recharge tab.
- [ ] Wallet activity labels include service/order/source where available.
- [ ] Support order selector lists recent customer-safe orders and does not expose provider names.
- [ ] Support ticket submit shows a clear success/error message.
- [ ] Bottom tabs stay pinned and readable after long scroll.
