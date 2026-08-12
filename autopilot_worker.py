"""Empty Chair autonomous recovery worker.

Run this as a single background process alongside the web service:

    python autopilot_worker.py

It advances expired recovery offers without requiring an owner to keep the
opening page open. The web app remains the source of truth for queue creation,
SMS delivery, claims, declines, and bookings.
"""

import os
import time
from datetime import datetime, timezone

from app import (
    connect,
    db_fetchall,
    event,
    parse_datetime,
    send_next_recovery_offer,
)

POLL_SECONDS = max(15, int(os.getenv("EMPTY_CHAIR_AUTOPILOT_POLL_SECONDS", "30")))


def active_recovery_openings():
    """Return IDs for openings that currently have recovery in progress."""
    conn = connect()
    try:
        rows = db_fetchall(
            conn,
            """
            SELECT id
            FROM openings
            WHERE status = 'RECOVERY_ACTIVE'
            ORDER BY created_at
            """,
        )
        return [row["id"] for row in rows]
    finally:
        conn.close()


def opening_needs_advance(opening_id):
    """True when an opening has no live offer or its live offer expired."""
    conn = connect()
    try:
        rows = db_fetchall(
            conn,
            """
            SELECT id, expires_at
            FROM offers
            WHERE opening_id = ?
              AND status = 'SENT'
            ORDER BY rank
            LIMIT 1
            """,
            (opening_id,),
        )
    finally:
        conn.close()

    if not rows:
        return True

    expiration = parse_datetime(rows[0]["expires_at"])
    return bool(expiration and datetime.now(timezone.utc) >= expiration)


def run_autopilot_once():
    """Advance every recovery campaign that currently needs attention."""
    advanced = 0

    for opening_id in active_recovery_openings():
        if not opening_needs_advance(opening_id):
            continue

        try:
            send_next_recovery_offer(opening_id)
            advanced += 1
        except Exception as exc:
            event(
                "autopilot.advance_failed",
                "opening",
                opening_id,
                str(exc),
            )

    return advanced


def main():
    print(
        "Empty Chair Autopilot worker started "
        f"(polling every {POLL_SECONDS}s)."
    )

    while True:
        run_autopilot_once()
        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    main()
