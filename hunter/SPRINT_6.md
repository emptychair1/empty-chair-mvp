# Hunter Sprint 6 — Attribution

Sprint 6 connects Hunter targets to measurable business outcomes without changing discovery, resolution, scoring, queueing, or action logic.

## Contract

- Stable `hunter_target_id` derived from the resolved Hunter account ID.
- First-party HTTPS signup link carrying `hunter_target_id` plus Hunter UTM tags.
- Target manifest preserves source signals, score explanation, queue state, action key, location, and discovery history.
- Lifecycle event contract: `VISIT`, `SIGNUP`, `TRIAL`, `ARMED`, `PAID`.
- Deterministic event idempotency prevents replayed conversion events from being counted twice.
- Explicit upstream `event_id` is honored as the idempotency key.
- First-touch and latest-touch are preserved per target.
- Furthest lifecycle stage is calculated per target.
- Multiple legitimate payment events roll up to the original Hunter target.
- Revenue, revenue per target, paid-target count, stage counts, and paid conversion rate are emitted in the report.
- Invalid/unknown events are ignored conservatively rather than guessed.

## Schemas

- `empty-chair-hunter-attribution-v1`
- `empty-chair-hunter-attribution-events-v1`
- `empty-chair-hunter-attribution-report-v1`

## Workflow

The scheduled Hunter workflow builds `hunter-attribution.json` and `hunter-attribution-report.json` after Sprint 5. Existing first-party event history can be supplied through `.hunter-state/hunter-attribution-events.json`.

Sprint 6 itself performs no outreach and does not enable Sprint 5 live execution.
