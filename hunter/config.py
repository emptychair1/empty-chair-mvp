"""Locked Sprint 0 rules for Empty Chair Hunter.

Hunter exists to find individual tattoo artists experiencing cancellation/opening pain now.
These rules are deliberately deterministic and explainable; later learning can tune weights.
"""

INTENT_PHRASES = (
    "had a cancellation",
    "last minute cancellation",
    "last-minute cancellation",
    "cancellation today",
    "cancellation tomorrow",
    "spot opened up",
    "spot just opened",
    "opening today",
    "opening tomorrow",
    "last minute opening",
    "last-minute opening",
    "last minute availability",
    "last-minute availability",
    "cancellation flash",
    "day opened up",
    "appointment opened up",
)

EXCLUSION_PHRASES = (
    "canceled design",
    "cancelled design",
    "event cancellation",
    "convention cancellation",
    "flight cancellation",
    "order cancellation",
    "subscription cancellation",
)

TATTOO_TERMS = (
    "tattoo",
    "tattooer",
    "tattooist",
    "tattoo artist",
    "flash",
    "day rate",
    "walk-in",
    "walk in",
    "booking",
)

URGENCY_TERMS = (
    "today",
    "tomorrow",
    "tonight",
    "this afternoon",
    "this evening",
    "last minute",
    "last-minute",
)

PRICE_TERMS = (
    "$",
    "day rate",
    "deposit",
    "discounted",
    "discount",
    "half day",
    "full day",
)

# Search engines often do not index fresh Instagram media directly. Hunter therefore uses
# both direct-Instagram queries and broader public-web queries that can resolve an artist's
# Instagram handle/profile from their own website, booking page, or public mirror.
SEARCH_QUERIES = tuple(
    query
    for phrase in INTENT_PHRASES
    for query in (
        f'site:instagram.com tattoo "{phrase}"',
        f'tattoo artist Instagram "{phrase}"',
    )
)

# Sprint 3 intent score. Missing/unknown information gets zero points rather than being
# guessed. Negative weights protect the queue from broad marketing and stale demand.
SCORE_WEIGHTS = {
    "explicit_cancellation": 35,
    "urgent": 20,
    "individual_artist": 15,
    "active_commercial_account": 10,
    "price_signal": 5,
    "us_location": 5,
    "very_recent_post": 10,
    "stale": -30,
    "generic_books_open": -15,
    "studio_account": -15,
}

HOT_THRESHOLD = 80
WARM_THRESHOLD = 60
STALE_HOURS = 72
VERY_RECENT_HOURS = 24
TARGET_COOLDOWN_HOURS = 72

TARGET_STATES = (
    "NEW",
    "HOT",
    "WARM",
    "ACTIONED",
    "CLICKED",
    "TRIAL",
    "ARMED",
    "PAID",
    "STALE",
    "SUPPRESSED",
)
