# Secrets and Rotation Policy

Last updated: 2026-03-23

## Requirements

1. Production must use host secret manager (not long-lived `.env` on server).
2. Rotate high-risk keys/tokens every 90 days or less:
   - Telegram bot tokens
   - Mongo URI credentials
   - Provider API keys
   - Sentry auth token
3. Set:
   - `PRODUCTION_MODE=true`
   - `SECRETS_ROTATED_AT=<ISO date/datetime>`

## Startup enforcement

- Runtime startup guard now blocks production startup when:
  - local `.env` exists and `ALLOW_ENV_FILE_IN_PRODUCTION` is not enabled
  - placeholder/weak secrets are detected
  - `SECRETS_ROTATED_AT` is missing/invalid
  - secret age exceeds `SECRETS_MAX_AGE_DAYS`

## Rotation checklist

1. Rotate secrets in provider/system dashboard.
2. Update secret manager values.
3. Restart service.
4. Verify with:
   - `python scripts/health_check.py`
   - owner log topic and Sentry signal.
