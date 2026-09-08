"""Production repair for Sign in with Apple.

Uses Apple's supported web JavaScript flow instead of sending iOS Safari straight
at the authorize endpoint, validates state + nonce, and keeps Apple hidden unless
its production configuration gate is enabled.
"""
from __future__ import annotations

import html
import json
import secrets
import time

import jwt
from fastapi import Form
from fastapi.responses import RedirectResponse

import v2_app as core
import v2_auth as auth


def _drop_route(path: str, methods: set[str]):
    kept = []
    for route in core.app.router.routes:
        route_methods = set(getattr(route, "methods", set()) or set())
        if getattr(route, "path", None) == path and methods.issubset(route_methods):
            continue
        kept.append(route)
    core.app.router.routes[:] = kept


_drop_route("/auth/apple/login", {"GET"})
_drop_route("/auth/apple/callback", {"POST"})


def _ready() -> bool:
    return bool(
        auth.APPLE_SIGNIN_ENABLED
        and auth.APPLE_CLIENT_ID
        and auth.APPLE_TEAM_ID
        and auth.APPLE_KEY_ID
        and auth.APPLE_PRIVATE_KEY
        and core.BASE_URL.startswith("https://")
    )


def _state_with_nonce(nonce: str) -> str:
    return core.sign(f"apple:{int(time.time())}:{nonce}")


def _state_nonce(value: str | None) -> str | None:
    raw = core.unsign(value)
    if not raw:
        return None
    parts = raw.split(":", 2)
    if len(parts) != 3 or parts[0] != "apple":
        return None
    try:
        if abs(int(time.time()) - int(parts[1])) > 600:
            return None
    except Exception:
        return None
    return parts[2]


@core.app.get("/auth/apple/login")
def apple_login_repaired():
    if not _ready():
        return core.page(
            "Apple",
            "<div class='error'>APPLE SIGN-IN IS TEMPORARILY UNAVAILABLE.</div>"
            "<p class='dim'>Please continue with phone or Google.</p>"
            "<a class='button' href='/'>BACK</a>",
        )

    nonce = secrets.token_urlsafe(24)
    state = _state_with_nonce(nonce)
    client_id = html.escape(auth.APPLE_CLIENT_ID, quote=True)
    redirect_uri = html.escape(f"{core.BASE_URL}/auth/apple/callback", quote=True)
    state_e = html.escape(state, quote=True)
    nonce_e = html.escape(nonce, quote=True)

    # Apple recommends its hosted JS framework for web authorization. Keeping the
    # authorization inside Apple's web SDK also avoids iOS universal-link/account
    # routing quirks from a raw appleid.apple.com redirect.
    body = f"""
<div class="center">
  <h1>CONTINUE WITH APPLE</h1>
  <p class="dim">Secure sign-in through Apple.</p>
  <div class="space"></div>
  <div id="appleid-signin" data-color="black" data-border="true" data-type="sign in"></div>
  <div class="space"></div>
  <a class="button quiet" href="/">BACK</a>
</div>
<meta name="appleid-signin-client-id" content="{client_id}">
<meta name="appleid-signin-scope" content="name email">
<meta name="appleid-signin-redirect-uri" content="{redirect_uri}">
<meta name="appleid-signin-state" content="{state_e}">
<meta name="appleid-signin-nonce" content="{nonce_e}">
<meta name="appleid-signin-use-popup" content="false">
<script type="text/javascript" src="https://appleid.cdn-apple.com/appleauth/static/jsapi/appleid/1/en_US/appleid.auth.js"></script>
"""
    return core.page("Apple sign in", body)


@core.app.post("/auth/apple/callback")
def apple_callback_repaired(
    code: str | None = Form(None),
    state: str | None = Form(None),
    user: str | None = Form(None),
    error: str | None = Form(None),
    error_description: str | None = Form(None),
):
    if not _ready():
        return RedirectResponse("/", status_code=303)

    nonce = _state_nonce(state)
    if not nonce:
        return core.page("Apple", "<div class='error'>SIGN-IN SESSION EXPIRED.</div><a class='button' href='/'>BACK</a>")

    if error:
        safe = html.escape(error_description or error)
        return core.page("Apple", f"<div class='error'>APPLE SIGN-IN COULD NOT COMPLETE.</div><p class='dim'>{safe}</p><a class='button' href='/'>BACK</a>")

    if not code:
        return core.page("Apple", "<div class='error'>APPLE DID NOT RETURN AN AUTHORIZATION CODE.</div><a class='button' href='/'>BACK</a>")

    try:
        token = core.http_json("https://appleid.apple.com/auth/token", "POST", form={
            "client_id": auth.APPLE_CLIENT_ID,
            "client_secret": auth._apple_client_secret(),
            "code": code,
            "grant_type": "authorization_code",
            "redirect_uri": f"{core.BASE_URL}/auth/apple/callback",
        })
        id_token = token.get("id_token")
        if not id_token:
            raise ValueError("missing identity token")

        jwks = jwt.PyJWKClient("https://appleid.apple.com/auth/keys")
        signing_key = jwks.get_signing_key_from_jwt(id_token)
        claims = jwt.decode(
            id_token,
            signing_key.key,
            algorithms=["RS256"],
            audience=auth.APPLE_CLIENT_ID,
            issuer="https://appleid.apple.com",
        )
        if claims.get("nonce") != nonce:
            raise ValueError("nonce mismatch")
    except Exception as exc:
        print(f"APPLE SIGN-IN CALLBACK FAILED // {type(exc).__name__}: {exc}", flush=True)
        return core.page(
            "Apple",
            "<div class='error'>APPLE SIGN-IN COULD NOT COMPLETE.</div>"
            "<p class='dim'>Please try again or continue with phone/Google.</p>"
            "<a class='button' href='/'>BACK</a>",
        )

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

    artist = auth._create_or_link("apple", str(claims["sub"]), email, name)
    return auth._finish_login(artist)


print("Sign in with Apple repair loaded // Apple JS + nonce validation")
