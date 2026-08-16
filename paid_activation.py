"""Verify paid signup handoffs from the standalone Empty Chair sales site."""

import base64
import hashlib
import hmac
import json
import os
import time

from fastapi import Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

import app as core


app = core.app
ACTIVATION_SECRET = os.getenv("EMPTY_CHAIR_ACTIVATION_SECRET", "")
BILLING_REQUIRED = os.getenv("EMPTY_CHAIR_BILLING_REQUIRED", "false").lower() == "true"
SALES_URL = os.getenv("EMPTY_CHAIR_SALES_URL", "https://emptychair.app").rstrip("/")


def _remove_route(path, method):
    method = method.upper()
    app.router.routes = [route for route in app.router.routes if not (
        getattr(route, "path", None) == path and method in (getattr(route, "methods", set()) or set())
    )]


def ensure_schema():
    conn = core.connect()
    try:
        core.db_execute(conn, """CREATE TABLE IF NOT EXISTS consumed_activations(
            token_digest TEXT PRIMARY KEY,
            subscription_id TEXT UNIQUE NOT NULL,
            email TEXT NOT NULL,
            user_id TEXT,
            consumed_at TEXT NOT NULL
        )""")
        conn.commit()
    finally:
        conn.close()


def verify_token(token):
    if not ACTIVATION_SECRET or not token or "." not in token:
        raise HTTPException(400, "Invalid purchase activation")
    raw, signature = token.rsplit(".", 1)
    expected = hmac.new(ACTIVATION_SECRET.encode(), raw.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, signature):
        raise HTTPException(400, "Invalid purchase activation")
    try:
        padded = raw + "=" * (-len(raw) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded).decode())
    except Exception as exc:
        raise HTTPException(400, "Invalid purchase activation") from exc
    email = core.normalize_email(payload.get("email") or "")
    subscription_id = payload.get("subscription_id") or ""
    if not email or not subscription_id.startswith("sub_") or int(payload.get("exp") or 0) <= int(time.time()):
        raise HTTPException(400, "Purchase activation expired or incomplete")
    payload["email"] = email
    payload["token_digest"] = hashlib.sha256(token.encode()).hexdigest()
    return payload


_original_signup_page = core.signup_page
_original_signup = core.signup
_remove_route("/signup", "GET")
_remove_route("/signup", "POST")


@app.get("/signup", response_class=HTMLResponse)
def activated_signup_page(request: Request, activation: str = ""):
    if activation:
        payload = verify_token(activation)
        conn = core.connect()
        try:
            used = core.db_fetchone(conn, "SELECT token_digest FROM consumed_activations WHERE token_digest=? OR subscription_id=?", (payload["token_digest"], payload["subscription_id"]))
        finally:
            conn.close()
        if used:
            return RedirectResponse("/login?activation=used", status_code=303)
        # A paid activation starts a new studio account, even when the browser\n        # is currently signed into the isolated live demo. Clear that identity\n        # before delegating to the original signup page, which redirects any\n        # authenticated session to the dashboard.\n        request.session.clear()\n        request.session["paid_activation"] = payload
    if BILLING_REQUIRED and not request.session.get("paid_activation"):
        return RedirectResponse(f"{SALES_URL}/#pricing", status_code=303)
    return _original_signup_page(request)


@app.post("/signup", response_class=HTMLResponse)
def activated_signup(
    request: Request,
    name: str = Form(...),
    shop_name: str = Form(...),
    email: str = Form(...),
    password: str = Form(...),
):
    payload = request.session.get("paid_activation")
    if BILLING_REQUIRED:
        if not payload or core.normalize_email(email) != payload.get("email"):
            return RedirectResponse(f"{SALES_URL}/#pricing", status_code=303)
    response = _original_signup(request, name, shop_name, email, password)
    if getattr(response, "status_code", None) == 303 and payload:
        conn = core.connect()
        try:
            user = core.db_fetchone(conn, "SELECT id FROM users WHERE email=?", (core.normalize_email(email),))
            core.db_execute(conn, "INSERT INTO consumed_activations(token_digest,subscription_id,email,user_id,consumed_at) VALUES (?,?,?,?,?)",
                            (payload["token_digest"], payload["subscription_id"], payload["email"], user["id"] if user else None, core.now_iso()))
            conn.commit()
        finally:
            conn.close()
        request.session.pop("paid_activation", None)
    return response


@app.on_event("startup")
def initialize_paid_activation():
    ensure_schema()
