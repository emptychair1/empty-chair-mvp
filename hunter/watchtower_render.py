"""Render entrypoint for Hunter Watchtower with safe diagnostics and one-time Instagram bootstrap."""
from __future__ import annotations

import asyncio
import html
import json
import os
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs

from fastapi import Request
from fastapi.responses import HTMLResponse
from playwright.sync_api import sync_playwright

import hunter.watchtower_service as service
from hunter.watchtower_service import SCHEMA, _worker_state, app

BOOTSTRAP_STATE = Path(os.getenv("WATCHTOWER_BOOTSTRAP_STATE", "/data/instagram-bootstrap-state.json"))
_original_authenticated = service.authenticated


def _install_bootstrap_state(context) -> None:
    if not BOOTSTRAP_STATE.exists():
        return
    try:
        payload = json.loads(BOOTSTRAP_STATE.read_text(encoding="utf-8"))
        cookies = payload.get("cookies") or []
        if cookies:
            context.add_cookies(cookies)
    except Exception as exc:
        _worker_state["last_error"] = f"bootstrap state import: {exc.__class__.__name__}: {exc}"


def authenticated_with_bootstrap(page, context) -> bool:
    _install_bootstrap_state(context)
    return _original_authenticated(page, context)


service.authenticated = authenticated_with_bootstrap


@app.get("/diagnostics")
def diagnostics() -> dict[str, Any]:
    return {
        "schema": SCHEMA,
        "browser_started": _worker_state.get("browser_started"),
        "authenticated": _worker_state.get("authenticated"),
        "last_heartbeat": _worker_state.get("last_heartbeat"),
        "last_error": _worker_state.get("last_error"),
        "bootstrap_state_ready": BOOTSTRAP_STATE.exists(),
    }


def _page(message: str = "", ok: bool | None = None) -> HTMLResponse:
    tone = "#53d769" if ok else "#ffb020" if ok is False else "#ddd"
    safe_message = html.escape(message)
    body = f"""<!doctype html>
<html><head><meta name='viewport' content='width=device-width,initial-scale=1'>
<title>Hunter Watchtower Bootstrap</title>
<style>
body{{background:#0b0b0c;color:#f4f4f4;font-family:-apple-system,BlinkMacSystemFont,Segoe UI,sans-serif;margin:0;padding:28px}}
main{{max-width:540px;margin:0 auto}}h1{{font-size:30px;margin:0 0 8px}}p{{line-height:1.45;color:#bbb}}
label{{display:block;margin:18px 0 6px;font-weight:700}}input{{width:100%;box-sizing:border-box;padding:14px;border:1px solid #444;border-radius:10px;background:#161618;color:white;font-size:16px}}
button{{width:100%;margin-top:22px;padding:15px;border:0;border-radius:10px;background:#8b5cf6;color:white;font-size:17px;font-weight:800}}
.msg{{margin:18px 0;padding:14px;border:1px solid {tone};border-radius:10px;color:{tone};white-space:pre-wrap}}
small{{display:block;color:#888;margin-top:18px;line-height:1.45}}
</style></head><body><main>
<h1>Hunter Watchtower</h1><p>One-time Instagram authentication for the virtual Chromium worker.</p>
{f"<div class='msg'>{safe_message}</div>" if message else ""}
<form method='post' action='/bootstrap'>
<label>Watchtower control token</label><input type='password' name='token' autocomplete='off' required>
<label>Instagram username</label><input type='text' name='username' autocapitalize='none' autocomplete='username' required>
<label>Instagram password</label><input type='password' name='password' autocomplete='current-password' required>
<button type='submit'>Authenticate virtual browser</button>
</form>
<small>The control token is the WATCHTOWER_API_TOKEN stored in Render. Instagram credentials are used only for this login attempt and are not written to the repo or returned by the API. If Instagram asks you to approve a new login, approve it in the Instagram app and submit this form again.</small>
</main></body></html>"""
    return HTMLResponse(body, headers={"Cache-Control": "no-store"})


@app.get("/bootstrap", response_class=HTMLResponse)
def bootstrap_form() -> HTMLResponse:
    if _worker_state.get("authenticated"):
        return _page("The Watchtower browser is already authenticated.", True)
    return _page()


def _bootstrap_sync(username: str, password: str) -> tuple[str, bool]:
    """Run Playwright Sync API outside FastAPI's asyncio event-loop thread."""
    try:
        BOOTSTRAP_STATE.parent.mkdir(parents=True, exist_ok=True)
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"])
            context = browser.new_context(viewport={"width": 1280, "height": 900})
            page = context.new_page()
            page.goto("https://www.instagram.com/accounts/login/", wait_until="domcontentloaded", timeout=45000)
            page.locator("input[name='username']").fill(username, timeout=15000)
            page.locator("input[name='password']").fill(password, timeout=15000)
            page.locator("button[type='submit']").click(timeout=15000)
            page.wait_for_timeout(6000)

            cookies = context.cookies("https://www.instagram.com")
            authed = any(cookie.get("name") == "sessionid" for cookie in cookies)
            if authed:
                context.storage_state(path=str(BOOTSTRAP_STATE))
                browser.close()
                return ("Instagram login succeeded. Session state is ready for the Watchtower worker. Open /diagnostics in a few seconds.", True)

            text = ""
            try:
                text = page.locator("body").inner_text(timeout=5000).lower()
            except Exception:
                pass
            browser.close()

            challenge_words = ("check your notifications", "security code", "enter code", "confirm it's you", "challenge", "approve")
            if any(word in text for word in challenge_words):
                return ("Instagram requires account approval or verification. Approve the login in the Instagram app, then submit this form again. Hunter will not bypass the verification step.", False)
            return ("Instagram did not establish a session. Check the credentials and Instagram app for a login approval prompt, then try again.", False)
    except Exception as exc:
        return (f"Bootstrap failed: {exc.__class__.__name__}: {str(exc)[:700]}", False)


@app.post("/bootstrap", response_class=HTMLResponse)
async def bootstrap_login(request: Request) -> HTMLResponse:
    raw = (await request.body()).decode("utf-8", errors="replace")
    form = parse_qs(raw, keep_blank_values=True)
    token = (form.get("token") or [""])[0]
    username = (form.get("username") or [""])[0].strip()
    password = (form.get("password") or [""])[0]

    expected = os.getenv("WATCHTOWER_API_TOKEN", "").strip()
    if not expected or token != expected:
        return _page("Invalid Watchtower control token.", False)
    if not username or not password:
        return _page("Instagram username and password are required.", False)

    message, ok = await asyncio.to_thread(_bootstrap_sync, username, password)
    return _page(message, ok)
