# Hunter Sprint 8 — Hardening + Live Validation

## Goal
Prove Hunter is healthy on real scheduled/main runs and make failures diagnosable without confusing zero discovery with a broken pipeline.

## What this sprint adds
- `hunter/validate_run.py` validates every required stage artifact.
- JSON/schema mismatches fail closed.
- queue/action/attribution count invariants are cross-checked.
- zero public cancellation signals is a WARN, not a fake failure.
- validation emits both JSON and a GitHub job summary.
- validation runs with `if: always()` so partial runs still explain what broke.
- artifact upload also runs with `if: always()` so successful upstream output survives a later-stage failure.
- queue history is saved only after successful upstream stages, protecting the last known-good state.
- workflow concurrency serializes runs per ref so scheduled main runs cannot race the persisted queue.

## Validation states
- `PASS`: all expected artifacts exist, schemas match, and checked invariants hold.
- `WARN`: pipeline is structurally healthy but needs operator attention, currently including an empty discovery result.
- `FAIL`: required artifact missing/malformed, schema mismatch, or cross-stage invariant failure.

## Launch checklist

Before calling Hunter production-observable:

1. Merge Sprint 8 with Hunter CI and full app CI green.
2. Confirm the post-merge `main` Hunter workflow runs the live stages (PR runs intentionally skip them).
3. Open the latest main-run artifact bundle and confirm these files exist:
   - `hunter-signals.json`
   - `hunter-artists.json`
   - `hunter-scores.json`
   - `hunter-queue.json`
   - `hunter-actions.json`
   - `hunter-queue-after-actions.json`
   - `hunter-attribution.json`
   - `hunter-attribution-report.json`
   - `hunter-learning-report.json`
   - `hunter-validation.json`
4. Check `hunter-validation.json` status.
5. If discovery is WARN/empty, inspect collector queries/results before changing scoring.
6. Manually inspect a sample of resolved artists for real-world classification accuracy.
7. Manually inspect HOT/WARM ranking quality against the underlying public evidence.
8. Confirm queue `first_seen`, `last_seen`, cooldown, and action keys persist across at least two main runs.
9. Keep Sprint 5 action mode in preview unless an approved/manual action path is intentionally configured.
10. Do not apply Sprint 7 weight recommendations until their sample-size guard is satisfied and a human approves the change.

## Definition of done
Hunter can fail visibly, preserve diagnostic evidence, protect last-known-good queue state, and distinguish a healthy empty run from a structurally broken run.
