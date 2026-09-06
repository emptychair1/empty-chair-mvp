"""Complete first-party Instagram growth attribution without changing signup UX."""
from __future__ import annotations

import v2_app as core

_ORIGINAL_SET_SESSION = core.set_session


def set_session_with_growth(response, artist_id: str):
    _ORIGINAL_SET_SESSION(response, artist_id)
    # ec_growth is set by /ig/{token}. Bind it through a short-lived signed handoff
    # cookie consumed on the first authenticated request.
    token = getattr(response, "_ec_growth_token", None)
    if token:
        _bind(token, artist_id)


def _bind(token: str, artist_id: str):
    try:
        lead = core.one("SELECT id FROM growth_instagram_leads WHERE token=?", (token,))
        if not lead:
            return
        core.run("UPDATE growth_instagram_leads SET artist_id=?,trial_at=COALESCE(trial_at,?),status='TRIAL' WHERE id=?",
                 (artist_id, core.utcnow(), lead["id"]))
    except Exception as exc:
        print(f"IG attribution bind failed: {exc}", flush=True)


@core.app.middleware("http")
async def instagram_growth_attribution(request, call_next):
    response = await call_next(request)
    token = request.cookies.get("ec_growth")
    if not token:
        return response
    try:
        aid = core.unsign(request.cookies.get("ec2"))
        if aid:
            _bind(token, aid)
            response.delete_cookie("ec_growth")
    except Exception as exc:
        print(f"IG attribution middleware failed: {exc}", flush=True)
    return response
