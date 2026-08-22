# M4 Practical Fit + Enrichment V1

This slice completes the first production path for customer context and practical-fit ranking.

## Inputs

Concierge zero-party inputs now include:

- budget
- placement
- timing
- short-notice availability
- artist preference
- travel radius
- city / ZIP location

Shop setup accepts a physical address so customer travel can be evaluated against the real studio destination.

## Enrichment

Explicit customer location may be enriched with:

1. US Census geocoding
2. 2024 ACS 5-year tract context
3. OSRM drive distance / time, with a haversine degraded-mode fallback

ACS fields are stored under `area_context` and marked `area_level_context_only`. They are context about an area, never claims about an individual customer.

All persisted customer enrichment carries source, confidence and observed time through Demand Graph signals and enrichment context provenance.

## M4 practical fit

M4 can now calculate bounded component fits for:

- declared budget vs opening price
- desired placement vs artist portfolio placement evidence
- declared travel radius vs drive distance
- declared timing vs actual opening date/time
- short-notice willingness vs actual lead time
- declared artist preference

Practical fit has a bounded maximum influence of 22% of the combined queue score and is scaled by Demand Graph confidence. Tattoo DNA remains separately bounded. Existing behavioral evidence, consent, cooldown, sequential-offer and calendar safeguards remain authoritative.

## Customer Intelligence

`demand_core.customer_intelligence()` now exposes one coherent object containing:

- identity
- declared
- behavioral
- visual
- practical
- affinity
- contextual
- provenance
- attribution

The contextual section contains geocode, area context and travel data when available, plus its own source/confidence/observed-at provenance.
