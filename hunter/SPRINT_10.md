# Hunter Sprint 10 — Discovery + Scoring Calibration

Goal: widen the public discovery net while making the actionable queue stricter.

## Discovery expansion

Hunter now recognizes additional schedule-pain language such as:

- someone canceled / cancelled
- appointment fell through
- client rescheduled / moved their appointment
- no-show
- slot opened up
- free spot / free appointment
- available today / tomorrow
- same-day availability
- last-minute spot
- need to fill this spot / appointment
- who wants this slot
- gap in my schedule
- walk-in availability
- opening this week

Every phrase is searched both as a direct public Instagram query and a broader public-web query. Resolution standards are unchanged: a signal still must resolve to a real tattoo account before it can be scored.

## Ranking calibration

- Known activity older than 72 hours is `IGNORE` even if the historical copy is strong.
- Unknown freshness is not fabricated as recent or stale; it remains reviewable if other evidence is strong enough.
- Explicit cancellation language remains strongest.
- No-show/reschedule/fell-through language is treated as a schedule disruption without pretending it was literally a cancellation.
- Specific fill-now language receives a smaller fill-intent boost.
- Generic books-open language alone cannot become actionable.
- HOT/WARM targets sort ahead of historical IGNORE rows.

## Diagnostics

Score payloads now include:

- `freshness`
- `activity_age_hours`
- `eligibility_reason`
- freshness counts
- eligibility-reason counts
- actionable count

## Safety invariants

- Public web only.
- No private Instagram endpoints.
- No authenticated scraping.
- No automatic contact or outreach.
- No discovery timestamp used as publication/activity time.
- Widening discovery does not weaken artist identity resolution.
