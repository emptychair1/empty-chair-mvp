"""Outcome attribution classification for Empty Chair.

Direct: the same customer claimed an Empty Chair offer for the same opening.
Assisted: the customer received a recent Empty Chair intervention before a booking,
but the booking cannot be tied to a same-opening claim.
Organic: no qualifying recent Empty Chair intervention exists.

The classifier is intentionally conservative: only explicit runtime evidence earns
Direct attribution.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import app as core
import demand_core

DEFAULT_ASSIST_LOOKBACK_DAYS = 30


def _parse(value):
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


def classify_outcome(shop_id: str, customer_id: str, opening_id: str | None = None, observed_at: str | None = None, lookback_days: int = DEFAULT_ASSIST_LOOKBACK_DAYS, conn=None):
    owns = conn is None
    conn = conn or core.connect()
    try:
        demand_core.ensure_schema(conn)
        when = _parse(observed_at) or datetime.now(timezone.utc)
        cutoff = when - timedelta(days=max(1, int(lookback_days)))
        rows = core.db_fetchall(
            conn,
            "SELECT action_type,opening_id,channel,attribution_class,created_at FROM attribution_events WHERE shop_id=? AND customer_id=? ORDER BY created_at DESC",
            (shop_id, customer_id),
        )

        qualifying = []
        for row in rows:
            created = _parse(row["created_at"])
            if not created or created > when or created < cutoff:
                continue
            action = str(row["action_type"] or "")
            if action in {"offer_sent", "offer_claimed", "m4_intervention", "recovery_started"}:
                qualifying.append(row)

        if opening_id:
            for row in qualifying:
                if row["action_type"] == "offer_claimed" and str(row["opening_id"] or "") == str(opening_id):
                    return {
                        "class": "direct",
                        "reason": "same_opening_offer_claim",
                        "lookback_days": int(lookback_days),
                        "evidence_action": "offer_claimed",
                        "evidence_opening_id": str(opening_id),
                    }

        if qualifying:
            strongest = qualifying[0]
            return {
                "class": "assisted",
                "reason": "recent_empty_chair_intervention",
                "lookback_days": int(lookback_days),
                "evidence_action": strongest["action_type"],
                "evidence_opening_id": strongest["opening_id"],
            }

        return {
            "class": "organic",
            "reason": "no_recent_empty_chair_intervention",
            "lookback_days": int(lookback_days),
            "evidence_action": None,
            "evidence_opening_id": None,
        }
    finally:
        if owns:
            conn.close()


def record_booking_outcome(shop_id: str, customer_id: str, opening_id: str, booking_id: str, artist_id: str, amount: float = 0.0, observed_at: str | None = None):
    classification = classify_outcome(shop_id, customer_id, opening_id, observed_at=observed_at)
    demand_core.record_attribution(
        shop_id,
        customer_id,
        opening_id,
        "booking_confirmed",
        channel="recovery" if classification["class"] != "organic" else "organic",
        attribution_class=classification["class"],
        value=float(amount or 0),
        metadata={
            "booking_id": booking_id,
            "artist_id": artist_id,
            "source": "booking_outcome_classifier",
            "classification_reason": classification["reason"],
            "evidence_action": classification.get("evidence_action"),
            "evidence_opening_id": classification.get("evidence_opening_id"),
        },
    )
    demand_core.record_signal(
        shop_id,
        customer_id,
        "outcome.booking_confirmed",
        "empty_chair_runtime",
        {
            "booking_id": booking_id,
            "opening_id": opening_id,
            "artist_id": artist_id,
            "amount": float(amount or 0),
            "attribution_class": classification["class"],
        },
        confidence=1.0,
        observed_at=observed_at,
    )
    return classification
