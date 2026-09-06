# Hunter Sprint 3 — Score Intent

Sprint 3 ranks resolved tattoo-artist accounts by evidence of immediate cancellation pain.
It does not perform outreach, write to the Empty Chair production database, or guess missing facts.

## Locked score

| Evidence | Points |
| --- | ---: |
| Explicit cancellation | +35 |
| Today/tomorrow/last-minute urgency | +20 |
| Individual tattoo artist | +15 |
| Active commercial account | +10 |
| Price/day-rate clue | +5 |
| Verified US location | +5 |
| Verified post/activity timestamp within 24h | +10 |
| Verified timestamp older than 72h | -30 |
| Generic books-open promotion | -15 |
| Studio account | -15 |

Scores are clamped to 0–100. Unknown evidence is worth zero.

- `HOT`: 80–100 and the account is a resolved tattoo artist.
- `WARM`: 60–79 and the account is a resolved tattoo artist.
- `IGNORE`: below 60 or the account is unresolved/rejected.

## Evidence rules

- The original Sprint 1 signal title/snippet/matched phrase supplies cancellation, urgency, and price evidence.
- Sprint 2 supplies artist type, commercial activity, location, and verified activity time.
- `discovered_at` is never used as a post/activity timestamp.
- A future, malformed, or missing activity timestamp earns neither freshness points nor a stale penalty.
- Every applied component is emitted with its points and source evidence.

## Output

`score.py` writes `empty-chair-hunter-scores-v1`, sorted by score descending. Each target includes its score, state, component explanations, signal IDs, activity timestamp, and location.

The scheduled Hunter workflow now produces:

1. `hunter-signals.json`
2. `hunter-artists.json`
3. `hunter-scores.json`

`ranking_separation` compares the top and bottom cohorts (up to 20 each) as the Sprint 3 quality diagnostic.
