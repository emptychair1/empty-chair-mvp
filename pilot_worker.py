"""Small in-process worker for Pilot Phase 1.

Render runs one web process for the pilot. This worker keeps campaigns moving
between page visits without adding Redis or another paid service. Database
state remains authoritative, so overlapping ticks are safe and idempotent.
"""

import os
import threading
from datetime import datetime, timezone

import app as core
import fill_chairs_flow


WORKER_INTERVAL_SECONDS = max(
    5,
    int(os.getenv("EMPTY_CHAIR_WORKER_INTERVAL_SECONDS", "30")),
)
WORKER_ENABLED = os.getenv("EMPTY_CHAIR_WORKER_ENABLED", "true").lower() == "true"

_stop_event = threading.Event()
_worker_thread = None
_tick_lock = threading.Lock()


def expire_due_offers() -> int:
    conn = core.connect()
    try:
        rows = core.db_fetchall(
            conn,
            """
            SELECT id
            FROM offers
            WHERE status = 'SENT'
              AND expires_at <= ?
            ORDER BY expires_at
            """,
            (datetime.now(timezone.utc).isoformat(),),
        )
    finally:
        conn.close()

    expired = 0
    for row in rows:
        try:
            core.expire_offer_and_continue(row["id"])
            expired += 1
        except Exception as exc:
            core.event("offer.expiration_failed", "offer", row["id"], str(exc))
    return expired


def active_shop_ids() -> list[str]:
    conn = core.connect()
    try:
        rows = core.db_fetchall(
            conn,
            """
            SELECT DISTINCT shop_id
            FROM autopilot_campaigns
            WHERE status = 'ACTIVE'
            """,
        )
        return [row["shop_id"] for row in rows]
    finally:
        conn.close()


def run_tick() -> None:
    if not _tick_lock.acquire(blocking=False):
        return
    try:
        expire_due_offers()
        for shop_id in active_shop_ids():
            fill_chairs_flow._activate_shop(shop_id)
    except Exception as exc:
        core.event("pilot.worker_failed", "system", "pilot-worker", str(exc))
    finally:
        _tick_lock.release()


def _worker_loop() -> None:
    while not _stop_event.wait(WORKER_INTERVAL_SECONDS):
        run_tick()


@core.app.on_event("startup")
def start_worker() -> None:
    global _worker_thread
    if not WORKER_ENABLED or (_worker_thread and _worker_thread.is_alive()):
        return
    _stop_event.clear()
    _worker_thread = threading.Thread(
        target=_worker_loop,
        name="empty-chair-pilot-worker",
        daemon=True,
    )
    _worker_thread.start()


@core.app.on_event("shutdown")
def stop_worker() -> None:
    _stop_event.set()
