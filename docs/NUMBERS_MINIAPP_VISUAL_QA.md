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

- [ ] Temporary number waiting state shows timeline and refresh/cancel actions.
- [ ] Temporary number code state shows code and copy actions.
- [ ] Refund action shows busy overlay and cannot be double-clicked.
- [ ] Call number waiting state shows timeline and Check call action.
- [ ] Call recording can be played in-app and downloaded.
- [ ] Rental number shows SMS, finish, renew, wake, and notes actions when supported.

## Account And Support

- [ ] Balance pill opens recharge in Telegram.
- [ ] Account recharge button opens the same recharge destination.
- [ ] Wallet activity labels include service/order/source where available.
- [ ] Support ticket submit shows a clear success/error message.
- [ ] Bottom tabs stay pinned and readable after long scroll.
