# Hosted Deployment Runbook

Last updated: 2026-03-23

This runbook is the minimum production checklist for hosting the bots (`bot.py` and `bot_manager.py`) on a VPS or managed worker platform.

## 1. Required environment

Set these variables in host secrets:

- `BOT_ADMIN_TOKEN`
- `BOT_MAIN_TOKEN`
- `MONGO_URI`
- `DB_NAME`
- `OWNER_ID`

Recommended:

- `REDIS_URL` (if Redis cache is used in environment)
- `SENTRY_DSN`
- `SENTRY_ENVIRONMENT=production`
- `SENTRY_TRACES_SAMPLE_RATE=0.05` (or `0.0` if tracing is not needed yet)
- `SENTRY_SEND_DEFAULT_PII=false` (set to `true` only if you explicitly need user/IP/request context)

## 2. Build and start commands

- Build: `pip install -r requirements.txt`
- Owner bot: `python bot.py`
- Manager bot: `python bot_manager.py`

Run owner and manager as separate long-running services.

## 3. Routing prerequisites

Configure these from owner/admin panel before going live:

- Bot logs target (`chat_id` + topic when needed)
- Provider balance alert target (`chat_id` + topic when needed)

Important:

- Provider low-balance alerts are group-only routing (group/supergroup chat IDs).
- Do not use a private user chat as the provider alert target.

## 4. First boot verification

After deployment:

1. Verify both processes are running and polling.
2. Verify `/start` on owner and reseller/user flows.
3. Trigger one controlled error and confirm log arrives in logs topic.
4. Trigger provider alert check (or lower threshold temporarily) and confirm alert reaches owner group/topic.
5. Confirm DB indexes bootstrap without crash.

## 5. Recovery and operations

- If Mongo/Telegram DNS fails temporarily, keep process alive and allow auto-retry.
- If process exits, restart by process manager (systemd/pm2/supervisor/platform worker restart).
- Keep one instance of `bot_manager.py` only (singleton lock is enforced).

## 6. Minimum process manager policy

- Auto-restart on exit: enabled
- Start on boot: enabled
- Log retention: enabled
- Health check interval: 30-60s equivalent

## 7. Release procedure

1. Pull latest code.
2. Install/update dependencies.
3. Restart owner bot.
4. Restart manager bot.
5. Run smoke tests (numbers temp/rental, owner panel, reseller panel).
6. Check logs topic for 5-10 minutes.
