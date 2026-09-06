# Hunter Sprint 7 — Learning Loop

Sprint 7 turns Sprint 6 attribution outcomes into evidence-backed learning without allowing Hunter to silently rewrite its own scoring model.

## Input

- `empty-chair-hunter-attribution-report-v1`
- optional `empty-chair-hunter-signals-v1` for source/query joins

## Output

- `empty-chair-hunter-learning-v1`
- default artifact: `hunter-learning-report.json`

## What it measures

Hunter compares conversion and revenue performance across:

- score bands
- scoring rules/components
- geography
- account type
- discovery source
- discovery query

It also identifies high-scoring non-converters as potential false positives and paid targets as high-value examples.

## Weight recommendations

Current `SCORE_WEIGHTS` are read from `config.py` and included in the report. Sprint 7 may recommend a bounded `+5` or `-5` change when a rule has at least 20 observed targets and at least 3 paid targets and its paid conversion rate materially differs from the overall baseline.

The learning stage never writes to `config.py`, never changes thresholds, and never applies recommendations automatically. Every recommendation includes `requires_human_approval=true`.

This is deliberate protection against small-sample overfitting and runaway self-modification.

## Workflow

On `main`, the Hunter workflow now runs:

1. discovery
2. resolution
3. intent scoring
4. target queue
5. action engine
6. attribution
7. learning report

PR runs continue to execute contract tests only for side-effecting pipeline stages.
