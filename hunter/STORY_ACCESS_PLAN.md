# Hunter Story Access Validation

Goal: determine the exact official Meta API boundary for Instagram Stories before any Story-based discovery is integrated into Hunter.

## Rules

- Use only Meta Graph API surfaces available to the connected app/account.
- No authenticated browser scraping, session reuse, challenge bypass, or undocumented endpoint guessing.
- Do not claim arbitrary public Story access from an Instagram user ID alone.
- Keep `HUNTER_ACTION_ENABLED=false`; this sprint never contacts artists.

## Probe

1. Test the connected Instagram professional account's `/{ig-user-id}/stories` edge.
2. Optionally test Business Discovery for a known external professional username.
3. Record whether authorized Stories are available and whether external discovery exposes only profile/media data.
4. Save a machine-readable artifact that states the observed access boundary.

## Integration decision

- If authorized Stories are returned, Hunter may later ingest those Stories for accounts that explicitly authorize access.
- External/public Story discovery remains disabled unless Meta exposes a documented supported surface for it.
