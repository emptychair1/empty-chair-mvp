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


def _authorized_request(url, token, method="GET", payload=None):
    data = None if payload is None else json.dumps(payload).encode()
    req = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=15) as response:
        body = response.read().decode()
        return json.loads(body) if body else {}


def _oauth_url(request, redirect_uri, scopes, purpose):
    state = secrets.token_urlsafe(24)
    request.session[f"google_{purpose}_state"] = state
    return AUTH_URL + "?" + urllib.parse.urlencode({"client_id": GOOGLE_CLIENT_ID, "redirect_uri": redirect_uri, "response_type": "code", "scope": " ".join(scopes), "state": state, "access_type": "offline", "prompt": "select_account consent", "include_granted_scopes": "true"})


def _ensure_schema():
    conn = core.connect()
    try:
        core.db_execute(conn, """CREATE TABLE IF NOT EXISTS google_calendar_connections (user_id TEXT PRIMARY KEY, access_token TEXT, refresh_token TEXT, expires_at TEXT, calendar_id TEXT NOT NULL DEFAULT 'primary', connected_at TEXT NOT NULL, FOREIGN KEY(user_id) REFERENCES users(id))""")
        core.db_execute(conn, """CREATE TABLE IF NOT EXISTS artist_calendar_connections (artist_id TEXT PRIMARY KEY, user_id TEXT NOT NULL, connected_at TEXT NOT NULL, FOREIGN KEY(artist_id) REFERENCES artists(id), FOREIGN KEY(user_id) REFERENCES users(id))""")
        core.db_execute(conn, """CREATE TABLE IF NOT EXISTS google_booking_events (booking_id TEXT PRIMARY KEY, user_id TEXT NOT NULL, event_id TEXT NOT NULL, created_at TEXT NOT NULL, FOREIGN KEY(booking_id) REFERENCES bookings(id), FOREIGN KEY(user_id) REFERENCES users(id))""")
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


def remember_booking_event(booking_id, user_id, event_id):
    if not event_id:
        return
    conn = core.connect()
    try:
        core.db_execute(conn, "DELETE FROM google_booking_events WHERE booking_id = ?", (booking_id,))
        core.db_execute(
            conn,
            "INSERT INTO google_booking_events(booking_id,user_id,event_id,created_at) VALUES (?,?,?,?)",
            (booking_id, user_id, event_id, core.now_iso()),
        )
        conn.commit()
    finally:
        conn.close()


def booking_event(booking_id):
    conn = core.connect()
    try:
        return core.db_fetchone(conn, "SELECT * FROM google_booking_events WHERE booking_id = ?", (booking_id,))
    finally:
        conn.close()


def delete_booking_event(booking_id):
    mapping = booking_event(booking_id)
    if not mapping:
        return True
    token = _access_token(mapping["user_id"])
    if not token:
        return False
    url = f"{EVENTS_URL}/{urllib.parse.quote(mapping['event_id'], safe='')}"
    try:
        _authorized_request(url, token, method="DELETE")
    except urllib.error.HTTPError as exc:
        if exc.code != 404:
            raise
    conn = core.connect()
    try:
        core.db_execute(conn, "DELETE FROM google_booking_events WHERE booking_id = ?", (booking_id,))
        conn.commit()
    finally:
        conn.close()
    return True


def list_calendar_events_for_user(user_id, time_min, time_max):
    token = _access_token(user_id)
    if not token:
        return []
    events = []
    page_token = ""
    while True:
        query = {
            "timeMin": time_min,
            "timeMax": time_max,
            "singleEvents": "true",
            "orderBy": "startTime",
            "maxResults": "250",
        }
        if page_token:
            query["pageToken"] = page_token
        result = _authorized_request(EVENTS_URL + "?" + urllib.parse.urlencode(query), token)
        events.extend(item for item in result.get("items", []) if item.get("status") != "cancelled")
        page_token = result.get("nextPageToken", "")
        if not page_token:
            return events


def external_calendar_events_for_shop(shop_id, time_min, time_max):
    conn = core.connect()
    try:
        artists = core.db_fetchall(
            conn,
            """SELECT a.id,a.name,ac.user_id FROM artists a JOIN artist_calendar_connections ac ON ac.artist_id=a.id WHERE a.shop_id=? AND a.active=1""",
            (shop_id,),
        )
        managed = {
            row["event_id"]
            for row in core.db_fetchall(
                conn,
                """SELECT gbe.event_id FROM google_booking_events gbe JOIN bookings b ON b.id=gbe.booking_id JOIN openings o ON o.id=b.opening_id WHERE o.shop_id=?""",
                (shop_id,),
            )
        }
    finally:
        conn.close()
    external = []
    seen = set()
    for artist in artists:
        for event in list_calendar_events_for_user(artist["user_id"], time_min, time_max):
            event_id = event.get("id")
            if not event_id or event_id in managed or (artist["id"], event_id) in seen:
                continue
            seen.add((artist["id"], event_id))
            start = event.get("start", {}).get("dateTime")
            end = event.get("end", {}).get("dateTime")
            if not start or not end:
                continue
            external.append(
                {
                    "id": event_id,
                    "artist_id": artist["id"],
                    "artist_name": artist["name"],
                    "start": start,
                    "end": end,
                    "html_link": event.get("htmlLink", ""),
                }
            )
    return external


def reconcile_deleted_booking_events():
    conn = core.connect()
    try:
        rows = core.db_fetchall(
            conn,
            """SELECT gbe.booking_id,gbe.user_id,gbe.event_id,b.opening_id,b.status,o.date,o.start_time,o.end_time,s.timezone AS shop_timezone FROM google_booking_events gbe JOIN bookings b ON b.id=gbe.booking_id JOIN openings o ON o.id=b.opening_id JOIN shops s ON s.id=o.shop_id""",
        )
    finally:
        conn.close()
    reopened = []
    for row in rows:
        if row["status"] == "CANCELLED":
            try:
                delete_booking_event(row["booking_id"])
            except Exception as exc:
                core.event("calendar.delete_failed", "booking", row["booking_id"], str(exc))
            continue
        if row["status"] != "CONFIRMED":
            continue
        token = _access_token(row["user_id"])
        if not token:
            continue
        missing = False
        try:
            event = _authorized_request(f"{EVENTS_URL}/{urllib.parse.quote(row['event_id'], safe='')}", token)
            missing = event.get("status") == "cancelled"
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                missing = True
            else:
                core.event("calendar.reconcile_failed", "booking", row["booking_id"], str(exc))
                continue
        except Exception as exc:
            core.event("calendar.reconcile_failed", "booking", row["booking_id"], str(exc))
            continue
        if not missing:
            try:
                start_value = event.get("start", {}).get("dateTime")
                end_value = event.get("end", {}).get("dateTime")
                if start_value and end_value:
                    zone = ZoneInfo(row["shop_timezone"] or "America/New_York")
                    start = datetime.fromisoformat(start_value.replace("Z", "+00:00")).astimezone(zone)
                    end = datetime.fromisoformat(end_value.replace("Z", "+00:00")).astimezone(zone)
                    new_values = (start.date().isoformat(), start.strftime("%H:%M"), end.strftime("%H:%M"))
                    old_values = (str(row["date"]), str(row["start_time"])[:5], str(row["end_time"])[:5])
                    if new_values != old_values:
                        conn = core.connect()
                        try:
                            core.db_execute(conn, "UPDATE openings SET date=?,start_time=?,end_time=? WHERE id=?", (*new_values, row["opening_id"]))
                            conn.commit()
                        finally:
                            conn.close()
                        core.event("calendar.external_reschedule", "booking", row["booking_id"])
            except Exception as exc:
                core.event("calendar.reconcile_failed", "booking", row["booking_id"], str(exc))
            continue
        conn = core.connect()
        try:
            core.db_execute(conn, "UPDATE bookings SET status='CANCELLED',cancelled_at=? WHERE id=? AND status='CONFIRMED'", (core.now_iso(), row["booking_id"]))
            core.db_execute(conn, "UPDATE openings SET status='OPEN',booking_id=NULL WHERE id=?", (row["opening_id"],))
            core.db_execute(conn, "DELETE FROM google_booking_events WHERE booking_id=?", (row["booking_id"],))
            conn.commit()
        finally:
            conn.close()
        reopened.append(row["opening_id"])
        core.event("calendar.external_cancellation", "booking", row["booking_id"])
    for opening_id in reopened:
        try:
            core.start_recovery_campaign(opening_id)
        except Exception as exc:
            core.event("booking.reopen_failed", "opening", opening_id, str(exc))
    return len(reopened)


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
