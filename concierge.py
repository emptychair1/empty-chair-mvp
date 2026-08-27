"""Empty Chair Concierge: customer-side zero-party intelligence experience."""
import json
import uuid

from fastapi import Form, Request
from fastapi.responses import HTMLResponse, JSONResponse

import app as core
import concierge_leads
import concierge_pilot
import demand_engine
import demand_core
import enrichment_v1
import m4_active_learning

DEMO_SHOP_ID = "shop_live_demo"


def _profile_score(p):
    fields = ["styles", "placement", "budget", "timing", "short_notice", "artist_vibe", "travel", "project", "location"]
    known = sum(bool(p.get(k)) for k in fields)
    return round(25 + 70 * known / len(fields))


def _signed_in_shop(request: Request):
    user = core.get_current_user(request)
    if not user:
        return None
    try:
        return str(user["shop_id"])
    except Exception:
        return None


def _resolve_shop(request: Request, requested_shop: str = "") -> str:
    signed_in = _signed_in_shop(request)
    if signed_in:
        return signed_in
    explicit = (requested_shop or "").strip().replace('"', "")
    return explicit or DEMO_SHOP_ID


@core.app.post("/api/m4/active-learning/next")
async def m4_active_learning_next(request: Request):
    """Return the single missing zero-party answer with highest M4 value."""
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    profile = payload.get("profile") if isinstance(payload, dict) else {}
    if not isinstance(profile, dict):
        return JSONResponse({"error": "profile must be an object"}, status_code=400)
    question = m4_active_learning.next_best_question(profile)
    ranked = m4_active_learning.rank_missing_questions(profile)
    return JSONResponse({
        "ok": True,
        "strategy": "m4_v1_information_value",
        "question": question,
        "remaining": len(ranked),
        "ranked_missing": ranked,
    }, headers={"Cache-Control": "no-store"})


@core.app.post("/api/concierge/profile")
def concierge_profile(
    request: Request,
    shop_id: str = Form(""),
    session_id: str = Form(""),
    name: str = Form(...),
    email: str = Form(""),
    phone: str = Form(...),
    contact_preference: str = Form(""),
    offer_consent: str = Form(...),
    project: str = Form(""),
    styles: str = Form(""),
    placement: str = Form(""),
    budget: str = Form(""),
    timing: str = Form(""),
    short_notice: str = Form(""),
    artist_vibe: str = Form(""),
    travel: str = Form(""),
    location: str = Form(""),
):
    sid = session_id.strip() or f"conc_{uuid.uuid4().hex[:12]}"
    target_shop = _resolve_shop(request, shop_id)
    conn = core.connect()
    try:
        if not core.db_fetchone(conn, "SELECT id FROM shops WHERE id=?", (target_shop,)):
            return JSONResponse({"error": "This Concierge link is not attached to a valid shop."}, status_code=400)
    finally:
        conn.close()

    p = {
        "session_id": sid,
        "name": name.strip(),
        "email": email.strip(),
        "phone": phone.strip(),
        "contact_preference": contact_preference.strip(),
        "offer_opt_in": offer_consent == "yes",
        "project": project.strip(),
        "styles": styles.strip(),
        "placement": placement.strip(),
        "budget": budget.strip(),
        "timing": timing.strip(),
        "short_notice": short_notice.strip(),
        "artist_vibe": artist_vibe.strip(),
        "travel": travel.strip(),
        "location": location.strip(),
    }
    if not p["name"] or not p["phone"]:
        return JSONResponse({"error": "Name and phone are required to create your profile."}, status_code=400)

    before = 31
    after = _profile_score(p)
    try:
        customer_id, lead_id = concierge_leads.save_concierge_profile(target_shop, p, after)
        demand_core.capture_concierge_profile(target_shop, customer_id, p)
        demand_core.sync_concierge_profile(target_shop, customer_id, p)
        contextual = None
        if p["location"]:
            try:
                contextual = enrichment_v1.enrich_customer(target_shop, customer_id, p["location"], source="concierge_zero_party")
            except Exception as exc:
                core.event("enrichment.customer_failed", "customer", customer_id, str(exc))
        verify = core.connect()
        try:
            customer = core.db_fetchone(verify, "SELECT id FROM customers WHERE id=? AND shop_id=?", (customer_id, target_shop))
            lead = core.db_fetchone(verify, "SELECT id FROM concierge_leads WHERE id=? AND shop_id=?", (lead_id, target_shop))
        finally:
            verify.close()
        if not customer or not lead:
            return JSONResponse({"error": "Profile save could not be verified."}, status_code=500)
    except Exception as exc:
        return JSONResponse({"error": f"Could not save customer profile: {exc}"}, status_code=500)

    try:
        concierge_pilot.send_new_lead_email(target_shop, p, after, customer_id)
    except Exception as exc:
        core.event("concierge.lead_email_failed", "customer", customer_id, str(exc))

    return JSONResponse({
        "ok": True,
        "shop_id": target_shop,
        "session_id": sid,
        "customer_id": customer_id,
        "lead_id": lead_id,
        "profile_created": True,
        "verified_customer": True,
        "verified_lead": True,
        "communication_consent": p["offer_opt_in"],
        "m4_confidence_before": before,
        "m4_confidence_after": after,
        "contextual_enrichment": contextual or {},
        "value": {
            "name": p["name"],
            "readiness": "ready to match" if after >= 70 else "developing",
            "short_notice": p.get("short_notice") or "not specified",
            "budget": p.get("budget") or "not specified",
            "style": p.get("styles") or "open",
            "location": p.get("location") or "not specified",
            "contact_preference": p.get("contact_preference") or "not specified",
        },
    }, headers={"Cache-Control": "no-store"})


@core.app.get("/concierge", response_class=HTMLResponse)
def concierge_page(request: Request):
    shop_id = _resolve_shop(request, request.query_params.get("shop_id") or "")
    try:
        with open("templates/concierge_chat.html", "r", encoding="utf-8") as handle:
            html = handle.read()
        html = html.replace("{{ url_for('static', path='/concierge-chat.css') }}", "/static/concierge-chat.css")
        html = html.replace("{{ url_for('static', path='/concierge-chat.js') }}", "/static/concierge-chat.js")
        html = html.replace("{{ shop_id|tojson }}", json.dumps(shop_id))
        return HTMLResponse(html, headers={"Cache-Control": "no-store"})
    except Exception as exc:
        return HTMLResponse(
            "<!doctype html><html><body style='background:#080908;color:#f0eadf;font-family:system-ui;padding:40px'><h1>Empty Chair Concierge</h1><p>Concierge could not load.</p><pre>" + str(exc) + "</pre></body></html>",
            status_code=503,
            headers={"Cache-Control": "no-store"},
        )


demand_engine.register_demand_engine(
    app=core.app,
    templates=core.templates,
    connect=core.connect,
    db_execute=core.db_execute,
    db_fetchone=core.db_fetchone,
    db_fetchall=core.db_fetchall,
    login_required_redirect=core.login_required_redirect,
    now_iso=core.now_iso,
)

import m4_operator_runtime_fix  # noqa: F401,E402
import m4_flywheel_demo  # noqa: F401,E402
import m4_flywheel_refine  # noqa: F401,E402
import concierge_site_demo  # noqa: F401,E402
import pilot_leads_dashboard  # noqa: F401,E402
import pilot_leads_live  # noqa: F401,E402
import m4_brand_runtime  # noqa: F401,E402
import m4_operator_v2  # noqa: F401,E402
import m4_operator_v3  # noqa: F401,E402
