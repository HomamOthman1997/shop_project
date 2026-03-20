# Release Checklist

Use this list before every patch release.

## Scope

- [ ] Patch scope is clear and limited.
- [ ] No unrelated refactors included.
- [ ] User-facing text reviewed (EN/AR where applicable).

## Quality

- [ ] Critical flows tested manually:
  - [ ] temporary number buy
  - [ ] rental buy
  - [ ] cancel/refund
  - [ ] provider fallback behavior
  - [ ] reseller/owner key paths (if touched)
- [ ] Relevant tests passed (if available).
- [ ] No secrets added to code or logs.

## Provider Safety

- [ ] Provider errors are normalized for user messages.
- [ ] Internal provider names are not leaked in user-facing errors.
- [ ] Balance/availability filters behave correctly.

## Release Metadata

- [ ] `CHANGELOG.md` updated.
- [ ] Version tag selected correctly (`v1.0.x` for patches).
- [ ] Rollback note prepared.

## Deploy/Publish

- [ ] Branch merged to `main`.
- [ ] Release tag pushed.
- [ ] Bot restarted cleanly after deploy.
- [ ] Smoke test performed on live bot.

