# Hunter Sprint 9 // Operator Console

Goal: turn Hunter's pipeline artifacts into an owner-operated review queue without adding automatic outreach.

## Flow

```text
Hunter pipeline
  -> validated operator snapshot
  -> authenticated production ingest
  -> owner-only review console
  -> APPROVED / SUPPRESSED / BAD_FIT
  -> audit trail
```

Approval is an internal operator decision only. It does not contact a target, enable the Sprint 5 action engine, or change scoring weights.

## Included

- ranked target inbox
- username, profile, location, score, score state, queue state, priority, and recency
- per-rule scoring evidence
- original discovery source excerpts, matched phrase, and source link
- action history fields
- attribution stage and attributed revenue
- HOT/WARM/ACTIONED/PAID filters
- PENDING/APPROVED/SUPPRESSED/BAD_FIT filters
- score/recency/revenue sorting
- artist/location search
- individual target decisions
- bulk selected-target decisions, max 200 per request
- validation warnings surfaced at the top of the console
- learning recommendations surfaced as human-approval-only suggestions
- database-backed operator audit trail
- manual decisions persist across Hunter snapshot refreshes
- authenticated snapshot ingest with a 5 MB request cap and 5,000-target cap
- production v2 bootstrap integration

## Production routes

- `GET /owner/hunter` — admin-only operator console
- `POST /owner/hunter/{account_id}/decision` — one manual decision
- `POST /owner/hunter/bulk` — selected-target manual decisions
- `POST /internal/hunter/operator/snapshot` — bearer-authenticated Hunter snapshot ingest

## Required production configuration

Render:

```text
EMPTY_CHAIR_ADMIN_EMAILS=<comma-separated operator account emails>
HUNTER_OPERATOR_INGEST_TOKEN=<strong shared secret>
```

GitHub Actions secrets:

```text
HUNTER_OPERATOR_INGEST_URL=https://app.tryemptychair.com/internal/hunter/operator/snapshot
HUNTER_OPERATOR_INGEST_TOKEN=<same shared secret>
```

If the GitHub ingest URL/token are absent, Hunter still builds and uploads `hunter-operator-snapshot.json`; production sync is skipped safely.

## Artifact

`hunter-operator-snapshot.json` uses schema `empty-chair-hunter-operator-v1`.

## Definition of done

Every ranked Hunter target can be reviewed with its evidence and outcome context, manually approved/suppressed/rejected, and traced through an operator audit record. No manual decision creates third-party outreach by itself.
