# Patching Workflow (Post V1)

This workflow is for safe periodic updates after `v1.0.0` is live.

## 1. Branching

- Keep `main` stable and releasable.
- For each patch, create a short branch from `main`:
  - `codex/patch-YYYYMMDD-short-name`
- For urgent production fixes:
  - `codex/hotfix-YYYYMMDD-short-name`

## 2. Commit Style

Use small, clear commits. Suggested format:

- `fix(numbers): cancel/refund edge case`
- `feat(custom-services): add folder move constraints`
- `refactor(providers): normalize provider error mapping`

## 3. Pull Request Rules

- One patch scope per PR.
- PR title should summarize impact clearly.
- Include:
  - what changed
  - why it changed
  - how it was tested
  - rollback notes (if needed)

## 4. Patch Release Steps

1. Merge PR into `main`.
2. Pull latest `main`.
3. Tag patch release:
   - `v1.0.1`, `v1.0.2`, ...
4. Push tag.
5. Update `CHANGELOG.md`:
   - move key notes from `Unreleased` into tagged version.

## 5. Minimal Command Flow

```bash
git checkout main
git pull origin main
git checkout -b codex/patch-20260312-short-name

# edit code
git add .
git commit -m "fix(scope): short description"
git push -u origin codex/patch-20260312-short-name
```

After PR merge:

```bash
git checkout main
git pull origin main
git tag v1.0.1
git push origin v1.0.1
```

## 6. Rollback Rule

- If a patch causes production issue:
  - revert the patch commit on `main`, or
  - deploy previous stable tag.
- Always record rollback reason in changelog notes.

