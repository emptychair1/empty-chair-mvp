"""Graceful web-only Apple Calendar connection for Empty Chair 2.0.

Apple's generic CalDAV access still requires an app-specific password. This module keeps
that one Apple handoff inside a short guided Empty Chair flow: open Apple Account, create
a one-time Empty Chair password, paste it once, then choose the tattoo calendar.
"""
from __future__ import annotations

import html

from fastapi import Form, Request
from fastapi.responses import RedirectResponse

import v2_app as core

APPLE_ACCOUNT_URL = "https://account.apple.com/"


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


def _calendar_picker(artist: dict, calendars: list[tuple[str, str]]):
    options = "".join(
        f'<label><input type="radio" name="calendar_url" value="{html.escape(url, quote=True)}" required> {html.escape(name)}</label>'
        for name, url in calendars
    )
    return core.page(
        "Apple Calendar",
        f'''<h1>WHICH ONE HOLDS TATTOOS?</h1>
<p class="dim">Empty Chair will watch this calendar for canceled appointments and put filled chairs back on it.</p>
<div class="space"></div>
<form method="post" action="/setup/apple/select" class="stack">{options}<button>USE THIS CALENDAR</button></form>''',
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
        allowed = {url for _, url in core.apple_discover_calendars(acct["apple_username"], acct["apple_password"])}
    except Exception:
        return RedirectResponse("/setup/apple")
    if calendar_url not in allowed:
        return RedirectResponse("/setup/apple/select")

    core.run(
        "UPDATE calendar_accounts SET calendar_id='selected',apple_calendar_url=?,connected_at=? WHERE artist_id=?",
        (calendar_url, core.utcnow(), artist["id"]),
    )
    core.run(
        "UPDATE artists SET setup_state='PAYMENT',updated_at=? WHERE id=?",
        (core.utcnow(), artist["id"]),
    )
    return core.page(
        "Calendar Connected",
        '''<div class="center"><h1 class="bright">CALENDAR CONNECTED [✓]</h1><p>APPLE</p><div class="space"></div><a class="button" href="/setup/payment">CONTINUE</a></div>''',
    )


print("Empty Chair 2.0 web Apple Calendar UX loaded", flush=True)
