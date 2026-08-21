# Concierge shop binding invariant

For an authenticated Empty Chair session, Concierge submissions always bind to the authenticated user's shop. A stale or default `shop_id` embedded in a previously opened Concierge page may never override the signed-in shop. Public unauthenticated Concierge links may explicitly specify `shop_id`; otherwise they fall back to the isolated demo shop.
