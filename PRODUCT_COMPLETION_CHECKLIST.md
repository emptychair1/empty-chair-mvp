# Empty Chair Product Completion Checklist

This is the frozen MVP completion scope for the private tattoo-shop demand intelligence system.

## P0 — Data spine

- [x] Core tenant model: shops, artists, customers, openings, offers, bookings, events.
- [x] Concierge creates real shop-scoped leads/customers with explicit communication consent.
- [x] Customer inspiration ingestion and visual analysis.
- [x] Tattoo DNA persistence.
- [x] Artist portfolio ingestion and Artist DNA persistence.
- [x] Tattoo DNA × Artist DNA affects the production M4 recovery queue.
- [x] Unified Customer Intelligence read model across declared, behavioral, visual, practical, affinity and contextual evidence.
- [ ] Field/signal provenance for every new customer intelligence fact.

## P0 — Decision quality

- [x] Booking probability, uplift, confidence and artist affinity contribute to M4 ranking.
- [x] Visual DNA match contributes with bounded weight.
- [x] Budget fit uses declared practical fit.
- [ ] Placement/project-scale fit contributes where evidence exists. (Placement is live; project-scale still needs a production feature.)
- [x] Travel radius / real drive-time fit contributes where evidence exists.
- [x] M4 explanations expose every material decision component.

## P0 — Attribution and learning

- [x] Record every actual M4/Empty Chair intervention as an attribution event.
- [x] Record claims and confirmed bookings against the originating intervention.
- [ ] Classify direct / assisted / organic outcomes.
- [x] Write outcome signals back into Customer Intelligence.
- [ ] Add holdout support for future incrementality measurement.

## P0 — Privacy and ownership

- [x] Shop-scoped application queries for core Demand Graph data.
- [x] Explicit customer communication consent gates production recovery eligibility.
- [ ] Signed, expiring public Concierge sessions.
- [ ] Expire unclaimed/pending inspiration uploads.
- [ ] Customer export endpoint.
- [ ] Customer deletion endpoint including inspiration assets and derived intelligence.
- [ ] Shop export/delete lifecycle.
- [ ] Encrypt sensitive raw assets at rest at the application/storage layer or move them to encrypted object storage.
- [ ] Trial privacy mode: shop sees identities; Empty Chair trial analytics can operate on pseudonymous/aggregate data.

## P1 — Enrichment v1

- [x] Geocode customer location with explicit provenance.
- [x] Census/ACS area context; label all values as area-level, never individual facts.
- [x] Drive-time / distance-to-shop feature.
- [ ] Contact validation/hygiene.
- [ ] Enrichment freshness and retry policy.

## P1 — Production proof

- [ ] End-to-end test: Concierge → customer → Tattoo DNA → enrichment → Artist DNA → M4 ranking → offer → claim → booking → attribution → learning.
- [ ] Cross-shop isolation tests for Customer DNA, Artist DNA and attribution.
- [ ] Public upload/session abuse tests.
- [ ] DNA ranking regression tests.
- [x] Attribution tests.
- [ ] Enrichment failure/degraded-mode tests.

## Later — deliberately out of current completion scope

- Pinterest authorization and board ingestion.
- Instagram-permitted affinity signals.
- Weather and local-event context.
- Cross-shop pooling of customer identities or demand (explicitly not part of the trust model).
