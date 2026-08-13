"""Safety patches for Empty Chair Pilot v1.1.

The legacy recovery scorer reduces the score of recently contacted customers,
but Autopilot needs a hard cooldown so several simultaneously active openings
cannot contact the same person repeatedly. This module also filters Pilot recent
delivery data to the authenticated shop.
"""

import uuid
from datetime import datetime, timedelta, timezone

import app as core
import delivery_safety
import pilot


CONTACT_COOLDOWN_HOURS = 24
_ORIGINAL_SHOP_SNAPSHOT = pilot._shop_snapshot


def frequency_safe_recovery_queue(opening_id):
    conn = core.connect()
    try:
        opening = core.db_fetchone(
            conn,
            "SELECT * FROM openings WHERE id = ?",
            (opening_id,),
        )
        if not opening:
            return 0

        artist = core.db_fetchone(
            conn,
            "SELECT * FROM artists WHERE id = ?",
            (opening["artist_id"],),
        )
        if not artist:
            return 0

        existing_count_row = core.db_fetchone(
            conn,
            "SELECT COUNT(*) AS n FROM offers WHERE opening_id = ? AND status IN ('PENDING','SENT')",
            (opening_id,),
        )
        existing_count = int(existing_count_row["n"] or 0) if existing_count_row else 0
        if existing_count:
            return existing_count

        customers = core.db_fetchall(
            conn,
            """
            SELECT *
            FROM customers
            WHERE shop_id = ?
              AND communication_consent = 1
            ORDER BY completed_count DESC
            """,
            (opening["shop_id"],),
        )

        cutoff = datetime.now(timezone.utc) - timedelta(hours=CONTACT_COOLDOWN_HOURS)
        candidates = []
        for customer in customers:
            if delivery_safety.is_suppressed(conn, customer["id"]):
                continue
            if not delivery_safety.eligible_for_offer(customer):
                continue
            last_offer = core.parse_datetime(customer["last_offer_at"])
            if last_offer and last_offer > cutoff:
                continue

            score = core.recovery_score(customer, opening, artist)
            candidates.append((score, customer))

        candidates.sort(
            key=lambda item: (item[0], item[1]["completed_count"] or 0),
            reverse=True,
        )
        selected = candidates[:5]

        for rank, (score, customer) in enumerate(selected, start=1):
            offer_id = f"offer_{uuid.uuid4().hex[:12]}"
            placeholder_expiration = datetime.now(timezone.utc) + timedelta(minutes=30)
            core.db_execute(
                conn,
                """
                INSERT INTO offers(
                    id, opening_id, customer_id, score, rank,
                    channel, expires_at, status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    offer_id,
                    opening_id,
                    customer["id"],
                    score,
                    rank,
                    "sms",
                    placeholder_expiration.isoformat(),
                    "PENDING",
                ),
            )

        core.db_execute(
            conn,
            "UPDATE openings SET status = ? WHERE id = ?",
            ("RECOVERY_ACTIVE" if selected else "NO_RECOVERY", opening_id),
        )
        conn.commit()
        return len(selected)
    finally:
        conn.close()


def _delivery_belongs_to_shop(conn, shop_id, item):
    entity_id = item.get("entity_id")
    event_type = item.get("event_type")
    if not entity_id:
        return False

    if event_type == "offer.delivery":
        row = core.db_fetchone(
            conn,
            """
            SELECT ofr.id
            FROM offers ofr
            JOIN openings o ON o.id = ofr.opening_id
            WHERE ofr.id = ? AND o.shop_id = ?
            LIMIT 1
            """,
            (entity_id, shop_id),
        )
        return bool(row)

    if event_type == "booking.customer_notified":
        row = core.db_fetchone(
            conn,
            """
            SELECT b.id
            FROM bookings b
            JOIN openings o ON o.id = b.opening_id
            WHERE b.id = ? AND o.shop_id = ?
            LIMIT 1
            """,
            (entity_id, shop_id),
        )
        return bool(row)

    return False


def isolated_shop_snapshot(shop_id):
    snapshot = _ORIGINAL_SHOP_SNAPSHOT(shop_id)
    deliveries = snapshot.get("recent_deliveries", [])

    conn = core.connect()
    try:
        filtered = [
            item
            for item in deliveries
            if _delivery_belongs_to_shop(conn, shop_id, item)
        ]
    finally:
        conn.close()

    snapshot["recent_deliveries"] = filtered
    snapshot["metrics"]["successful_delivery_events"] = sum(
        1 for item in filtered if item.get("sms") or item.get("email")
    )
    snapshot["metrics"]["failed_delivery_events"] = sum(
        1 for item in filtered if not item.get("sms") and not item.get("email")
    )
    snapshot["autopilot_safety"] = {
        "contact_cooldown_hours": CONTACT_COOLDOWN_HOURS,
        "active_opening_window": pilot.AUTOPILOT_ACTIVE_WINDOW,
    }
    return snapshot


core.create_recovery_queue = frequency_safe_recovery_queue
pilot._shop_snapshot = isolated_shop_snapshot
