"""Instagram Professional account connection foundation for Empty Chair.

Phase 1 only: account connection, token/account storage, and disconnect.
Automatic publishing is intentionally not enabled here.
"""

import os
import secrets
import urllib.parse
import urllib.request
import json
from datetime import datetime, timezone

from fastapi import HTTPException, Request
from fastapi.responses import RedirectResponse

import app as core

app = core.app

INSTAGRAM_APP_ID = os.getenv("INSTAGRAM_APP_ID", "")
INSTAGRAM_APP_SECRET = os.getenv("INSTAGRAM_APP_SECRET", "")
INSTAGRAM_REDIRECT_URI = os.getenv(
    "INSTAGRAM_REDIRECT_URI",
    f"{core.PUBLIC_BASE_URL.rstrip('/')}/integrations/instagram/callback",
)
INSTAGRAM_API_VERSION = os.getenv("INSTAGRAM_API_VERSION", "v23.0")
INSTAGRAM_SCOPE = "instagram_business_basic,instagram_business_content_publish"


def _columns(conn, table):
    if core.USE_POSTGRES:
        rows = core.db_fetchall(
            conn,
            "SELECT column_name FROM information_schema.columns WHERE table_name=?",
            (table,),
        )
        return {row["column_name"] for row in rows}
    return {row["name"] for row in core.db_fetchall(conn, f"PRAGMA table_info({table})")}


def ensure_schema():
    conn = core.connect()
    try:
        artist_columns = _columns(conn, "artists")
        additions = [
            ("instagram_user_id", "TEXT"),
            ("instagram_username", "TEXT"),
            ("instagram_access_token", "TEXT"),
            ("instagram_connected_at", "TEXT"),
            ("instagram_connection_active", "INTEGER NOT NULL DEFAULT 0"),
        ]
        for name, ddl in additions:
            if artist_columns and name not in artist_columns:
                core.db_execute(conn, f"ALTER TABLE artists ADD COLUMN {name} {ddl}")
        conn.commit()
    finally:
        conn.close()


def configured():
    return bool(INSTAGRAM_APP_ID and INSTAGRAM_APP_SECRET and INSTAGRAM_REDIRECT_URI)


def _graph_get(path, access_token, params=None):
    query = dict(params or {})
    query["access_token"] = access_token
    url = f"https://graph.instagram.com/{path.lstrip('/')}?{urllib.parse.urlencode(query)}"
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=20) as response:
            return json.loads(response.read().decode())
    except Exception as exc:
        raise RuntimeError(f"Instagram API request failed: {exc}") from exc


def _post_form(url, fields):
    req = urllib.request.Request(
        url,
        data=urllib.parse.urlencode(fields).encode(),
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as response:
            return json.loads(response.read().decode())
    except Exception as exc:
        raise RuntimeError(f"Instagram token exchange failed: {exc}") from exc


def _artist_for_shop(conn, artist_id, shop_id):
    return core.db_fetchone(
        conn,
        "SELECT * FROM artists WHERE id=? AND shop_id=? LIMIT 1",
        (artist_id, shop_id),
    )


@app.get("/integrations/instagram/connect/{artist_id}")
def connect_instagram(request: Request, artist_id: str):
    user, redirect = core.login_required_redirect(request)
    if redirect:
        return redirect
    if not configured():
        raise HTTPException(503, "Instagram integration is not configured yet")

    conn = core.connect()
    try:
        artist = _artist_for_shop(conn, artist_id, user["shop_id"])
    finally:
        conn.close()
    if not artist:
        raise HTTPException(404, "Artist not found")

    state = secrets.token_urlsafe(24)
    request.session["instagram_oauth_state"] = state
    request.session["instagram_artist_id"] = artist_id

    params = {
        "client_id": INSTAGRAM_APP_ID,
        "redirect_uri": INSTAGRAM_REDIRECT_URI,
        "response_type": "code",
        "scope": INSTAGRAM_SCOPE,
        "state": state,
        "enable_fb_login": "0",
        "force_authentication": "1",
    }
    auth_url = "https://www.instagram.com/oauth/authorize?" + urllib.parse.urlencode(params)
    return RedirectResponse(auth_url, status_code=303)


@app.get("/integrations/instagram/callback")
def instagram_callback(request: Request, code: str = "", state: str = "", error: str = ""):
    user, redirect = core.login_required_redirect(request)
    if redirect:
        return redirect

    expected_state = request.session.get("instagram_oauth_state")
    artist_id = request.session.get("instagram_artist_id")
    if error:
        return RedirectResponse("/settings?instagram=cancelled", status_code=303)
    if not code or not state or state != expected_state or not artist_id:
        raise HTTPException(400, "Invalid Instagram authorization response")

    conn = core.connect()
    try:
        artist = _artist_for_shop(conn, artist_id, user["shop_id"])
    finally:
        conn.close()
    if not artist:
        raise HTTPException(404, "Artist not found")

    token_data = _post_form(
        "https://api.instagram.com/oauth/access_token",
        {
            "client_id": INSTAGRAM_APP_ID,
            "client_secret": INSTAGRAM_APP_SECRET,
            "grant_type": "authorization_code",
            "redirect_uri": INSTAGRAM_REDIRECT_URI,
            "code": code,
        },
    )
    short_token = token_data.get("access_token")
    if not short_token:
        raise HTTPException(502, "Instagram did not return an access token")

    exchange = _graph_get(
        "access_token",
        short_token,
        {
            "grant_type": "ig_exchange_token",
            "client_secret": INSTAGRAM_APP_SECRET,
        },
    )
    long_token = exchange.get("access_token") or short_token
    profile = _graph_get("me", long_token, {"fields": "user_id,username"})
    instagram_user_id = str(profile.get("user_id") or profile.get("id") or "")
    username = profile.get("username") or ""
    if not instagram_user_id:
        raise HTTPException(502, "Instagram account identity could not be resolved")

    conn = core.connect()
    try:
        core.db_execute(
            conn,
            """
            UPDATE artists
            SET instagram_user_id=?,instagram_username=?,instagram_access_token=?,
                instagram_connected_at=?,instagram_connection_active=1
            WHERE id=? AND shop_id=?
            """,
            (
                instagram_user_id,
                username,
                long_token,
                datetime.now(timezone.utc).isoformat(),
                artist_id,
                user["shop_id"],
            ),
        )
        conn.commit()
    finally:
        conn.close()

    request.session.pop("instagram_oauth_state", None)
    request.session.pop("instagram_artist_id", None)
    core.event("instagram.connected", "artist", artist_id, username)
    return RedirectResponse("/settings?instagram=connected", status_code=303)


@app.post("/integrations/instagram/disconnect/{artist_id}")
def disconnect_instagram(request: Request, artist_id: str):
    user, redirect = core.login_required_redirect(request)
    if redirect:
        return redirect

    conn = core.connect()
    try:
        artist = _artist_for_shop(conn, artist_id, user["shop_id"])
        if not artist:
            raise HTTPException(404, "Artist not found")
        core.db_execute(
            conn,
            """
            UPDATE artists
            SET instagram_user_id=NULL,instagram_username=NULL,instagram_access_token=NULL,
                instagram_connected_at=NULL,instagram_connection_active=0
            WHERE id=? AND shop_id=?
            """,
            (artist_id, user["shop_id"]),
        )
        conn.commit()
    finally:
        conn.close()

    core.event("instagram.disconnected", "artist", artist_id)
    return RedirectResponse("/settings?instagram=disconnected", status_code=303)


ensure_schema()
