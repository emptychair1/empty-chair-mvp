"""Recover the rare case where Square has charged but booking finalization failed."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import v2_app as core


def _event(kind:str, artist_id:str|None, payload:dict):
    try:core.event(kind,artist_id,payload)
    except Exception as exc:print(f"Empty Chair paid-finalize event failed // {kind} // {exc}",flush=True)


def _recent_retry(payment_id:str)->bool:
    try:
        row=core.one(
            "SELECT id FROM events WHERE kind='payment.finalize_retry_failed' AND payload LIKE ? AND created_at>=? LIMIT 1",
            (f'%\"payment_id\":\"{payment_id}\"%',(datetime.now(timezone.utc)-timedelta(minutes=2)).isoformat()),
        )
        return bool(row)
    except Exception:return False


def retry_paid_finalizations():
    since=(datetime.now(timezone.utc)-timedelta(days=7)).isoformat()
    pending=core.all_rows(
        "SELECT * FROM events WHERE kind='payment.finalize_pending' AND created_at>=? ORDER BY created_at LIMIT 50",
        (since,),
    )
    for row in pending:
        try:payload=json.loads(row.get("payload") or "{}")
        except Exception:continue
        opening_id=payload.get("opening_id");offer_id=payload.get("offer_id");payment_id=payload.get("payment_id");provider=payload.get("provider") or "square"
        if not opening_id or not offer_id or not payment_id:continue
        if core.one("SELECT id FROM bookings WHERE opening_id=? LIMIT 1",(opening_id,)):continue
        if _recent_retry(payment_id):continue
        offer=core.one("SELECT * FROM offers WHERE id=?",(offer_id,))
        if not offer:continue
        try:
            core.finalize_booking(offer,provider,payment_id)
            booking=core.one("SELECT id FROM bookings WHERE opening_id=? LIMIT 1",(opening_id,))
            if booking:_event("payment.finalize_recovered",row.get("artist_id"),{"opening_id":opening_id,"offer_id":offer_id,"payment_id":payment_id,"booking_id":booking["id"]})
        except Exception as exc:
            _event("payment.finalize_retry_failed",row.get("artist_id"),{"opening_id":opening_id,"offer_id":offer_id,"payment_id":payment_id,"error":f"{type(exc).__name__}: {exc}"[:500]})


_original_worker_tick=core.worker_tick

def worker_tick():
    _original_worker_tick()
    try:retry_paid_finalizations()
    except Exception as exc:_event("worker.paid_finalize_retry_failed",None,{"error":f"{type(exc).__name__}: {exc}"[:500]})

core.worker_tick=worker_tick
print("Empty Chair 2.0 paid-finalization recovery loaded",flush=True)
