"""M4 operating-intelligence control plane.

Adds a bounded API that lets the signed-in shop ask M4 to inspect current Empty
Chair recovery state and activate an already-created OPEN opening through the
existing recovery engine. M4 does not bypass calendar, consent, cooldown,
delivery, sequential-offer, claim, or booking safeguards: execution delegates to
core.start_recovery_campaign, the same guarded path used by Fill Chairs.
"""
import json

from fastapi import Form, Request
from fastapi.responses import JSONResponse

import app as core
import m4_runtime


def _opening_context(conn, shop_id, opening_id):
    opening = core.db_fetchone(conn, "SELECT * FROM openings WHERE id=? AND shop_id=? LIMIT 1", (opening_id, shop_id))
    if not opening:
        return None, None, []
    artist = core.db_fetchone(conn, "SELECT * FROM artists WHERE id=? AND shop_id=? LIMIT 1", (opening["artist_id"], shop_id))
    customers = core.db_fetchall(conn, "SELECT * FROM customers WHERE shop_id=? AND communication_consent=1", (shop_id,))
    return opening, artist, customers


def _rank(opening, artist, customers):
    ranked = []
    for customer in customers:
        try:
            result = m4_runtime.score(dict(customer), dict(opening))
            ranked.append({
                "customer_id": customer["id"],
                "booking_probability": round(float(result.get("booking_probability", 0)), 4),
                "incremental_uplift": round(float(result.get("incremental_uplift", 0)), 4),
                "confidence": round(float(result.get("confidence", 0)), 4),
                "expected_value": round(float(result.get("expected_value", 0)), 2) if result.get("expected_value") is not None else None,
            })
        except Exception:
            continue
    ranked.sort(key=lambda x: (x["incremental_uplift"], x["booking_probability"], x["confidence"]), reverse=True)
    return ranked[:5]


@core.app.get("/api/m4/operator/status")
def m4_operator_status(request: Request):
    user = core.get_current_user(request)
    if not user:
        return JSONResponse({"error": "Sign in first."}, status_code=401)
    conn = core.connect()
    try:
        openings = core.db_fetchall(conn, "SELECT * FROM openings WHERE shop_id=? AND status='OPEN' ORDER BY date,start_time LIMIT 12", (user["shop_id"],))
        return JSONResponse({"ok": True, "shop_id": user["shop_id"], "openings": [dict(o) for o in openings]}, headers={"Cache-Control": "no-store"})
    finally:
        conn.close()


@core.app.post("/api/m4/operator/preview")
def m4_operator_preview(request: Request, opening_id: str = Form(...)):
    user = core.get_current_user(request)
    if not user:
        return JSONResponse({"error": "Sign in first."}, status_code=401)
    conn = core.connect()
    try:
        opening, artist, customers = _opening_context(conn, user["shop_id"], opening_id)
        if not opening:
            return JSONResponse({"error": "Opening not found for this shop."}, status_code=404)
        if opening["status"] != "OPEN":
            return JSONResponse({"error": "Only OPEN openings can be previewed."}, status_code=409)
        ranked = _rank(opening, artist, customers)
        return JSONResponse({
            "ok": True,
            "opening": dict(opening),
            "artist": dict(artist) if artist else None,
            "consented_candidates": len(customers),
            "m4_top_candidates": ranked,
            "execution": "preview_only",
            "guardrails": ["shop ownership", "communication consent", "calendar safety on activation", "existing contact cooldown", "sequential offers"],
        }, headers={"Cache-Control": "no-store"})
    finally:
        conn.close()


@core.app.post("/api/m4/operator/activate")
def m4_operator_activate(request: Request, opening_id: str = Form(...)):
    user = core.get_current_user(request)
    if not user:
        return JSONResponse({"error": "Sign in first."}, status_code=401)
    conn = core.connect()
    try:
        opening, artist, customers = _opening_context(conn, user["shop_id"], opening_id)
        if not opening:
            return JSONResponse({"error": "Opening not found for this shop."}, status_code=404)
        if opening["status"] != "OPEN":
            return JSONResponse({"error": "Opening is no longer OPEN."}, status_code=409)
        preview = _rank(opening, artist, customers)
    finally:
        conn.close()

    try:
        offer_id = core.start_recovery_campaign(opening_id)
        core.event("m4.operator_activated", "opening", opening_id, json.dumps({"offer_id": offer_id, "candidate_preview": preview[:3]}))
        return JSONResponse({
            "ok": bool(offer_id),
            "opening_id": opening_id,
            "offer_id": offer_id,
            "m4_top_candidates": preview,
            "message": "M4 handed this opening to Empty Chair's guarded recovery engine." if offer_id else "The recovery engine did not activate an offer; existing safety or eligibility rules may have blocked it.",
        }, headers={"Cache-Control": "no-store"})
    except Exception as exc:
        core.event("m4.operator_activation_failed", "opening", opening_id, json.dumps({"error": str(exc)}))
        return JSONResponse({"error": str(exc)}, status_code=409)
