# Demand Engine Tattoo Finder

Tattoo Finder is a reusable public acquisition strategy owned by Demand Engine.

## V1 flow

`/tattoo-finder/{market}` captures:

- tattoo idea
- placement
- approximate size
- style/reference description
- budget
- timing
- name, phone, optional email
- explicit contact opt-in

The submission is persisted through the existing Concierge lead/customer persistence path and tagged in `profile_json` with `acquisition_mode=tattoo_finder` and the market. When an active acquisition campaign exists for the market identity, the lead also receives the existing campaign/source/artist-identity attribution.

## First deployment

Athens is the first market because an active acquisition identity already exists there. The route is market-based rather than Josh-specific so the same strategy can be reused for other artists and cities.

## Boundaries

Tattoo Finder captures demand. It does not claim a booking, price, artist match, or availability. Matching and downstream conversion remain responsibilities of M4 / Concierge / Apprentice workflows.
