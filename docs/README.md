# Documentation Index

This directory is the primary home for project documentation.

## Start Here
- `PROJECT_CONTEXT.md`: current high-level product and architecture context.
- `AGENT_HANDOFF_CONTEXT.md`: compact context for future Codex/AI sessions.
- `NUMBERS_MINIAPP_MIGRATION_CHECKLIST.md`: current Mini App migration checklist.
- `NUMBERS_TELEGRAM_FLOW_AUDIT.md`: Telegram bot flow coverage audit.

## Operational Docs
- `BACKUP_RESTORE_RUNBOOK.md`
- `HOSTED_DEPLOYMENT_RUNBOOK.md`
- `INCIDENT_RESPONSE_PLAYBOOK.md`
- `PATCHING_WORKFLOW.md`
- `RELEASE_CHECKLIST.md`
- `SECRETS_POLICY.md`
- `LOG_RETENTION_POLICY.md`

## Product / Planning Docs
- Active product direction belongs in `PROJECT_CONTEXT.md` and `AGENT_HANDOFF_CONTEXT.md`.
- Older planning drafts live under `archive/legacy-planning/`.

## Provider Docs
- `providers/READ_ME_FIRST.md`: provider-doc navigation notes.
- `providers/index.json`: machine-readable provider docs index.
- `providers/manual/`: curated local manual references.
- `providers/raw/`: raw imported OpenAPI/Postman/HTML source files.

## Archive
- `archive/`: historical notes, old chat exports, and dated handoff documents kept for reference only.
- `archive/generated-reports/`: generated analysis reports kept for audit/reference.
- `archive/legacy-planning/`: superseded planning and checklist drafts.

## Cleanup Rules
- Keep active docs in `docs/`.
- Move dated or superseded notes into `docs/archive/`.
- Avoid keeping duplicate raw provider specs when the content hash is identical.
