"""Social authentication for Empty Chair 2.0.

Adds Sign in with Google, Sign in with Apple, and phone signup without coupling
account identity to the artist's calendar provider.
"""
from __future__ import annotations

import json
import os
import secrets
import time
import urllib.parse

import jwt
from fastapi import Form, Request
from fastapi.responses import RedirectResponse

import v2_app as core

GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET", "")
APPLE_CLIENT_ID = os.getenv("APPLE_CLIENT_ID", "")  # Services ID
APPLE_TEAM_ID = os.getenv("APPLE_TEAM_ID", "")
APPLE_KEY_ID = os.getenv("APPLE_KEY_ID", "")
APPLE_PRIVATE_KEY = os.getenv("APPLE_PRIVATE_KEY", "").replace("\\n", "\n")
# Safety gate: Apple login stays out of production until the Services ID,
# production domain/return URL, key, and end-to-end flow have been verified.
APPLE_SIGNIN_ENABLED = os.getenv("APPLE_SIGNIN_ENABLED", "false").strip().lower() in {"1", "true", "yes", "on"}


def _apple_ready() -> bool:
    return bool(
        APPLE_SIGNIN_ENABLED
        and APPLE_CLIENT_ID
        and APPLE_TEAM_ID
        and APPLE_KEY_ID
        and APPLE_PRIVATE_KEY
        and core.BASE_URL.startswith("https://")
    )


def _drop_route(path: str, methods: set[str]):
    kept = []
    for route in core.app.router.routes:
        route_methods = set(getattr(route, "methods", set()) or set())
        if getattr(route, "path", None) == path and methods.issubset(route_methods):
            continue
        kept.append(route)
    core.app.router.routes[:] = kept


for _path, _methods in [("/", {"GET"}), ("/setup", {"GET"})]:
    _drop_route(_path, _methods)


AUTH_SCHEMA = """CREATE TABLE IF NOT EXISTS auth_identities (
provider TEXT NOT NULL,
subject TEXT NOT NULL,
artist_id TEXT NOT NULL,
email TEXT,
created_at TEXT NOT NULL,
PRIMARY KEY(provider, subject)
)"""


@core.app.on_event("startup")
def social_auth_schema():
    d = core.DB()
    try:
        d.execute(AUTH_SCHEMA)
        d.commit()
    finally:
        d.close()


def _state(provider: str) -> str:
    return core.sign(f"{provider}:{int(time.time())}:{secrets.token_urlsafe(16)}")


def _valid_state(value: str | None, provider: str) -> bool:
    raw = core.unsign(value)
    if not raw:
        return False
    parts = raw.split(":", 2)
    if len(parts) != 3 or parts[0] != provider:
        return False
    try:
        return abs(int(time.time()) - int(parts[1])) <= 600
    except Exception:
        return False


def _artist_for_identity(provider: str, subject: str):
    row = core.one("SELECT artist_id FROM auth_identities WHERE provider=? AND subject=?", (provider, subject))
    return core.one("SELECT * FROM artists WHERE id=?", (row["artist_id"],)) if row else None


def _create_or_link(provider: str, subject: str, email: str, name: str):
    artist = _artist_for_identity(provider, subject)
    if artist:
        return artist

    artist = core.one("SELECT * FROM artists WHERE lower(email)=lower(?) ORDER BY created_at LIMIT 1", (email,)) if email else None
    if not artist:
        aid = secrets.token_hex(16)
        now = core.utcnow()
        core.run(
            "INSERT INTO artists(id,name,email,phone,verified,setup_state,created_at,updated_at) VALUES(?,?,?,?,0,'PHONE',?,?)",
            (aid, name or "Tattoo Artist", email or "", "", now, now),
        )
        artist = core.one("SELECT * FROM artists WHERE id=?", (aid,))

    core.run(
        "INSERT INTO auth_identities(provider,subject,artist_id,email,created_at) VALUES(?,?,?,?,?) ON CONFLICT(provider,subject) DO NOTHING",
        (provider, subject, artist["id"], email or "", core.utcnow()),
    )
    return artist


def _finish_login(artist):
    target = "/" if artist["setup_state"] == "ARMED" else "/setup"
    response = RedirectResponse(target, status_code=303)
    core.set_session(response, artist["id"])
    return response


@core.app.get("/")
def landing(request: Request):
    artist = core.current_artist(request)
    if artist:
        if artist["setup_state"] == "ARMED":
            return core.page("ARMED", '''<div class="center"><h1 class="bright">ARMED.</h1><div class="space"></div><p>calendar................[✓]</p><p>deposits................[✓]</p><p>clients..................[✓]</p><div class="space"></div><p>YOU CAN CLOSE THIS NOW.</p></div>''', chair=True)
        return RedirectResponse("/setup")

    google = '<a class="button" href="/auth/google/login">CONTINUE WITH GOOGLE</a>' if GOOGLE_CLIENT_ID else '<a class="button quiet" href="/auth/google/login">CONTINUE WITH GOOGLE</a>'
    apple = '<a class="button" href="/auth/apple/login">CONTINUE WITH APPLE</a>' if _apple_ready() else ''
    phone = '<a class="button" href="/auth/phone">CONTINUE WITH PHONE</a>'
    return core.page("Sign in", f'''<div class="center"><h1>DON'T LEAVE IT EMPTY.</h1><p class="dim">When they cancel, we fill the chair.</p></div><div class="space"></div><div class="stack">{apple}{google}{phone}</div>''', chair=True)


@core.app.get("/auth/phone")
def phone_signup_page(request: Request):
    if core.current_artist(request):
        return RedirectResponse("/setup")
    return core.page("Phone sign in", '''<h1>CONTINUE WITH PHONE</h1><form method="post" class="stack"><label>name<input name="name" autocomplete="name" required></label><label>mobile<input name="phone" autocomplete="tel" inputmode="tel" required></label><button>TEXT ME A CODE</button></form>''')


@core.app.post("/auth/phone")
def phone_signup(name: str = Form(...), phone: str = Form(...)):
    phone = core.clean_phone(phone)
    artist = core.one("SELECT * FROM artists WHERE phone=? ORDER BY created_at LIMIT 1", (phone,))
    if artist:
        aid = artist["id"]
        core.run("UPDATE artists SET name=?,updated_at=? WHERE id=?", (name.strip() or artist["name"], core.utcnow(), aid))
    else:
        aid = secrets.token_hex(16)
        now = core.utcnow()
        core.run(
            "INSERT INTO artists(id,name,email,phone,verified,setup_state,created_at,updated_at) VALUES(?,?,?,?,0,'VERIFY',?,?)",
            (aid, name.strip() or "Tattoo Artist", "", phone, now, now),
        )

    code = f"{secrets.randbelow(1000000):06d}"
    import hashlib
    from datetime import datetime, timedelta, timezone
    digest = hashlib.sha256((code + core.SESSION_SECRET).encode()).hexdigest()
    exp = (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat()
    core.run("INSERT INTO otp_codes(artist_id,code_hash,expires_at) VALUES(?,?,?) ON CONFLICT(artist_id) DO UPDATE SET code_hash=excluded.code_hash,expires_at=excluded.expires_at", (aid, digest, exp))
    core.send_sms(phone, f"EMPTY CHAIR // VERIFY\n\n{code}\n\nCode expires in 10 min.")
    response = RedirectResponse("/setup/verify", status_code=303)
    core.set_session(response, aid)
    return response


@core.app.get("/setup")
def setup(request: Request):
    artist = core.current_artist(request)
    if not artist:
        return RedirectResponse("/")
    return RedirectResponse({
        "PHONE": "/setup/phone",
        "VERIFY": "/setup/verify",
        "CALENDAR": "/setup/calendar",
        "PAYMENT": "/setup/payment",
        "CLIENTS": "/setup/clients",
        "ARMED": "/",
    }.get(artist["setup_state"], "/setup/phone"))


@core.app.get("/setup/phone")
def phone_page(request: Request):
    artist = core.current_artist(request)
    if not artist:
        return RedirectResponse("/")
    return core.page("Mobile", '''<h1>WHAT NUMBER SHOULD WE TEXT?</h1><form method="post" class="stack"><label>mobile<input name="phone" autocomplete="tel" inputmode="tel" required></label><button>CONTINUE</button></form><p class="dim">Only chair alerts and verification. No feed. No noise.</p>''')


@core.app.post("/setup/phone")
def phone_post(request: Request, phone: str = Form(...)):
    artist = core.current_artist(request)
    if not artist:
        return RedirectResponse("/")
    phone = core.clean_phone(phone)
    code = f"{secrets.randbelow(1000000):06d}"
    import hashlib
    from datetime import datetime, timedelta, timezone
    digest = hashlib.sha256((code + core.SESSION_SECRET).encode()).hexdigest()
    exp = (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat()
    core.run("UPDATE artists SET phone=?,setup_state='VERIFY',updated_at=? WHERE id=?", (phone, core.utcnow(), artist["id"]))
    core.run("INSERT INTO otp_codes(artist_id,code_hash,expires_at) VALUES(?,?,?) ON CONFLICT(artist_id) DO UPDATE SET code_hash=excluded.code_hash,expires_at=excluded.expires_at", (artist["id"], digest, exp))
    core.send_sms(phone, f"EMPTY CHAIR // VERIFY\n\n{code}\n\nCode expires in 10 min.")
    return RedirectResponse("/setup/verify", status_code=303)


@core.app.get("/auth/google/login")
def google_login():
    if not GOOGLE_CLIENT_ID:
        return core.page("Google", "<div class='error'>GOOGLE SIGN-IN IS TEMPORARILY UNAVAILABLE.</div><a class='button' href='/'>BACK</a>")
    state = _state("google")
    params = {
        "client_id": GOOGLE_CLIENT_ID,
        "redirect_uri": f"{core.BASE_URL}/auth/google/login/callback",
        "response_type": "code",
        "scope": "openid email profile",
        "state": state,
        "prompt": "select_account",
    }
    return RedirectResponse("https://accounts.google.com/o/oauth2/v2/auth?" + urllib.parse.urlencode(params))


@core.app.get("/auth/google/login/callback")
def google_login_callback(code: str, state: str):
    if not _valid_state(state, "google"):
        return core.page("Google", "<div class='error'>SIGN-IN SESSION EXPIRED.</div>")
    token = core.http_json("https://oauth2.googleapis.com/token", "POST", form={
        "code": code,
        "client_id": GOOGLE_CLIENT_ID,
        "client_secret": GOOGLE_CLIENT_SECRET,
        "redirect_uri": f"{core.BASE_URL}/auth/google/login/callback",
        "grant_type": "authorization_code",
    })
    info = core.http_json("https://openidconnect.googleapis.com/v1/userinfo", headers={"Authorization": f"Bearer {token['access_token']}"})
    artist = _create_or_link("google", str(info["sub"]), str(info.get("email") or ""), str(info.get("name") or "Tattoo Artist"))
    return _finish_login(artist)


def _apple_client_secret() -> str:
    now = int(time.time())
    return jwt.encode(
        {"iss": APPLE_TEAM_ID, "iat": now, "exp": now + 300, "aud": "https://appleid.apple.com", "sub": APPLE_CLIENT_ID},
        APPLE_PRIVATE_KEY,
        algorithm="ES256",
        headers={"kid": APPLE_KEY_ID},
    )


@core.app.get("/auth/apple/login")
def apple_login():
    if not _apple_ready():
        return core.page("Apple", "<div class='error'>APPLE SIGN-IN IS TEMPORARILY UNAVAILABLE.</div><p class='dim'>Please continue with phone or Google.</p><a class='button' href='/'>BACK</a>")
    params = {
        "client_id": APPLE_CLIENT_ID,
        "redirect_uri": f"{core.BASE_URL}/auth/apple/callback",
        "response_type": "code id_token",
        "response_mode": "form_post",
        "scope": "name email",
        "state": _state("apple"),
        "nonce": secrets.token_urlsafe(24),
    }
    return RedirectResponse("https://appleid.apple.com/auth/authorize?" + urllib.parse.urlencode(params))


@core.app.post("/auth/apple/callback")
def apple_callback(code: str = Form(...), state: str = Form(...), user: str | None = Form(None)):
    if not _apple_ready():
        return RedirectResponse("/", status_code=303)
    if not _valid_state(state, "apple"):
        return core.page("Apple", "<div class='error'>SIGN-IN SESSION EXPIRED.</div>")
    token = core.http_json("https://appleid.apple.com/auth/token", "POST", form={
        "client_id": APPLE_CLIENT_ID,
        "client_secret": _apple_client_secret(),
        "code": code,
        "grant_type": "authorization_code",
        "redirect_uri": f"{core.BASE_URL}/auth/apple/callback",
    })
    id_token = token.get("id_token")
    if not id_token:
        return core.page("Apple", "<div class='error'>APPLE DID NOT RETURN AN IDENTITY TOKEN.</div>")
    jwks = jwt.PyJWKClient("https://appleid.apple.com/auth/keys")
    signing_key = jwks.get_signing_key_from_jwt(id_token)
    claims = jwt.decode(id_token, signing_key.key, algorithms=["RS256"], audience=APPLE_CLIENT_ID, issuer="https://appleid.apple.com")
    email = str(claims.get("email") or "")
    name = "Tattoo Artist"
    if user:
        try:
            payload = json.loads(user)
            n = payload.get("name") or {}
            name = " ".join(x for x in [n.get("firstName"), n.get("lastName")] if x).strip() or name
            email = payload.get("email") or email
        except Exception:
            pass
    artist = _create_or_link("apple", str(claims["sub"]), email, name)
    return _finish_login(artist)
