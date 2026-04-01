# Financial Model

## Active Model

- `user`: customer wallet inside a reseller bot. This wallet belongs only to that customer within that bot.
- `reseller_main`: reseller owner wallet. This wallet is used for bot subscription renewals and owner-approved topups.
- `reseller_earnings`: reseller custom-profit wallet. This contains profit from the reseller's own services only.

## Platform Separation

- Platform services such as numbers, proxies, game topups, and apps are handled by the central CyberZone bot.
- Reseller bots do not execute platform-service purchases directly.
- There is no reserve model, no owner-fee model, and no reseller settlement model in the live system.

## Subscription Model

- First eligible bot per Telegram owner gets one free 30-day trial.
- Renewal plans:
  - 1 month: base price
  - 6 months: 10% discount
  - 12 months: 20% discount
- Subscription time is counted in exact 30-day blocks per month.
- Grace period is 3 days after the subscription end date.
- During grace, the bot stays active and users are warned that the bot will be suspended if the owner does not pay.
- After grace ends, the bot is suspended until the owner's `reseller_main` wallet has enough balance for renewal.

## Renewal Collection

- Renewal is charged only from `reseller_main`.
- Customer wallets are never used for bot subscription renewal.
- If the reseller wallet has enough balance when the subscription is checked, the renewal is collected automatically.
- If renewal happens during grace, the new paid period starts from the previous subscription end date, not from the payment moment.

## Recharge Flow

### Customer recharge

- A recharge request is created first.
- Credit is applied only after approval.
- Approval writes the wallet credit and ledger entry.

### Reseller main-wallet topup

- A recharge request is created with `wallet_type=reseller_main`.
- The request is reviewed by the owner.
- Approved topups credit the reseller owner's main wallet.
- Reseller topup requests are routed to the dedicated owner-group topic for reseller topups.

## Manual Balance Adjustment Policy

- Manual customer balance changes are support-only actions.
- They must go through the central wallet layer and always write a clear ledger reason.
- Recharge requests remain the normal path for adding customer credit.

## Audit Guidance

- Investigate any negative wallet immediately.
- Investigate any accepted recharge without a matching ledger credit.
- Investigate any paid or refunded order without ledger entries.

## Ledger Categories

- `core_purchase`
- `core_refund`
- `custom_purchase`
- `custom_refund`
- `recharge_credit`
- `manual_credit`
- `manual_adjustment`
- `other`
