"""Instagram organic entry path for launch before Meta app publication.

Every /ig visit gets its own first-party attribution token, then flows through the
existing signup/session attribution machinery. No Instagram webhook is required.
"""
from __future__ import annotations

import secrets
import uuid

import v2_app as core
import v2_instagram_growth as growth
from fastapi.responses import RedirectResponse


@core.app.get("/ig")
def instagram_organic_entry():
    lead_id = str(uuid.uuid4())
    token = secrets.token_urlsafe(18)
    comment_id = f"organic:{uuid.uuid4()}"
    created = growth.now()
    core.run(
        "INSERT INTO growth_instagram_leads(id,ig_user_id,username,comment_id,media_id,keyword,token,status,created_at,clicked_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
        (lead_id, "organic", "", comment_id, "", "bio", token, "CLICKED", created, created),
    )
    growth.log(lead_id, "instagram.organic_clicked", {"source": "bio"})
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
