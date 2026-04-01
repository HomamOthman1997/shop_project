# Incident Response Playbook

Last updated: 2026-03-23

## Severity levels

- `SEV-1`: payments/ledger integrity risk, full bot outage, security compromise
- `SEV-2`: degraded purchases/refunds, major provider outage
- `SEV-3`: partial feature degradation, non-critical errors

## First 15 minutes

1. Acknowledge incident in owner ops channel/topic.
2. Capture timestamp, affected flows, first visible error.
3. Triage blast radius:
   - numbers
   - proxies
   - game store
   - finance/recharge
4. Stabilize:
   - disable risky paths (temporary toggles)
   - keep financial consistency over feature availability
5. Assign roles:
   - Incident lead
   - Investigator
   - Communications owner

## Technical checklist

1. Check bot runtime health:
   - `python scripts/health_check.py`
2. Check error stream:
   - Telegram log topic + Sentry issues
3. Check financial safety:
   - run `/financial_audit` from owner panel
4. Check pending order/recovery sweeps:
   - verify scheduler logs for recovery cycles
5. Record mitigation decisions with exact UTC time.

## Recovery and closure

1. Confirm service restored and error rate normalized.
2. Backfill/refund stuck orders if required.
3. Publish incident summary:
   - root cause
   - impacted users
   - financial impact
   - remediation
4. Add regression test and checklist update before closure.
