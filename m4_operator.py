"""M4 operating-intelligence control plane.

The operator can inspect current shop inventory, preview M4 ranking, and activate
an OPEN opening through Empty Chair's guarded recovery path. The isolated public
demo uses a simulated activation so synthetic records can never trigger external
delivery.
"""
import json
import uuid

from fastapi import Form, Request
from fastapi.responses import JSONResponse

import app as core
import m4_runtime
import m4_integration

DEMO_SHOP_ID = "shop_live_demo"


def _opening_context(conn, shop_id, opening_id):
    opening = core.db_fetchone(conn, "SELECT * FROM openings WHERE id=? AND shop_id=? LIMIT 1", (opening_id, shop_id))
    if not opening:
        return None, None, []
    artist = core.db_fetchone(conn, "SELECT * FROM artists WHERE id=? AND shop_id=? LIMIT 1", (opening["artist_id"], shop_id))
    customers = core.db_fetchall(conn, "SELECT * FROM customers WHERE shop_id=? AND communication_consent=1", (shop_id,))
    return opening, artist, customers


def _rank(opening, artist, customers):
    ranked = []
    artist_dict = dict(artist) if artist else {}
    for customer in customers:
        try:
            customer_dict = dict(customer)
            result = m4_runtime.score(customer_dict, dict(opening))
            queue_score = m4_integration.m4_recovery_score(customer_dict, dict(opening), artist_dict)
            ranked.append({
                "customer_id": customer["id"],
                "name": customer.get("name") if hasattr(customer, "get") else customer["name"],
                "booking_probability": round(float(result.get("booking_probability", 0)), 4),
                "incremental_uplift": round(float(result.get("incremental_uplift", 0)), 4),
                "confidence": round(float(result.get("confidence", 0)), 4),
                "expected_value": round(float(result.get("expected_value", 0)), 2) if result.get("expected_value") is not None else None,
                "style_fit": round(float(result.get("style_fit", 0)), 3),
                "budget_fit": round(float(result.get("budget_fit", 0)), 3),
                "queue_score": round(float(queue_score), 2),
                "why": result.get("why") or [],
            })
        except Exception:
            continue
    ranked.sort(key=lambda x: (x["queue_score"], x["expected_value"] or 0, x["confidence"]), reverse=True)
    return ranked[:8]


@core.app.get("/api/m4/operator/status")
def m4_operator_status(request: Request):
    user = core.get_current_user(request)
    if not user:
        return JSONResponse({"error": "Sign in first."}, status_code=401)
    conn = core.connect()
    try:
        openings = core.db_fetchall(conn, "SELECT * FROM openings WHERE shop_id=? AND status='OPEN' ORDER BY date,start_time LIMIT 12", (user["shop_id"],))
        customer_row = core.db_fetchone(conn, "SELECT COUNT(*) AS n FROM customers WHERE shop_id=?", (user["shop_id"],))
        artist_row = core.db_fetchone(conn, "SELECT COUNT(*) AS n FROM artists WHERE shop_id=? AND active=1", (user["shop_id"],))
        synthetic = user["shop_id"] == DEMO_SHOP_ID
        return JSONResponse({
            "ok": True,
            "shop_id": user["shop_id"],
            "synthetic": synthetic,
            "dataset": {"customers": int(customer_row["n"] if customer_row else 0), "artists": int(artist_row["n"] if artist_row else 0)},
            "openings": [dict(o) for o in openings],
        }, headers={"Cache-Control": "no-store"})
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
            "synthetic": user["shop_id"] == DEMO_SHOP_ID,
            "opening": dict(opening),
            "artist": dict(artist) if artist else None,
            "consented_candidates": len(customers),
            "m4_top_candidates": ranked,
            "execution": "preview_only",
            "guardrails": ["shop ownership", "communication consent", "calendar safety on live activation", "contact cooldown", "sequential offers", "demo delivery suppression" if user["shop_id"] == DEMO_SHOP_ID else "production delivery safeguards"],
        }, headers={"Cache-Control": "no-store"})
    finally:
        conn.close()


def _simulate_demo_activation(opening_id, preview):
    """Create an internal synthetic offer without contacting any recipient."""
    if not preview:
        return None
    top = preview[0]
    offer_id = f"demo_m4_offer_{uuid.uuid4().hex[:10]}"
    now = core.now_iso()
    conn = core.connect()
    try:
        core.db_execute(conn, "INSERT INTO offers(id,opening_id,customer_id,score,rank,channel,sent_at,expires_at,status) VALUES (?,?,?,?,?,?,?,?,?)",
                        (offer_id, opening_id, top["customer_id"], top["queue_score"], 1, "synthetic", now, now, "SENT"))
        core.db_execute(conn, "UPDATE openings SET status='RECOVERY_ACTIVE' WHERE id=? AND shop_id=? AND status='OPEN'", (opening_id, DEMO_SHOP_ID))
        conn.commit()
    finally:
        conn.close()
    core.event("m4.synthetic_operator_activated", "opening", opening_id, json.dumps({"offer_id": offer_id, "customer_id": top["customer_id"], "queue_score": top["queue_score"], "external_delivery": False}))
    return offer_id


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
        synthetic = user["shop_id"] == DEMO_SHOP_ID
        offer_id = _simulate_demo_activation(opening_id, preview) if synthetic else core.start_recovery_campaign(opening_id)
        core.event("m4.operator_activated", "opening", opening_id, json.dumps({"offer_id": offer_id, "candidate_preview": preview[:3], "synthetic": synthetic}))
        return JSONResponse({
            "ok": bool(offer_id),
            "synthetic": synthetic,
            "external_delivery": False if synthetic else None,
            "opening_id": opening_id,
            "offer_id": offer_id,
            "m4_top_candidates": preview,
            "message": ("Synthetic recovery activated. M4 selected the top modeled customer and created an internal offer; no SMS or email was sent." if synthetic and offer_id else "M4 handed this opening to Empty Chair's guarded recovery engine." if offer_id else "The recovery engine did not activate an offer; existing safety or eligibility rules may have blocked it."),
        }, headers={"Cache-Control": "no-store"})
    except Exception as exc:
        core.event("m4.operator_activation_failed", "opening", opening_id, json.dumps({"error": str(exc)}))
        return JSONResponse({"error": str(exc)}, status_code=409)
