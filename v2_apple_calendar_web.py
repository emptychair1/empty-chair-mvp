"""Graceful web-only Apple Calendar connection for Empty Chair 2.0.

Apple's generic CalDAV access still requires an app-specific password. This module keeps
that one Apple handoff inside a short guided Empty Chair flow: open Apple Account, create
a one-time Empty Chair password, paste it once, then choose the tattoo calendar.

It also replaces the core Apple event reader with a more defensive iCloud CalDAV reader.
iCloud normally answers a calendar-query REPORT, but some calendars return an empty
calendar-data set even while event resources exist. In that case we enumerate calendar
resources and fetch them with calendar-multiget. This keeps cancellation detection reliable
without changing the shared Google/recovery worker.
"""
from __future__ import annotations

import base64
import html
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from fastapi import Form, Request
from fastapi.responses import RedirectResponse

import v2_app as core

APPLE_ACCOUNT_URL = "https://account.apple.com/"
CALDAV_NS = "urn:ietf:params:xml:ns:caldav"
DAV_NS = "DAV:"


def _drop_route(path: str, methods: set[str]):
    kept = []
    for route in core.app.router.routes:
        route_methods = set(getattr(route, "methods", set()) or set())
        if getattr(route, "path", None) == path and methods.issubset(route_methods):
            continue
        kept.append(route)
    core.app.router.routes[:] = kept


for _path, _methods in [
    ("/setup/apple", {"GET"}),
    ("/setup/apple", {"POST"}),
    ("/setup/apple/select", {"GET"}),
    ("/setup/apple/select", {"POST"}),
    ("/setup/apple/manual", {"POST"}),
]:
    _drop_route(_path, _methods)


def _apple_xml_request(
    url: str,
    username: str,
    password: str,
    body: str,
    *,
    method: str,
    depth: str | None = None,
) -> ET.Element:
    auth = base64.b64encode(f"{username}:{password}".encode()).decode()
    headers = {
        "Authorization": f"Basic {auth}",
        "Content-Type": "application/xml; charset=utf-8",
        "User-Agent": "EmptyChair/2.0",
    }
    if depth is not None:
        headers["Depth"] = depth
    req = urllib.request.Request(url, data=body.encode(), method=method, headers=headers)
    with urllib.request.urlopen(req, timeout=30) as resp:
        return ET.fromstring(resp.read())


def _unfold_ics(text: str) -> list[str]:
    raw = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    lines: list[str] = []
    for line in raw:
        if line.startswith((" ", "\t")) and lines:
            lines[-1] += line[1:]
        else:
            lines.append(line)
    return lines


def _parse_ical_datetime(prop: str, value: str) -> str | None:
    params: dict[str, str] = {}
    pieces = prop.split(";")
    for item in pieces[1:]:
        if "=" in item:
            key, val = item.split("=", 1)
            params[key.upper()] = val.strip('"')

    value = value.strip()
    try:
        if len(value) == 8 and value.isdigit():
            # All-day calendar entries are not tattoo appointment slots.
            return None
        if value.endswith("Z"):
            dt = datetime.strptime(value, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
        else:
            dt = datetime.strptime(value[:15], "%Y%m%dT%H%M%S")
            tzid = params.get("TZID")
            if tzid:
                try:
                    dt = dt.replace(tzinfo=ZoneInfo(tzid))
                except Exception:
                    dt = dt.replace(tzinfo=timezone.utc)
            else:
                dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).isoformat()
    except Exception:
        return None


def _parse_ics_events(text: str) -> list[dict]:
    events: list[dict] = []
    cur: dict | None = None
    for line in _unfold_ics(text):
        if line == "BEGIN:VEVENT":
            cur = {}
            continue
        if line == "END:VEVENT":
            if cur and cur.get("id") and cur.get("start") and cur.get("end"):
                cur.setdefault("title", "Tattoo appointment")
                cur.setdefault("status", "confirmed")
                events.append(cur)
            cur = None
            continue
        if cur is None or ":" not in line:
            continue

        prop, value = line.split(":", 1)
        key = prop.split(";", 1)[0].upper()
        if key == "UID":
            cur["id"] = value.strip()
        elif key == "SUMMARY":
            cur["title"] = (
                value.replace("\\n", " ")
                .replace("\\N", " ")
                .replace("\\,", ",")
                .replace("\\;", ";")
                .replace("\\\\", "\\")
            )
        elif key == "STATUS":
            cur["status"] = value.strip().lower()
        elif key in ("DTSTART", "DTEND"):
            parsed = _parse_ical_datetime(prop, value)
            if parsed:
                cur["start" if key == "DTSTART" else "end"] = parsed
    return events


def _calendar_data_events(root: ET.Element) -> list[dict]:
    out: list[dict] = []
    for node in root.findall(f".//{{{CALDAV_NS}}}calendar-data"):
        out.extend(_parse_ics_events(node.text or ""))
    return out


def _apple_multiget_events(acct: dict) -> list[dict]:
    url = acct.get("apple_calendar_url") or ""
    username = acct.get("apple_username") or ""
    password = acct.get("apple_password") or ""
    propfind = '''<?xml version="1.0" encoding="utf-8"?>
<d:propfind xmlns:d="DAV:"><d:prop><d:getcontenttype/><d:resourcetype/></d:prop></d:propfind>'''
    root = _apple_xml_request(url, username, password, propfind, method="PROPFIND", depth="1")

    hrefs: list[str] = []
    calendar_path = urllib.parse.urlparse(url).path.rstrip("/") + "/"
    for response in root.findall(f".//{{{DAV_NS}}}response"):
        href_el = response.find(f"{{{DAV_NS}}}href")
        if href_el is None or not href_el.text:
            continue
        href = href_el.text
        path = urllib.parse.urlparse(href).path
        if path.rstrip("/") + "/" == calendar_path:
            continue
        content_type = response.find(f".//{{{DAV_NS}}}getcontenttype")
        ctype = (content_type.text or "").lower() if content_type is not None else ""
        if path.lower().endswith(".ics") or "text/calendar" in ctype:
            hrefs.append(href)

    events: list[dict] = []
    for offset in range(0, min(len(hrefs), 2000), 100):
        batch = hrefs[offset : offset + 100]
        href_xml = "".join(f"<d:href>{html.escape(href)}</d:href>" for href in batch)
        body = f'''<?xml version="1.0" encoding="utf-8"?>
<c:calendar-multiget xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav">
  <d:prop><d:getetag/><c:calendar-data/></d:prop>
  {href_xml}
</c:calendar-multiget>'''
        multi = _apple_xml_request(url, username, password, body, method="REPORT", depth="1")
        events.extend(_calendar_data_events(multi))
    return events


def _apple_events_robust(acct: dict) -> list[dict]:
    url = acct.get("apple_calendar_url") or ""
    if not url:
        return []

    username = acct.get("apple_username") or ""
    password = acct.get("apple_password") or ""
    now = datetime.now(timezone.utc)
    low = now - timedelta(days=1)
    high = now + timedelta(days=60)
    start = low.strftime("%Y%m%dT%H%M%SZ")
    end = high.strftime("%Y%m%dT%H%M%SZ")
    body = f'''<?xml version="1.0" encoding="utf-8"?>
<c:calendar-query xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav">
  <d:prop><d:getetag/><c:calendar-data/></d:prop>
  <c:filter>
    <c:comp-filter name="VCALENDAR">
      <c:comp-filter name="VEVENT"><c:time-range start="{start}" end="{end}"/></c:comp-filter>
    </c:comp-filter>
  </c:filter>
</c:calendar-query>'''
    root = _apple_xml_request(url, username, password, body, method="REPORT", depth="1")
    events = _calendar_data_events(root)

    # Some iCloud calendars answer the filtered REPORT successfully but omit event
    # payloads. Enumerate resources and multiget as a compatibility fallback.
    if not events:
        events = _apple_multiget_events(acct)

    filtered: list[dict] = []
    seen: set[str] = set()
    for item in events:
        try:
            starts = datetime.fromisoformat(item["start"].replace("Z", "+00:00"))
        except Exception:
            continue
        if starts < low or starts > high:
            continue
        uid = item.get("id")
        if not uid or uid in seen:
            continue
        seen.add(uid)
        filtered.append(item)
    return filtered


# The worker in v2_app resolves this dynamically each polling cycle. Replace only the
# Apple reader; Google polling and the recovery engine remain untouched.
core.apple_events = _apple_events_robust


@core.app.get("/setup/apple")
def apple_setup(request: Request):
    artist = core.current_artist(request)
    if not artist:
        return RedirectResponse("/setup")

    existing = core.one("SELECT * FROM calendar_accounts WHERE artist_id=?", (artist["id"],))
    username = ""
    if existing and existing.get("provider") == "apple":
        username = existing.get("apple_username") or ""

    return core.page(
        "Apple Calendar",
        f'''<h1>CONNECT APPLE CALENDAR</h1>
<p>Apple requires a one-time calendar password. We'll take you directly there.</p>
<div class="space"></div>
<p class="dim">1 // CREATE THE PASSWORD WITH APPLE</p>
<a class="button" href="{APPLE_ACCOUNT_URL}" target="_blank" rel="noopener noreferrer">OPEN APPLE ACCOUNT</a>
<p class="dim">Sign-In & Security → App-Specific Passwords → generate one named <span class="bright">Empty Chair</span>.</p>
<div class="space"></div>
<p class="dim">2 // COME BACK HERE AND PASTE IT</p>
<form method="post" class="stack" autocomplete="off">
<label>Apple Account email<input type="email" name="username" value="{html.escape(username, quote=True)}" autocomplete="username" required></label>
<label>one-time Apple calendar password<input type="password" name="password" placeholder="xxxx-xxxx-xxxx-xxxx" autocomplete="off" autocapitalize="none" spellcheck="false" required></label>
<button>CONNECT CALENDAR</button>
</form>
<p class="dim">Use the password Apple generated — never your normal Apple Account password.</p>''',
    )


@core.app.post("/setup/apple")
def apple_post(request: Request, username: str = Form(...), password: str = Form(...)):
    artist = core.current_artist(request)
    if not artist:
        return RedirectResponse("/setup")

    username = username.strip()
    password = password.strip()
    try:
        calendars = core.apple_discover_calendars(username, password)
    except Exception:
        return core.page(
            "Apple Calendar",
            f'''<h1>APPLE DIDN'T ACCEPT THAT.</h1>
<p>Make sure you pasted the app-specific password Apple generated for Empty Chair — not your normal Apple password.</p>
<div class="space"></div>
<a class="button" href="{APPLE_ACCOUNT_URL}" target="_blank" rel="noopener noreferrer">OPEN APPLE ACCOUNT</a>
<div class="space"></div>
<a class="button quiet" href="/setup/apple">TRY AGAIN</a>''',
        )

    # Store only after Apple has accepted the credential and calendar discovery succeeds.
    core.run(
        "INSERT INTO calendar_accounts(artist_id,provider,calendar_id,apple_username,apple_password,apple_calendar_url,connected_at) VALUES(?,?,?,?,?,?,?) "
        "ON CONFLICT(artist_id) DO UPDATE SET provider=excluded.provider,calendar_id=excluded.calendar_id,access_token=NULL,refresh_token=NULL,token_expires_at=NULL,apple_username=excluded.apple_username,apple_password=excluded.apple_password,apple_calendar_url=excluded.apple_calendar_url,connected_at=excluded.connected_at",
        (artist["id"], "apple", "", username, password, "", core.utcnow()),
    )
    return _calendar_picker(artist, calendars)


def _usable_calendars(calendars: list[tuple[str, str]]) -> list[tuple[str, str]]:
    blocked_names = {"reminders", "birthdays", "holidays", "contacts"}
    usable = []
    for name, url in calendars:
        clean = (name or "Calendar").strip()
        if clean.lower() in blocked_names:
            continue
        usable.append((clean, url))
    return usable or calendars


def _calendar_picker(artist: dict, calendars: list[tuple[str, str]]):
    calendars = _usable_calendars(calendars)
    rows = "".join(
        f'''<label style="display:flex;align-items:center;gap:12px;padding:14px 0;border-bottom:1px solid var(--off);color:var(--bright);cursor:pointer">
<input type="radio" name="calendar_url" value="{html.escape(url, quote=True)}" required style="width:18px;height:18px;margin:0;accent-color:var(--amber);flex:0 0 auto">
<span>{html.escape(name)}</span>
</label>'''
        for name, url in calendars
    )
    return core.page(
        "Apple Calendar",
        f'''<h1>WHICH ONE HOLDS TATTOOS?</h1>
<p class="dim">Empty Chair will watch this calendar for canceled appointments and put filled chairs back on it.</p>
<div class="space"></div>
<form method="post" action="/setup/apple/select">
<div>{rows}</div>
<div class="space"></div>
<button>USE THIS CALENDAR</button>
</form>''',
    )


@core.app.get("/setup/apple/select")
def apple_select(request: Request):
    artist = core.current_artist(request)
    if not artist:
        return RedirectResponse("/setup")
    acct = core.one("SELECT * FROM calendar_accounts WHERE artist_id=?", (artist["id"],))
    if not acct or acct.get("provider") != "apple" or not acct.get("apple_username") or not acct.get("apple_password"):
        return RedirectResponse("/setup/apple")
    try:
        calendars = core.apple_discover_calendars(acct["apple_username"], acct["apple_password"])
    except Exception:
        return RedirectResponse("/setup/apple")
    return _calendar_picker(artist, calendars)


@core.app.post("/setup/apple/select")
def apple_select_post(request: Request, calendar_url: str = Form(...)):
    artist = core.current_artist(request)
    if not artist:
        return RedirectResponse("/setup")
    acct = core.one("SELECT * FROM calendar_accounts WHERE artist_id=?", (artist["id"],))
    if not acct or acct.get("provider") != "apple":
        return RedirectResponse("/setup/apple")

    # Only accept URLs that Apple itself returned for this credential.
    try:
        allowed = {url for _, url in _usable_calendars(core.apple_discover_calendars(acct["apple_username"], acct["apple_password"]))}
    except Exception:
        return RedirectResponse("/setup/apple")
    if calendar_url not in allowed:
        return RedirectResponse("/setup/apple/select")

    core.run(
        "UPDATE calendar_accounts SET calendar_id='selected',apple_calendar_url=?,connected_at=? WHERE artist_id=?",
        (calendar_url, core.utcnow(), artist["id"]),
    )

    # Reconnecting/changing a calendar must never disarm an already configured artist.
    # New artists continue directly to the specific deposit/payment step.
    if artist.get("setup_state") == "ARMED":
        return RedirectResponse("/", status_code=303)
    core.run(
        "UPDATE artists SET setup_state='PAYMENT',updated_at=? WHERE id=?",
        (core.utcnow(), artist["id"]),
    )
    return RedirectResponse("/setup/payment", status_code=303)


print("Empty Chair 2.0 web Apple Calendar UX + robust polling loaded", flush=True)
