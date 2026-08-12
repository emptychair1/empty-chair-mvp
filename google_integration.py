"""Google authentication + optional Calendar safety layer for Empty Chair."""
import json
import os
import secrets
import urllib.parse
import urllib.request
from datetime import datetime

import app as core
from fastapi import Request
from fastapi.responses import RedirectResponse

GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET", "")
GOOGLE_REDIRECT_URI = os.getenv(
    "GOOGLE_REDIRECT_URI",
    f"{core.PUBLIC_BASE_URL.rstrip('/')}/auth/google/callback",
)
GOOGLE_CALENDAR_REDIRECT_URI = os.getenv(
    "GOOGLE_CALENDAR_REDIRECT_URI",
    f"{core.PUBLIC_BASE_URL.rstrip('/')}/integrations/google-calendar/callback",
)

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
USERINFO_URL = "https://openidconnect.googleapis.com/v1/userinfo"
FREEBUSY_URL = "https://www.googleapis.com/calendar/v3/freeBusy"
EVENTS_URL = "https://www.googleapis.com/calendar/v3/calendars/primary/events"


def _post_form(url, payload):
    req = urllib.request.Request(
        url,
        data=urllib.parse.urlencode(payload).encode(),
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    with urllib.request.urlopen(req, timeout=15) as response:
        return json.loads(response.read().decode())


def _json_request(url, token, payload=None):
    data = None if payload is None else json.dumps(payload).encode()
    req = urllib.request.Request(
        url,
        data=data,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=15) as response:
        return json.loads(response.read().decode())


def _oauth_url(request, redirect_uri, scopes, purpose):
    state = secrets.token_urlsafe(24)
    request.session[f"google_{purpose}_state"] = state
    params = {
        "client_id": GOOGLE_CLIENT_ID,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": " ".join(scopes),
        "state": state,
        "access_type": "offline",
        "prompt": "select_account consent",
    }
    return AUTH_URL + "?" + urllib.parse.urlencode(params)


@core.app.get("/auth/google")
def google_login(request: Request):
    if not GOOGLE_CLIENT_ID or not GOOGLE_CLIENT_SECRET:
        return RedirectResponse("/login?google=not_configured", status_code=303)
    return RedirectResponse(
        _oauth_url(
            request,
            GOOGLE_REDIRECT_URI,
            ["openid", "email", "profile"],
            "login",
        ),
        status_code=303,
    )


@core.app.get("/auth/google/callback")
def google_login_callback(request: Request, code: str = "", state: str = ""):
    expected = request.session.pop("google_login_state", None)
    if not code or not expected or not secrets.compare_digest(state, expected):
        return RedirectResponse("/login?google=invalid_state", status_code=303)
    token = _post_form(TOKEN_URL, {
        "code": code,
        "client_id": GOOGLE_CLIENT_ID,
        "client_secret": GOOGLE_CLIENT_SECRET,
        "redirect_uri": GOOGLE_REDIRECT_URI,
        "grant_type": "authorization_code",
    })
    profile = _json_request(USERINFO_URL, token["access_token"])
    email = core.normalize_email(profile.get("email"))
    conn = core.connect()
    user = core.db_fetchone(conn, "SELECT * FROM users WHERE email = ? AND is_active = 1 LIMIT 1", (email,))
    conn.close()
    if not user:
        return RedirectResponse("/login?google=no_account", status_code=303)
    request.session.clear()
    request.session["user_id"] = user["id"]
    core.event("user.google_logged_in", "user", user["id"])
    return RedirectResponse("/", status_code=303)


@core.app.get("/integrations/google-calendar/connect")
def connect_google_calendar(request: Request):
    user, redirect = core.login_required_redirect(request)
    if redirect:
        return redirect
    if not GOOGLE_CLIENT_ID or not GOOGLE_CLIENT_SECRET:
        return RedirectResponse("/settings?calendar=not_configured", status_code=303)
    return RedirectResponse(
        _oauth_url(
            request,
            GOOGLE_CALENDAR_REDIRECT_URI,
            ["openid", "email", "https://www.googleapis.com/auth/calendar"],
            "calendar",
        ),
        status_code=303,
    )


@core.app.get("/integrations/google-calendar/callback")
def google_calendar_callback(request: Request, code: str = "", state: str = ""):
    user, redirect = core.login_required_redirect(request)
    if redirect:
        return redirect
    expected = request.session.pop("google_calendar_state", None)
    if not code or not expected or not secrets.compare_digest(state, expected):
        return RedirectResponse("/settings?calendar=invalid_state", status_code=303)
    token = _post_form(TOKEN_URL, {
        "code": code,
        "client_id": GOOGLE_CLIENT_ID,
        "client_secret": GOOGLE_CLIENT_SECRET,
        "redirect_uri": GOOGLE_CALENDAR_REDIRECT_URI,
        "grant_type": "authorization_code",
    })
    request.session["google_calendar_access_token"] = token["access_token"]
    if token.get("refresh_token"):
        request.session["google_calendar_refresh_token"] = token["refresh_token"]
    request.session["google_calendar_connected"] = True
    return RedirectResponse("/settings?calendar=connected", status_code=303)


def calendar_is_available(request: Request, start_iso: str, end_iso: str):
    """Return True/False when connected, None when manual availability should be trusted."""
    token = request.session.get("google_calendar_access_token")
    if not token:
        return None
    result = _json_request(FREEBUSY_URL, token, {
        "timeMin": start_iso,
        "timeMax": end_iso,
        "items": [{"id": "primary"}],
    })
    return not result.get("calendars", {}).get("primary", {}).get("busy", [])


def block_calendar_time(request: Request, summary: str, start_iso: str, end_iso: str, timezone_name: str):
    token = request.session.get("google_calendar_access_token")
    if not token:
        return None
    return _json_request(EVENTS_URL, token, {
        "summary": summary,
        "description": "Booked by Empty Chair",
        "start": {"dateTime": start_iso, "timeZone": timezone_name},
        "end": {"dateTime": end_iso, "timeZone": timezone_name},
    })
