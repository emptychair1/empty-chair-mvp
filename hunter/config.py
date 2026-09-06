"""Locked Hunter rules and calibrated discovery/scoring configuration."""

INTENT_PHRASES = (
    "had a cancellation",
    "last minute cancellation",
    "last-minute cancellation",
    "cancellation today",
    "cancellation tomorrow",
    "someone canceled",
    "someone cancelled",
    "appointment fell through",
    "client rescheduled",
    "client moved their appointment",
    "had a no show",
    "had a no-show",
    "no show today",
    "no-show today",
    "spot opened up",
    "spot just opened",
    "slot opened up",
    "free spot",
    "free appointment",
    "opening today",
    "opening tomorrow",
    "available today",
    "available tomorrow",
    "same day availability",
    "same-day availability",
    "last minute opening",
    "last-minute opening",
    "last minute availability",
    "last-minute availability",
    "last minute spot",
    "last-minute spot",
    "need to fill this spot",
    "need to fill this appointment",
    "who wants this slot",
    "gap in my schedule",
    "walk-in availability",
    "walk in availability",
    "opening this week",
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
    "same day",
    "same-day",
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

# Public-web only. The second query family widens coverage beyond directly indexed
# Instagram pages while still requiring the resolver to tie evidence to a real account.
SEARCH_QUERIES = tuple(
    query
    for phrase in INTENT_PHRASES
    for query in (
        f'site:instagram.com tattoo "{phrase}"',
        f'tattoo artist Instagram "{phrase}"',
    )
)

SCORE_WEIGHTS = {
    "explicit_cancellation": 35,
    "schedule_disruption": 35,
    "fill_intent": 20,
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
