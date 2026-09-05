"""SMS-only communication policy for Empty Chair 2.0.

All customer and artist communication stays in text messages. Email delivery is disabled,
and weekly/monthly artist reports are sent over SMS through the same resilient transport.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import v2_app as core


def send_email_disabled(to: str | None, subject: str, text: str):
    """Intentionally disable email everywhere in the 2.0 product."""
    return False


def send_digests_if_due_sms(artist: dict):
    now = datetime.now().astimezone()
    aid = artist["id"]

    week = f"{now.isocalendar().year}-W{now.isocalendar().week:02d}"
    kind = f"digest.weekly.{week}"
    if now.weekday() == 0 and now.hour >= 8 and not core.one(
        "SELECT * FROM events WHERE artist_id=? AND kind=? LIMIT 1", (aid, kind)
    ):
        since = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
        stats = core.one(
            "SELECT COUNT(*) AS cancellations,"
            "SUM(CASE WHEN status='FILLED' THEN 1 ELSE 0 END) AS fills,"
            "COALESCE(SUM(CASE WHEN status='FILLED' THEN value_cents ELSE 0 END),0) AS recovered "
            "FROM openings WHERE artist_id=? AND created_at>=?",
            (aid, since),
        )
        cancellations = int(stats["cancellations"] or 0)
        fills = int(stats["fills"] or 0)
        recovered = int(stats["recovered"] or 0)
        pct = round(100 * fills / cancellations) if cancellations else 0
        body = (
            "EMPTY CHAIR // WEEK\n\n"
            f"recovered........{core.fmt_money(recovered)}\n"
            f"cancellations....{cancellations}\n"
            f"fills............{fills}\n"
            f"recovery.........{pct}%\n\n"
            "nothing to do."
        )
        if core.send_sms(artist.get("phone"), body):
            core.event(kind, aid, stats)

    month = now.strftime("%Y-%m")
    kind = f"digest.monthly.{month}"
    if now.day == 1 and now.hour >= 8 and not core.one(
        "SELECT * FROM events WHERE artist_id=? AND kind=? LIMIT 1", (aid, kind)
    ):
        first = datetime(now.year, now.month, 1, tzinfo=now.tzinfo).astimezone(timezone.utc)
        prev = (first - timedelta(days=1)).replace(day=1)
        stats = core.one(
            "SELECT COUNT(*) AS cancellations,"
            "SUM(CASE WHEN status='FILLED' THEN 1 ELSE 0 END) AS fills,"
            "COALESCE(SUM(CASE WHEN status='FILLED' THEN value_cents ELSE 0 END),0) AS recovered "
            "FROM openings WHERE artist_id=? AND created_at>=? AND created_at<?",
            (aid, prev.isoformat(), first.isoformat()),
        )
        cancellations = int(stats["cancellations"] or 0)
        fills = int(stats["fills"] or 0)
        recovered = int(stats["recovered"] or 0)
        pct = round(100 * fills / cancellations) if cancellations else 0
        body = (
            "EMPTY CHAIR // MONTH\n\n"
            f"recovered value..{core.fmt_money(recovered)}\n"
            f"cancellations....{cancellations}\n"
            f"fills............{fills}\n"
            f"recovery.........{pct}%\n\n"
            "Your cancellation protection receipt."
        )
        if core.send_sms(artist.get("phone"), body):
            core.event(kind, aid, stats)


# Existing customer confirmation paths call core.send_email dynamically; making it a
# no-op removes email without touching the recovery/payment/calendar flow.
core.send_email = send_email_disabled
core.send_digests_if_due = send_digests_if_due_sms
print("Empty Chair 2.0 communications: SMS only", flush=True)
