"""Google authentication + optional Calendar safety layer for Empty Chair."""
import json
import os
import secrets
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import app as core
from fastapi import Request
from fastapi.responses import RedirectResponse

GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET", "")
GOOGLE_REDIRECT_URI = os.getenv("GOOGLE_REDIRECT_URI", f"{core.PUBLIC_BASE_URL.rstrip('/')}/auth/google/callback")
GOOGLE_CALENDAR_REDIRECT_URI = os.getenv("GOOGLE_CALENDAR_REDIRECT_URI", f"{core.PUBLIC_BASE_URL.rstrip('/')}/integrations/google-calendar/callback")
AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
USERINFO_URL = "https://openidconnect.googleapis.com/v1/userinfo"
FREEBUSY_URL = "https://www.googleapis.com/calendar/v3/freeBusy"
EVENTS_URL = "https://www.googleapis.com/calendar/v3/calendars/primary/events"


def _post_form(url, payload):
    req = urllib.request.Request(url, data=urllib.parse.urlencode(payload).encode(), headers={"Content-Type": "application/x-www-form-urlencoded"})
    with urllib.request.urlopen(req, timeout=15) as response:
        return json.loads(response.read().decode())


def _json_request(url, token, payload=None):
    data = None if payload is None else json.dumps(payload).encode()
    req = urllib.request.Request(url, data=data, headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=15) as response:
        return json.loads(response.read().decode())


def _oauth_url(request, redirect_uri, scopes, purpose):
    state = secrets.token_urlsafe(24)
    request.session[f"google_{purpose}_state"] = state
    return AUTH_URL + "?" + urllib.parse.urlencode({"client_id": GOOGLE_CLIENT_ID, "redirect_uri": redirect_uri, "response_type": "code", "scope": " ".join(scopes), "state": state, "access_type": "offline", "prompt": "select_account consent", "include_granted_scopes": "true"})


def _ensure_schema():
    conn = core.connect()
    try:
        core.db_execute(conn, """CREATE TABLE IF NOT EXISTS google_calendar_connections (user_id TEXT PRIMARY KEY, access_token TEXT, refresh_token TEXT, expires_at TEXT, calendar_id TEXT NOT NULL DEFAULT 'primary', connected_at TEXT NOT NULL, FOREIGN KEY(user_id) REFERENCES users(id))""")
        core.db_execute(conn, """CREATE TABLE IF NOT EXISTS artist_calendar_connections (artist_id TEXT PRIMARY KEY, user_id TEXT NOT NULL, connected_at TEXT NOT NULL, FOREIGN KEY(artist_id) REFERENCES artists(id), FOREIGN KEY(user_id) REFERENCES users(id))""")
        conn.commit()
    finally:
        conn.close()


def _save_connection(user_id, token):
    expires_at = (datetime.now(timezone.utc) + timedelta(seconds=max(60, int(token.get("expires_in", 3600)) - 60))).isoformat()
    conn = core.connect()
    try:
        existing = core.db_fetchone(conn, "SELECT refresh_token FROM google_calendar_connections WHERE user_id = ?", (user_id,))
        refresh = token.get("refresh_token") or (existing["refresh_token"] if existing else None)
        core.db_execute(conn, "DELETE FROM google_calendar_connections WHERE user_id = ?", (user_id,))
        core.db_execute(conn, "INSERT INTO google_calendar_connections(user_id, access_token, refresh_token, expires_at, calendar_id, connected_at) VALUES (?, ?, ?, ?, 'primary', ?)", (user_id, token["access_token"], refresh, expires_at, core.now_iso()))
        conn.commit()
    finally:
        conn.close()


def _access_token(user_id):
    conn = core.connect()
    try:
        row = core.db_fetchone(conn, "SELECT * FROM google_calendar_connections WHERE user_id = ?", (user_id,))
    finally:
        conn.close()
    if not row:
        return None
    expires = core.parse_datetime(row["expires_at"])
    if expires and expires > datetime.now(timezone.utc) + timedelta(seconds=30):
        return row["access_token"]
    if not row["refresh_token"]:
        return None
    token = _post_form(TOKEN_URL, {"client_id": GOOGLE_CLIENT_ID, "client_secret": GOOGLE_CLIENT_SECRET, "refresh_token": row["refresh_token"], "grant_type": "refresh_token"})
    token["refresh_token"] = row["refresh_token"]
    _save_connection(user_id, token)
    return token["access_token"]


def calendar_connected(user_id):
    conn = core.connect()
    try:
        return bool(core.db_fetchone(conn, "SELECT user_id FROM google_calendar_connections WHERE user_id = ?", (user_id,)))
    finally:
        conn.close()

def calendar_user_for_artist(artist_id):
    conn = core.connect()
    try:
        row = core.db_fetchone(conn, "SELECT user_id FROM artist_calendar_connections WHERE artist_id = ?", (artist_id,))
        return row["user_id"] if row else None
    finally: conn.close()

def artist_calendar_connected(artist_id):
    user_id = calendar_user_for_artist(artist_id)
    return bool(user_id and calendar_connected(user_id))


def slot_iso(date_value, time_value, timezone_name):
    zone = ZoneInfo(timezone_name or "America/New_York")
    local = datetime.fromisoformat(f"{date_value}T{time_value}").replace(tzinfo=zone)
    return local.isoformat()


@core.app.get("/auth/google")
def google_login(request: Request):
    if not GOOGLE_CLIENT_ID or not GOOGLE_CLIENT_SECRET:
        return RedirectResponse("/login?google=not_configured", status_code=303)
    return RedirectResponse(_oauth_url(request, GOOGLE_REDIRECT_URI, ["openid", "email", "profile"], "login"), status_code=303)


@core.app.get("/auth/google/callback")
def google_login_callback(request: Request, code: str = "", state: str = ""):
    expected = request.session.pop("google_login_state", None)
    if not code or not expected or not secrets.compare_digest(state, expected):
        return RedirectResponse("/login?google=invalid_state", status_code=303)
    token = _post_form(TOKEN_URL, {"code": code, "client_id": GOOGLE_CLIENT_ID, "client_secret": GOOGLE_CLIENT_SECRET, "redirect_uri": GOOGLE_REDIRECT_URI, "grant_type": "authorization_code"})
    profile = _json_request(USERINFO_URL, token["access_token"])
    email = core.normalize_email(profile.get("email"))
    conn = core.connect()
    user = core.db_fetchone(conn, "SELECT * FROM users WHERE email = ? AND is_active = 1 LIMIT 1", (email,))
    conn.close()
    if not user:
        return RedirectResponse("/login?google=no_account", status_code=303)
    request.session.clear(); request.session["user_id"] = user["id"]
    core.event("user.google_logged_in", "user", user["id"])
    return RedirectResponse("/", status_code=303)


@core.app.get("/integrations/google-calendar/connect")
def connect_google_calendar(request: Request, artist_id: str = ""):
    user, redirect = core.login_required_redirect(request)
    if redirect: return redirect
    if not GOOGLE_CLIENT_ID or not GOOGLE_CLIENT_SECRET:
        return RedirectResponse("/settings?calendar=not_configured", status_code=303)
    if artist_id:
        conn = core.connect()
        try: artist = core.db_fetchone(conn, "SELECT id FROM artists WHERE id = ? AND shop_id = ?", (artist_id, user["shop_id"]))
        finally: conn.close()
        if not artist: return RedirectResponse("/artists?calendar=invalid_artist", status_code=303)
        request.session["google_calendar_artist_id"] = artist_id
    return RedirectResponse(_oauth_url(request, GOOGLE_CALENDAR_REDIRECT_URI, ["openid", "email", "https://www.googleapis.com/auth/calendar"], "calendar"), status_code=303)


@core.app.get("/integrations/google-calendar/callback")
def google_calendar_callback(request: Request, code: str = "", state: str = ""):
    user, redirect = core.login_required_redirect(request)
    if redirect: return redirect
    expected = request.session.pop("google_calendar_state", None)
    if not code or not expected or not secrets.compare_digest(state, expected):
        return RedirectResponse("/settings?calendar=invalid_state", status_code=303)
    token = _post_form(TOKEN_URL, {"code": code, "client_id": GOOGLE_CLIENT_ID, "client_secret": GOOGLE_CLIENT_SECRET, "redirect_uri": GOOGLE_CALENDAR_REDIRECT_URI, "grant_type": "authorization_code"})
    _save_connection(user["id"], token)
    artist_id = request.session.pop("google_calendar_artist_id", None)
    if artist_id:
        conn = core.connect()
        try:
            artist = core.db_fetchone(conn, "SELECT id FROM artists WHERE id = ? AND shop_id = ?", (artist_id, user["shop_id"]))
            if artist:
                core.db_execute(conn, "DELETE FROM artist_calendar_connections WHERE artist_id = ?", (artist_id,))
                core.db_execute(conn, "INSERT INTO artist_calendar_connections(artist_id, user_id, connected_at) VALUES (?, ?, ?)", (artist_id, user["id"], core.now_iso()))
                conn.commit()
        finally: conn.close()
    core.event("calendar.connected", "user", user["id"])
    return RedirectResponse("/artists?calendar=connected" if artist_id else "/settings?calendar=connected", status_code=303)


@core.app.post("/integrations/google-calendar/disconnect")
def disconnect_google_calendar(request: Request):
    user, redirect = core.login_required_redirect(request)
    if redirect: return redirect
    conn = core.connect()
    try:
        core.db_execute(conn, "DELETE FROM google_calendar_connections WHERE user_id = ?", (user["id"],)); conn.commit()
    finally: conn.close()
    core.event("calendar.disconnected", "user", user["id"])
    return RedirectResponse("/settings?calendar=disconnected", status_code=303)


def calendar_is_available_for_user(user_id, start_iso, end_iso):
    token = _access_token(user_id)
    if not token: return None
    result = _json_request(FREEBUSY_URL, token, {"timeMin": start_iso, "timeMax": end_iso, "items": [{"id": "primary"}]})
    return not result.get("calendars", {}).get("primary", {}).get("busy", [])


def block_calendar_time_for_user(user_id, summary, start_iso, end_iso, timezone_name):
    token = _access_token(user_id)
    if not token: return None
    return _json_request(EVENTS_URL, token, {"summary": summary, "description": "Booked by Empty Chair", "start": {"dateTime": start_iso, "timeZone": timezone_name}, "end": {"dateTime": end_iso, "timeZone": timezone_name}})


def calendar_is_available(request, start_iso, end_iso):
    user = core.get_current_user(request)
    return calendar_is_available_for_user(user["id"], start_iso, end_iso) if user else None


def block_calendar_time(request, summary, start_iso, end_iso, timezone_name):
    user = core.get_current_user(request)
    return block_calendar_time_for_user(user["id"], summary, start_iso, end_iso, timezone_name) if user else None


_ensure_schema()

@core.app.on_event("startup")
def ensure_google_schema_on_startup():
    _ensure_schema()
