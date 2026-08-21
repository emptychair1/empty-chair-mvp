"""Empty Chair Concierge: conversational customer-side zero-party intelligence."""
import uuid

from fastapi import Form, Request
from fastapi.responses import JSONResponse

import app as core
import concierge_leads

DEMO_SHOP_ID = "shop_live_demo"


def _profile_score(profile):
    fields = [
        "styles",
        "placement",
        "budget",
        "timing",
        "short_notice",
        "artist_vibe",
        "travel",
        "project",
    ]
    known = sum(bool(profile.get(key)) for key in fields)
    return round(25 + 70 * known / len(fields))


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
    target_shop = shop_id.strip() or DEMO_SHOP_ID
    profile = {
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
    if not profile["name"] or not profile["phone"]:
        return JSONResponse(
            {"error": "Name and phone are required to create your profile."},
            status_code=400,
        )

    before = 31
    after = _profile_score(profile)
    try:
        customer_id, lead_id = concierge_leads.save_concierge_profile(
            target_shop,
            profile,
            after,
        )
    except Exception as exc:
        return JSONResponse(
            {"error": f"Could not save customer profile: {exc}"},
            status_code=500,
        )

    signals = [
        {"label": key.replace("_", " ").title(), "value": value}
        for key, value in profile.items()
        if key not in {"session_id", "email", "phone", "offer_opt_in"} and value
    ]
    return JSONResponse(
        {
            "ok": True,
            "session_id": sid,
            "customer_id": customer_id,
            "lead_id": lead_id,
            "profile_created": True,
            "communication_consent": profile["offer_opt_in"],
            "signals": signals,
            "m4_confidence_before": before,
            "m4_confidence_after": after,
            "value": {
                "name": profile["name"],
                "readiness": "ready to match" if after >= 70 else "developing",
                "short_notice": profile.get("short_notice") or "not specified",
                "budget": profile.get("budget") or "not specified",
                "style": profile.get("styles") or "open",
                "contact_preference": profile.get("contact_preference") or "not specified",
            },
        },
        headers={"Cache-Control": "no-store"},
    )


@core.app.get("/concierge")
def concierge_page(request: Request):
    shop_id = (request.query_params.get("shop_id") or DEMO_SHOP_ID).strip()
    return core.templates.TemplateResponse(
        "concierge_public.html",
        {
            "request": request,
            "shop_id": shop_id,
        },
        headers={"Cache-Control": "no-store"},
    )
