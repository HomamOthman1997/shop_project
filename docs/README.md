# Documentation Index

This directory is the primary home for project documentation.

## Start Here
- `PROJECT_CONTEXT.md`: current high-level product and architecture context.
- `AGENT_HANDOFF_CONTEXT.md`: compact context for future Codex/AI sessions.
- `platform/API_FIRST_PRODUCT_STRATEGY.md`: active API-first platform decision.
- `numbers/`: Numbers product docs and migration notes.
- `cards/`: Cards product docs.
- `digital/`: Digital products docs.
- `proxies/`: Proxy product docs.

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
- Shared product/API decisions belong in `platform/`.
- Product-specific docs must stay under their product folder.
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
- Do not mix Numbers, Cards, Digital, and Proxies planning in one backlog file.
- Move dated or superseded notes into `docs/archive/`.
- Avoid keeping duplicate raw provider specs when the content hash is identical.
