# Empty Chair Release Policy

## Production source of truth

- `main` is the production branch.
- Render production must deploy from `main`.
- Feature work must not be developed directly on `main`.
- Use `feature/*`, `fix/*`, or `chore/*` branches for changes.
- Merge only after tests pass and the change has been reviewed or manually verified.

## Versioning

Use semantic-style pilot versions:

- `v1.1.0-pilot` — current pilot baseline
- patch fixes: `v1.1.1-pilot`, `v1.1.2-pilot`, ...
- backward-compatible features: `v1.2.0-pilot`
- breaking production changes: `v2.0.0`

Every production release should:

1. Update `CHANGELOG.md`.
2. Confirm GitHub Actions tests pass.
3. Merge to `main`.
4. Create a Git tag from the exact production commit.
5. Confirm Render deploy health.

## Rollback

Application rollback:

1. Identify the last known-good production tag or commit.
2. Revert or redeploy that commit.
3. Confirm `/health` and login.

Database rollback is separate from application rollback. Do not assume Git history protects production data.

## Database backups

Production PostgreSQL must have provider-level backups enabled.

Recommended minimum pilot policy:

- automatic daily database backups
- at least 7 days retention
- before any destructive migration, create or verify a fresh backup
- document restore instructions in the production operations notes

GitHub does not back up PostgreSQL data.

## Secrets

Never commit production secrets, API tokens, Stripe secrets, Google credentials, Instagram access tokens, or database URLs to GitHub. Keep them in Render environment variables or another secrets manager.
