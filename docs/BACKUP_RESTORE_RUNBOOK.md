# Backup and Restore Runbook

Last updated: 2026-03-23

## Scope

- MongoDB primary data for this project
- Critical collections: `wallets`, `ledger_entries`, `orders`, `recharge_requests`, `bots`, `custom_services`

## Backup plan

1. Frequency: daily full backup, hourly oplog/incremental backup (if cluster supports it).
2. Retention:
   - Daily backups: 14 days
   - Weekly backups: 8 weeks
   - Monthly backups: 12 months
3. Storage:
   - Primary: cloud object storage with server-side encryption
   - Secondary: separate bucket/account for disaster isolation
4. Verification: each backup job must emit size + checksum + restore test status.

## Restore steps (operator)

1. Freeze writes:
   - stop bot processes (`bot_manager.py`, admin bot) or set maintenance mode.
2. Pick restore point:
   - choose backup timestamp + optional oplog window.
3. Restore into staging DB first:
   - never restore directly to production without staging verification.
4. Verify staging:
   - run `python scripts/health_check.py`
   - run `python scripts/export_financial_audit.py`
   - verify wallet totals and random order samples.
5. Production restore:
   - restore selected snapshot
   - replay oplog up to chosen timestamp (if used)
6. Post-restore checks:
   - run `python scripts/health_check.py`
   - run key pytest smoke set
   - restart bots and monitor owner log topic.

## Restore drill record (documented)

- Drill date: 2026-03-23
- Target: staging restore from latest backup snapshot
- Checks performed:
  - Mongo connectivity OK
  - Core collection counts readable
  - Financial audit export command successful
- Result: pass
- Follow-up action: automate checksum publication in deployment logs.
