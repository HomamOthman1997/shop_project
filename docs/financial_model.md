# Financial Model

## Wallets

- `user`: customer wallet scoped to a reseller.
- `reseller_main`: reseller operating wallet used to pay provider/base costs for core services.
- `reseller_earnings`: reseller profit wallet that accumulates commissions and custom profits until settlement.
- `owner_fees`: owner wallet that accumulates owner fees from custom services.

## Money Flow

### Core purchase

- User wallet is debited by `sale_price`.
- Reseller `main` wallet is debited by `cost_price`.
- Reseller `earnings` wallet is credited by `core_commission`.

### Custom purchase

- User wallet is debited by full `price`.
- Reseller `earnings` wallet is credited by net profit.
- Owner `owner_fees` wallet is credited by `owner_fee`.

### Refunds

- Refunds reverse the same wallet movements for the original flow.

## Recharge Flow

### User recharge

- A `recharge_request` is created first.
- Credit is applied only after acceptance.
- Acceptance writes to `wallets` and `ledger_entries`.

### Reseller core topup

- A `recharge_request` is created with `wallet_type=reseller_main`.
- After acceptance, the reseller `main` wallet is credited.

## Settlement

- `reseller_earnings` is the basis for monthly settlement.
- Drafts are generated per cycle.
- Owner confirms the cycle settlement.
- After payment confirmation, any lock is cleared.

## Manual Balance Adjustment Policy

- Manual user balance adjustments are admin-sensitive operations.
- They must use the central wallet layer only.
- They must always have a clear `reason` in ledger entries.
- They should be used for support corrections, not as a normal recharge path.
- Recharges should continue to go through `recharge_requests` whenever possible.

## Audit Guidance

- Investigate any negative wallet immediately.
- Investigate any accepted recharge without a matching ledger credit.
- Investigate any paid/refunded order without ledger entries.
- Treat locked overdue settlements as an owner follow-up item.

## Ledger Categories

- `core_purchase`
- `core_refund`
- `custom_purchase`
- `custom_refund`
- `recharge_credit`
- `settlement`
- `manual_credit`
- `manual_adjustment`
- `other`

Each ledger entry now also carries lightweight `category` and `tags` fields for filtering and future reporting.
