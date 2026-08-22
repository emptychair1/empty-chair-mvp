"""Privacy Trial Mode for Empty Chair analytics.

Shop-facing product surfaces keep normal shop-scoped identities. This module is the
separate analytics boundary: stable HMAC pseudonyms plus aggregate/operational
features only. Names, email, phone, addresses, raw images, free text, coordinates,
and ACS demographic values are never emitted by this interface.
"""
from __future__ import annotations

import hashlib
import hmac
import os
from collections import Counter

import app as core
import demand_core

ANALYTICS_SECRET = os.getenv("EMPTY_CHAIR_ANALYTICS_SECRET") or core.SESSION_SECRET
DEFAULT_MIN_GROUP_SIZE = max(3, int(os.getenv("EMPTY_CHAIR_ANALYTICS_MIN_GROUP_SIZE", "3")))


def _pseudo(kind: str, value: str) -> str:
    payload = f"empty-chair-trial-v1:{kind}:{value}".encode("utf-8")
    digest = hmac.new(ANALYTICS_SECRET.encode("utf-8"), payload, hashlib.sha256).hexdigest()
    return f"{kind}_{digest[:20]}"


def pseudonymous_customer_id(shop_id: str, customer_id: str) -> str:
    return _pseudo("customer", f"{shop_id}:{customer_id}")


def pseudonymous_shop_id(shop_id: str) -> str:
    return _pseudo("shop", shop_id)


def _bucket(value, cuts, labels):
    try:
        number = float(value)
    except Exception:
        return "unknown"
    for cut, label in zip(cuts, labels):
        if number < cut:
            return label
    return labels[-1]


def _customer_row(shop_id: str, customer_id: str):
    intel = demand_core.customer_intelligence(shop_id, customer_id)
    if not intel:
        return None
    behavioral = intel.get("behavioral") or {}
    practical = intel.get("practical") or {}
    contextual = intel.get("contextual") or {}
    travel = contextual.get("travel") or {}
    attribution = intel.get("attribution") or []

    outcome_classes = Counter()
    action_counts = Counter()
    for event in attribution:
        action_counts[str(event.get("action_type") or "unknown")] += 1
        klass = str(event.get("attribution_class") or "candidate")
        if klass in {"direct", "assisted", "organic", "candidate"}:
            outcome_classes[klass] += 1

    return {
        "customer_id": pseudonymous_customer_id(shop_id, customer_id),
        "shop_id": pseudonymous_shop_id(shop_id),
        "dna_completeness_bucket": _bucket(intel.get("completeness", 0), [0.25, 0.5, 0.75, 1.01], ["low", "developing", "strong", "high"]),
        "appointment_count_bucket": _bucket(behavioral.get("appointment_count", 0), [1, 3, 6, 10**9], ["0", "1-2", "3-5", "6+"]),
        "completed_count_bucket": _bucket(behavioral.get("completed_count", 0), [1, 3, 6, 10**9], ["0", "1-2", "3-5", "6+"]),
        "has_budget": bool(practical.get("budget")),
        "has_placement": bool(practical.get("placement")),
        "has_timing": bool(practical.get("timing")),
        "has_short_notice": bool(practical.get("short_notice")),
        "has_travel_preference": bool(practical.get("travel")),
        "drive_distance_bucket": _bucket(travel.get("drive_miles"), [10, 25, 50, 100, 10**9], ["<10mi", "10-24mi", "25-49mi", "50-99mi", "100mi+"]) if travel.get("drive_miles") is not None else "unknown",
        "offer_sent_count": int(action_counts.get("offer_sent", 0)),
        "claim_count": int(action_counts.get("offer_claimed", 0)),
        "booking_count": int(action_counts.get("booking_confirmed", 0)),
        "direct_outcomes": int(outcome_classes.get("direct", 0)),
        "assisted_outcomes": int(outcome_classes.get("assisted", 0)),
        "organic_outcomes": int(outcome_classes.get("organic", 0)),
    }


def pseudonymous_customer_rows(shop_id: str):
    """Return analytics-safe customer rows for one shop.

    This intentionally excludes identity, raw declared text, styles/motifs, exact
    location, latitude/longitude, ACS values, and raw event metadata.
    """
    conn = core.connect()
    try:
        customers = core.db_fetchall(conn, "SELECT id FROM customers WHERE shop_id=? ORDER BY id", (shop_id,))
    finally:
        conn.close()
    rows = []
    for customer in customers:
        row = _customer_row(shop_id, customer["id"])
        if row:
            rows.append(row)
    return rows


def _safe_group_counts(rows, key, minimum):
    counts = Counter(str(row.get(key) or "unknown") for row in rows)
    return {label: count for label, count in sorted(counts.items()) if count >= minimum}


def trial_analytics_snapshot(shop_id: str, min_group_size: int | None = None):
    """Return a privacy-bounded trial analytics snapshot.

    Customer-level rows are pseudonymous and contain only operational/bucketed
    features. Aggregate categorical groups below the minimum size are suppressed.
    """
    minimum = max(DEFAULT_MIN_GROUP_SIZE, int(min_group_size or DEFAULT_MIN_GROUP_SIZE))
    rows = pseudonymous_customer_rows(shop_id)
    total = len(rows)
    offers = sum(row["offer_sent_count"] for row in rows)
    claims = sum(row["claim_count"] for row in rows)
    bookings = sum(row["booking_count"] for row in rows)
    direct = sum(row["direct_outcomes"] for row in rows)
    assisted = sum(row["assisted_outcomes"] for row in rows)
    organic = sum(row["organic_outcomes"] for row in rows)

    return {
        "privacy_mode": "trial_pseudonymous_v1",
        "shop_id": pseudonymous_shop_id(shop_id),
        "minimum_group_size": minimum,
        "aggregate": {
            "customers": total,
            "offers_sent": offers,
            "claims": claims,
            "bookings": bookings,
            "claim_rate": round(claims / offers, 4) if offers else 0.0,
            "booking_rate": round(bookings / offers, 4) if offers else 0.0,
            "direct_outcomes": direct,
            "assisted_outcomes": assisted,
            "organic_outcomes": organic,
            "dna_completeness": _safe_group_counts(rows, "dna_completeness_bucket", minimum),
            "drive_distance": _safe_group_counts(rows, "drive_distance_bucket", minimum),
        },
        "customers": rows,
        "excluded_fields": [
            "name", "email", "phone", "address", "location", "latitude", "longitude",
            "raw_images", "raw_declared_text", "raw_event_metadata", "acs_demographic_values",
        ],
    }
