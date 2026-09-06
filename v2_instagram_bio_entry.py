"""Final-route Instagram bio entry for the pre-review organic launch loop.

Imported last by bootstrap so the route is attached to the final FastAPI app after all
other production patches have loaded. No startup workers or external calls.
"""
from __future__ import annotations

import secrets
import uuid

import v2_app as core
from fastapi.responses import RedirectResponse


@core.app.get("/ig")
def instagram_bio_entry():
    lead_id = str(uuid.uuid4())
    token = secrets.token_urlsafe(18)
    created = core.utcnow()
    comment_id = f"organic:{uuid.uuid4()}"

    core.run(
        "INSERT INTO growth_instagram_leads(id,ig_user_id,username,comment_id,media_id,keyword,token,status,created_at,clicked_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
        (lead_id, "organic", "", comment_id, "", "bio", token, "CLICKED", created, created),
    )
    try:
        core.run(
            "INSERT INTO growth_instagram_events(id,lead_id,kind,payload,created_at) VALUES(?,?,?,?,?)",
            (str(uuid.uuid4()), lead_id, "instagram.organic_clicked", '{"source":"bio"}', created),
        )
    except Exception:
        pass

    response = RedirectResponse("/signup", status_code=303)
    response.set_cookie(
        "ec_growth",
        token,
        max_age=60 * 60 * 24 * 14,
        httponly=True,
        secure=core.BASE_URL.startswith("https://"),
        samesite="lax",
    )
    return response
