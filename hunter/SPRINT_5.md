# Hunter Sprint 5 — Action Engine

Goal: every eligible target can receive a concrete acquisition attempt through an explicitly approved action adapter, with no duplicate firing and a complete audit trail.

## Built

- consumes Sprint 4 `next_action_batch`
- re-checks eligibility and the 72-hour cooldown immediately before execution
- uses Sprint 4 `action_key` as an idempotency key
- records an `ATTEMPT_STARTED` journal entry before any external request
- first live adapter: operator-approved HTTPS webhook
- bearer token support without writing secrets to artifacts
- retries only transport failures and transient HTTP statuses (`408`, `425`, `429`, `5xx` allowlist)
- does not retry permanent `4xx` failures
- records `SUCCEEDED`, `FAILED`, `BLOCKED`, `SKIPPED`, or `PREVIEW`
- only successful delivery moves the target to `ACTIONED`
- failed/blocked/preview actions leave the target eligible for later handling
- preserves account, source signal IDs, score evidence, priority, and action key
- writes `hunter-actions.json`, updated queue state, and an execute-mode JSONL journal

## Activation safety

GitHub Actions runs Sprint 5 in preview mode by default. Live execution requires both:

- repository variable `HUNTER_ACTION_ENABLED=true`
- secret `HUNTER_ACTION_WEBHOOK_URL` containing an approved HTTPS endpoint

Optional secret `HUNTER_ACTION_WEBHOOK_TOKEN` supplies bearer authentication.

The action engine does not implement unofficial Instagram automation, private scraping, credential harvesting, moderation evasion, or hidden production-app writes.

## Definition of done

Given an eligible HOT/WARM target and a configured approved webhook, Hunter makes exactly one idempotent acquisition attempt, records the result, and marks the target `ACTIONED` only after a successful response.
