# Log Retention Policy

Last updated: 2026-03-23

## Runtime logs

- Primary runtime logs are streamed to console/stdout and owner Telegram log topic.
- If file logging is enabled by host supervisor, enforce:
  - max file size: 50 MB
  - max files: 10
  - compression: enabled

## Data retention for operational collections

- `proxy_events`: 30 days
- `number_order_events`: 30 days
- low-signal `usage_stats` rows (`count <= 1` and stale): 180 days
- archived orders (`orders_archive`): 365 days

## Enforcement

- Automated lifecycle cleanup runs via scheduler every `LIFECYCLE_CLEANUP_INTERVAL_SEC` (default 6h).
- Cleanup metrics are stored in `system_settings._id=lifecycle_cleanup_metrics`.
- Owner can review cleanup metrics from `Ops Health Report`.
