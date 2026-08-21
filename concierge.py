"""Empty Chair Concierge: customer-side zero-party intelligence experience."""
import json
import uuid

from fastapi import Form, Request
from fastapi.responses import HTMLResponse, JSONResponse

import app as core
import concierge_leads

DEMO_SHOP_ID = "shop_live_demo"


def _profile_score(p):
    fields = ["styles", "placement", "budget", "timing", "short_notice", "artist_vibe", "travel", "project"]
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
    }
    if not p["name"] or not p["phone"]:
        return JSONResponse({"error": "Name and phone are required to create your profile."}, status_code=400)

    before = 31
    after = _profile_score(p)
    try:
        customer_id, lead_id = concierge_leads.save_concierge_profile(target_shop, p, after)
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
        "value": {
            "name": p["name"],
            "readiness": "ready to match" if after >= 70 else "developing",
            "short_notice": p.get("short_notice") or "not specified",
            "budget": p.get("budget") or "not specified",
            "style": p.get("styles") or "open",
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


# Runtime hardening and the cinematic flywheel demo are loaded after the base routes.
import m4_operator_runtime_fix  # noqa: F401,E402
import m4_flywheel_demo  # noqa: F401,E402
