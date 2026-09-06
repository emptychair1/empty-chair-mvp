# Hunter Sprint 2 — Resolve the Artist

Builds on the existing Sprint 1 JSON collector without importing the production
app, changing the sales site, sending messages, or changing Sprint 0 weights.

## Run

```sh
pip install -r hunter/requirements.txt
python hunter/collect.py --out hunter-signals.json
python hunter/resolve.py --input hunter-signals.json --out hunter-artists.json
cd hunter
pytest -q
```

The existing half-hourly workflow now runs both stages and uploads both JSON
files. PRs and non-main branch pushes run tests only; collection and resolution
run on main. The workflow has read-only repository permissions, bounded network
requests, a 35-minute job timeout, and a concurrency group to avoid overlapping
runs on the same branch. It remains independent of Render and the app server.

## Resolution contract

- Resolve normalized Instagram profile URLs or public structured author/subject
  identities. Media URL shortcodes are never treated as usernames.
- Multiple different accounts are ambiguous; do not select the first link.
- Search snippets, the query, arbitrary mentions, and the collector's guessed
  username are not sufficient evidence for an artist's identity or biography.
- The collector now unwraps Bing's encoded destination URLs. Text-handle
  fallback requires an explicit Instagram handle/link; like counts and arbitrary
  mentions are not treated as page owners.
- Prefer public Instagram profile metadata. A uniquely identified structured
  Person/Organization on a public source can supply fallback profile context.
  A post caption or unrelated page body cannot supply the author's biography.
- Keep evidence for tattoo-artist classification, individual vs studio,
  commercial status, activity, and location. `null` means unknown, not false.
- Studio classification and tattoo-artist classification are separate fields;
  a studio is not automatically an individual artist.
- Commercial evidence requires a booking call to action. Explicit closed books
  override a booking call to action. Activity requires an actual publication
  timestamp within 90 days. Future, invalid, or timezone-free timestamps remain
  unknown. `discovered_at` is never used as a publication timestamp.
- Extract structured addresses or explicit city/state text, not bare ambiguous
  cities. Preserve an unknown country in a structured address without country.
  International structured addresses retain their country. Location is a
  heuristic with retained evidence, not independently verified residency.
- Each normalized account has a stable `account_id` derived from its platform
  and username. Multiple signals share one account record while retaining their
  source IDs/URLs, query, phrase, and discovery time. Conflicting classifications
  become unresolved. No fuzzy matching or merging of similar usernames.

The output schema is `empty-chair-hunter-artists-v1`. It includes `accounts`,
per-signal `resolutions`, input/unique-signal/account counts, status counts
(per signal), and the HTTP request count. Resolution statuses are `RESOLVED`,
`UNRESOLVED`, and `REJECTED`; they are not Sprint 4 target states.

Account deduplication is within the input batch, with stable IDs suitable for
cross-run upserts. This sprint does not add a persistent target database,
cooldown enforcement, fuzzy account rename matching, or the Sprint 4 queue.

## Failure behavior and limitations

The fetcher caches pages, bounds response size and request count, rejects
non-public destinations and credential-bearing URLs, and validates redirects.
Login walls, CAPTCHA/consent pages without usable metadata, blocked requests,
missing profiles, and identity conflicts remain unresolved. No authentication
or access-control bypass is attempted, and no Playwright fallback is introduced.
Generic profiles with insufficient evidence are deliberately not promoted.
DNS lookup failures are also fail-closed (`unsafe_url_or_unresolved_host`);
the resolver requires public DNS resolution in its execution environment.

Use `--max-requests N` to bound each run (default 120). Budget-exhausted signals
remain in the output for inspection/retry. Public metadata is often incomplete;
the real-world acceptance criterion still requires checking a representative
live batch against actual artist profiles. Passing fixture tests does not prove
that most live collected signals will resolve successfully.

## Regression coverage

Tests cover existing Sprint 1 behavior, URL validation and normalization,
media-owner resolution, conflicting identities, captions vs biographies,
public structured profile fallback, account deduplication, profile caching,
artist/studio/exclusion classifications, booking negation, activity dates,
US/international/ambiguous location handling, input validation, blocked and
oversized responses, redirect safety, request budgets, and CLI JSON output.
