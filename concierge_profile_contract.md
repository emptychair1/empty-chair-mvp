# Concierge profile contract

A Concierge submission creates both:

1. a row in `customers` scoped to the selected shop, and
2. a richer row in `concierge_leads` containing the volunteered zero-party profile.

`communication_consent` is written from the required explicit yes/no offer-consent choice. A `No` still creates the customer profile, but the customer is ineligible for automated Empty Chair outreach.
