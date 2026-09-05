"""Delivery-aware recovery offers for Empty Chair 2.0.

An offer is not SENT until Twilio accepts the message. Failed transports retry without
burning the client or starting the customer hold timer. Also repairs pre-fix SENT offers
that never recorded transport acceptance so the current recovery can continue.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import v2_app as core

RETRY_MINUTES = 2
MAX_DELIVERY_ATTEMPTS = 3


def _offer_text(artist: dict, opening: dict, offer: dict) -> str:
    url = f"{core.BASE_URL}/o/{offer['token']}"
    return (
        "EMPTY CHAIR // OPEN\n\n"
        f"{artist['name']} has an opening.\n\n"
        f"{core.fmt_when(opening['starts_at'])}\n"
        f"{core.hours_between(opening['starts_at'], opening['ends_at'])}\n"
        f"{core.fmt_money(int(opening['value_cents']))}\n\n"
        "+----------------------+\n"
        "|   TAKE THE CHAIR     |\n"
        "+----------------------+\n"
        f"{url}\n\n"
        f"held for {core.OFFER_MINUTES} min.\n\n"
        "Reply STOP to opt out."
    )


def _failed_attempts(offer_id: str) -> int:
    row = core.one(
        "SELECT COUNT(*) AS n FROM events WHERE kind='offer.delivery_failed' AND payload LIKE ?",
        (f'%\"offer_id\":\"{offer_id}\"%',),
    )
    return int(row["n"] if row else 0)


def send_next_offer(opening_id: str):
    opening = core.one("SELECT * FROM openings WHERE id=?", (opening_id,))
    if not opening or opening["status"] != "OPEN":
        return

    active = core.one(
        "SELECT * FROM offers WHERE opening_id=? AND status IN ('SENT','HOLDING') ORDER BY rank LIMIT 1",
        (opening_id,),
    )
    if active:
        return

    offer = core.one(
        "SELECT * FROM offers WHERE opening_id=? AND status='PENDING' ORDER BY rank LIMIT 1",
        (opening_id,),
    )
    if not offer:
        waiting = core.one(
            "SELECT * FROM offers WHERE opening_id=? AND status='RETRY' ORDER BY rank LIMIT 1",
            (opening_id,),
        )
        if waiting:
            return
        tried = core.one(
            "SELECT COUNT(*) AS n FROM offers WHERE opening_id=? AND status IN ('SENT','EXPIRED','PASSED','DELIVERY_FAILED')",
            (opening_id,),
        )["n"]
        core.run("UPDATE openings SET status='EMPTY' WHERE id=?", (opening_id,))
        artist = core.one("SELECT * FROM artists WHERE id=?", (opening["artist_id"],))
        core.artist_sms_empty(artist, opening, tried)
        core.event("opening.empty", opening["artist_id"], {"opening_id": opening_id, "tried": tried})
        return

    client = core.one("SELECT * FROM clients WHERE id=?", (offer["client_id"],))
    artist = core.one("SELECT * FROM artists WHERE id=?", (opening["artist_id"],))
    accepted = bool(client and core.send_sms(client.get("phone"), _offer_text(artist, opening, offer)))

    if accepted:
        now = core.utcnow()
        expires = (datetime.now(timezone.utc) + timedelta(minutes=core.OFFER_MINUTES)).isoformat()
        core.run(
            "UPDATE offers SET status='SENT',sent_at=?,expires_at=? WHERE id=?",
            (now, expires, offer["id"]),
        )
        core.run("UPDATE clients SET last_offered_at=? WHERE id=?", (now, offer["client_id"]))
        core.event(
            "offer.delivery.accepted",
            opening["artist_id"],
            {"opening_id": opening_id, "offer_id": offer["id"], "rank": offer["rank"]},
        )
        core.event(
            "offer.sent",
            opening["artist_id"],
            {"opening_id": opening_id, "offer_id": offer["id"], "rank": offer["rank"]},
        )
        return

    attempts = _failed_attempts(offer["id"]) + 1
    core.event(
        "offer.delivery_failed",
        opening["artist_id"],
        {"opening_id": opening_id, "offer_id": offer["id"], "rank": offer["rank"], "attempt": attempts},
    )
    if attempts >= MAX_DELIVERY_ATTEMPTS:
        core.run("UPDATE offers SET status='DELIVERY_FAILED',sent_at=NULL,expires_at=NULL WHERE id=?", (offer["id"],))
        send_next_offer(opening_id)
        return

    retry_at = (datetime.now(timezone.utc) + timedelta(minutes=RETRY_MINUTES)).isoformat()
    core.run(
        "UPDATE offers SET status='RETRY',sent_at=NULL,expires_at=? WHERE id=?",
        (retry_at, offer["id"]),
    )


def expire_offers():
    now = core.utcnow()
    expired = core.all_rows(
        "SELECT * FROM offers WHERE status='SENT' AND expires_at IS NOT NULL AND expires_at<?",
        (now,),
    )
    for offer in expired:
        core.run("UPDATE offers SET status='EXPIRED' WHERE id=?", (offer["id"],))
        send_next_offer(offer["opening_id"])

    retries = core.all_rows(
        "SELECT * FROM offers WHERE status='RETRY' AND expires_at IS NOT NULL AND expires_at<?",
        (now,),
    )
    for offer in retries:
        core.run("UPDATE offers SET status='PENDING',expires_at=NULL WHERE id=?", (offer["id"],))
        send_next_offer(offer["opening_id"])


# Worker/recovery functions reference these globals dynamically.
core.send_next_offer = send_next_offer
core.expire_offers = expire_offers


def _repair_pre_fix_offers():
    repaired = 0
    legacy = core.all_rows(
        "SELECT o.* FROM offers o JOIN openings p ON p.id=o.opening_id WHERE o.status='SENT' AND p.status='OPEN'"
    )
    for offer in legacy:
        accepted = core.one(
            "SELECT id FROM events WHERE kind='offer.delivery.accepted' AND payload LIKE ? LIMIT 1",
            (f'%\"offer_id\":\"{offer["id"]}\"%',),
        )
        if accepted:
            continue
        core.run("UPDATE offers SET status='PENDING',sent_at=NULL,expires_at=NULL WHERE id=?", (offer["id"],))
        repaired += 1

    if repaired:
        print(f"Empty Chair 2.0 repaired {repaired} pre-fix offer(s)", flush=True)
        openings = core.all_rows("SELECT id FROM openings WHERE status='OPEN'")
        for opening in openings:
            send_next_offer(opening["id"])


_repair_pre_fix_offers()
