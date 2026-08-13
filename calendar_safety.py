"""Pre-offer Google Calendar safety for every Empty Chair recovery campaign."""

import app as core
import google_integration

_ORIGINAL_START_RECOVERY_CAMPAIGN = core.start_recovery_campaign


def _calendar_owner_and_opening(opening_id):
    conn = core.connect()
    try:
        opening = core.db_fetchone(
            conn,
            """
            SELECT o.*, s.timezone AS shop_timezone
            FROM openings o
            JOIN shops s ON s.id = o.shop_id
            WHERE o.id = ?
            LIMIT 1
            """,
            (opening_id,),
        )
        if not opening:
            return None, None
        calendar_user_id = google_integration.calendar_user_for_artist(opening["artist_id"])
        owner = {"id": calendar_user_id} if calendar_user_id else None
        return owner, opening
    finally:
        conn.close()


def start_recovery_campaign_calendar_safe(opening_id):
    owner, opening = _calendar_owner_and_opening(opening_id)
    if owner and opening and google_integration.calendar_connected(owner["id"]):
        start_iso = google_integration.slot_iso(
            opening["date"], opening["start_time"], opening["shop_timezone"]
        )
        end_iso = google_integration.slot_iso(
            opening["date"], opening["end_time"], opening["shop_timezone"]
        )
        try:
            available = google_integration.calendar_is_available_for_user(
                owner["id"], start_iso, end_iso
            )
        except Exception as exc:
            core.event("calendar.availability_error", "opening", opening_id, str(exc))
            available = None

        if available is False:
            conn = core.connect()
            try:
                core.db_execute(
                    conn,
                    """
                    UPDATE openings
                    SET status = 'NO_RECOVERY'
                    WHERE id = ? AND status IN ('OPEN', 'NO_RECOVERY')
                    """,
                    (opening_id,),
                )
                conn.commit()
            finally:
                conn.close()
            core.event("calendar.offer_blocked_busy", "opening", opening_id)
            return None

    return _ORIGINAL_START_RECOVERY_CAMPAIGN(opening_id)


core.start_recovery_campaign = start_recovery_campaign_calendar_safe
