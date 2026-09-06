# Hunter Sprint 4 — Target Queue

Sprint 4 converts Sprint 3 scores into a safe, persistent next-action queue. It performs no outreach.

## Contract

- Input: `empty-chair-hunter-scores-v1`
- Optional history: prior `empty-chair-hunter-queue-v1`
- Output: `empty-chair-hunter-queue-v1`
- Only HOT and WARM resolved targets can be eligible.
- Highest score is prioritized first; recent verified activity breaks ties.
- Stale verified activity older than 72 hours is never actionable.
- Unknown activity is not guessed stale.
- Queue history preserves `first_seen`, `last_seen`, `last_action_at`, and progression state.
- A target action is blocked for 72 hours after `last_action_at`.
- The exact same account + evidence set cannot be actioned twice, even after cooldown.
- New evidence may become actionable after cooldown.
- CLICKED, TRIAL, ARMED, PAID, and SUPPRESSED progression states are never automatically reset by a new score run.
- Targets missing from a later score run are retained as STALE rather than silently disappearing.
- The workflow persists queue history between scheduled runs via GitHub Actions cache.

## Output fields

Each target records:

- account identity and profile URL
- score and Sprint 3 score state
- queue state and eligibility
- priority
- eligibility reason
- first/last seen timestamps
- last action and next eligible timestamps
- stable `action_key`
- signal IDs and score components
- last verified activity and location

`next_action_batch` is the ordered handoff contract for Sprint 5.
