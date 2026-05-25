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

- [ ] Balance pill opens recharge in Telegram.
- [ ] Account recharge button opens the same recharge destination.
- [ ] Wallet activity labels include service/order/source where available.
- [ ] Support ticket submit shows a clear success/error message.
- [ ] Bottom tabs stay pinned and readable after long scroll.
