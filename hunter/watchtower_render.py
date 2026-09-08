"""Render entrypoint for Hunter Watchtower with safe diagnostics and one-time Instagram bootstrap."""
from __future__ import annotations

import html
import json
import os
import threading
import time
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs

from fastapi import Request
from fastapi.responses import HTMLResponse, JSONResponse
from playwright.sync_api import sync_playwright

import hunter.watchtower_service as service
from hunter.watchtower_service import SCHEMA, _worker_state, app

BOOTSTRAP_STATE = Path(os.getenv("WATCHTOWER_BOOTSTRAP_STATE", "/data/instagram-bootstrap-state.json"))
_original_authenticated = service.authenticated
_bootstrap_lock = threading.Lock()
_bootstrap_status: dict[str, Any] = {"state": "idle", "message": "", "ok": None}


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
        "bootstrap": dict(_bootstrap_status),
    }


def _page(message: str = "", ok: bool | None = None, refresh: bool = False) -> HTMLResponse:
    tone = "#53d769" if ok else "#ffb020" if ok is False else "#ddd"
    safe_message = html.escape(message)
    refresh_tag = "<meta http-equiv='refresh' content='4'>" if refresh else ""
    body = f"""<!doctype html>
<html><head><meta name='viewport' content='width=device-width,initial-scale=1'>{refresh_tag}
<title>Hunter Watchtower Bootstrap</title>
<style>
body{{background:#0b0b0c;color:#f4f4f4;font-family:-apple-system,BlinkMacSystemFont,Segoe UI,sans-serif;margin:0;padding:28px}}
main{{max-width:540px;margin:0 auto}}h1{{font-size:30px;margin:0 0 8px}}h2{{font-size:21px;margin:28px 0 8px}}p{{line-height:1.45;color:#bbb}}
label{{display:block;margin:18px 0 6px;font-weight:700}}input{{width:100%;box-sizing:border-box;padding:14px;border:1px solid #444;border-radius:10px;background:#161618;color:white;font-size:16px}}
button{{width:100%;margin-top:22px;padding:15px;border:0;border-radius:10px;background:#8b5cf6;color:white;font-size:17px;font-weight:800}}
.secondary{{background:#222;border:1px solid #555}}.panel{{margin-top:24px;padding-top:4px;border-top:1px solid #333}}
.msg{{margin:18px 0;padding:14px;border:1px solid {tone};border-radius:10px;color:{tone};white-space:pre-wrap}}
#importResult{{margin-top:14px;white-space:pre-wrap;color:#bbb}}
small{{display:block;color:#888;margin-top:18px;line-height:1.45}}
</style></head><body><main>
<h1>Hunter Watchtower</h1><p>One-time Instagram authentication for the virtual Chromium worker.</p>
{f"<div class='msg'>{safe_message}</div>" if message else ""}
<div class='panel'>
<h2>Import existing authenticated session</h2>
<p>Use the Safari session JSON created by Hunter. The file is sent directly from this browser to your Render service over HTTPS. Its cookie values are never displayed by this page or written to GitHub.</p>
<label>Watchtower control token</label><input type='password' id='importToken' autocomplete='off'>
<label>Safari session JSON</label><input type='file' id='sessionFile' accept='.json,application/json'>
<button type='button' class='secondary' onclick='importSession()'>Import existing session</button>
<div id='importResult'></div>
</div>
<div class='panel'>
<h2>Fresh login</h2>
<form method='post' action='/bootstrap'>
<label>Watchtower control token</label><input type='password' name='token' autocomplete='off' required>
<label>Instagram username</label><input type='text' name='username' autocapitalize='none' autocomplete='username' required>
<label>Instagram password</label><input type='password' name='password' autocomplete='current-password' required>
<button type='submit'>Authenticate virtual browser</button>
</form>
</div>
<small>The existing-session import is preferred when Instagram's new-device approval flow hangs. Hunter does not bypass account verification.</small>
<script>
async function importSession(){{
  const out=document.getElementById('importResult');
  const token=document.getElementById('importToken').value;
  const input=document.getElementById('sessionFile');
  if(!token){{out.textContent='Enter the Watchtower control token.';return;}}
  if(!input.files.length){{out.textContent='Choose the Safari session JSON file.';return;}}
  out.textContent='Importing session…';
  try{{
    const text=await input.files[0].text();
    const session=JSON.parse(text);
    const response=await fetch('/bootstrap/import-session',{{
      method:'POST',
      headers:{{'Content-Type':'application/json','Cache-Control':'no-store'}},
      body:JSON.stringify({{token,session}})
    }});
    const data=await response.json();
    out.textContent=data.message || (data.ok ? 'Session imported.' : 'Import failed.');
    if(data.ok) setTimeout(()=>window.location='/diagnostics',1200);
  }}catch(err){{out.textContent='Import failed: '+err.message;}}
}}
</script>
</main></body></html>"""
    return HTMLResponse(body, headers={"Cache-Control": "no-store"})


@app.get("/bootstrap", response_class=HTMLResponse)
def bootstrap_form() -> HTMLResponse:
    if _worker_state.get("authenticated"):
        return _page("The Watchtower browser is already authenticated.", True)
    state = _bootstrap_status.get("state")
    if state == "running":
        return _page(str(_bootstrap_status.get("message") or "Login attempt is running in the virtual browser. This page will refresh automatically."), None, refresh=True)
    if state in {"finished", "failed"}:
        return _page(str(_bootstrap_status.get("message") or ""), _bootstrap_status.get("ok"))
    return _page()


def _valid_imported_cookies(session: Any) -> list[dict[str, Any]]:
    if not isinstance(session, dict):
        raise ValueError("session file must contain a JSON object")
    cookies = session.get("cookies")
    if not isinstance(cookies, list) or not cookies:
        raise ValueError("session file does not contain cookies")

    cleaned: list[dict[str, Any]] = []
    for raw in cookies:
        if not isinstance(raw, dict):
            continue
        name = str(raw.get("name") or "")
        value = str(raw.get("value") or "")
        domain = str(raw.get("domain") or "")
        path = str(raw.get("path") or "/")
        if not name or not value or not domain:
            continue
        normalized_domain = domain.lstrip(".").lower()
        if normalized_domain != "instagram.com" and not normalized_domain.endswith(".instagram.com"):
            continue
        cookie: dict[str, Any] = {
            "name": name,
            "value": value,
            "domain": domain,
            "path": path,
            "secure": bool(raw.get("secure", True)),
            "httpOnly": bool(raw.get("httpOnly", False)),
        }
        same_site = raw.get("sameSite")
        if same_site in {"Strict", "Lax", "None"}:
            cookie["sameSite"] = same_site
        expiry = raw.get("expiry")
        if isinstance(expiry, (int, float)) and expiry > 0:
            cookie["expires"] = float(expiry)
        cleaned.append(cookie)

    if not any(cookie.get("name") == "sessionid" for cookie in cleaned):
        raise ValueError("session file does not contain an Instagram sessionid cookie")
    return cleaned


@app.post("/bootstrap/import-session")
async def import_existing_session(request: Request) -> JSONResponse:
    try:
        raw = await request.body()
        if len(raw) > 512_000:
            return JSONResponse({"ok": False, "message": "Session file is too large."}, status_code=413)
        payload = json.loads(raw.decode("utf-8"))
    except Exception:
        return JSONResponse({"ok": False, "message": "Invalid JSON request."}, status_code=400)

    token = str(payload.get("token") or "") if isinstance(payload, dict) else ""
    expected = os.getenv("WATCHTOWER_API_TOKEN", "").strip()
    if not expected or token != expected:
        return JSONResponse({"ok": False, "message": "Invalid Watchtower control token."}, status_code=401)

    try:
        cookies = _valid_imported_cookies(payload.get("session"))
        BOOTSTRAP_STATE.parent.mkdir(parents=True, exist_ok=True)
        temp_path = BOOTSTRAP_STATE.with_suffix(".tmp")
        temp_path.write_text(json.dumps({"cookies": cookies, "origins": []}), encoding="utf-8")
        try:
            os.chmod(temp_path, 0o600)
        except OSError:
            pass
        temp_path.replace(BOOTSTRAP_STATE)
        _bootstrap_status.update({
            "state": "finished",
            "message": "Existing Instagram session imported. Watchtower will use it on the next authenticated request.",
            "ok": True,
        })
        _worker_state["last_error"] = None
        return JSONResponse({
            "ok": True,
            "message": "Existing Instagram session imported. Open diagnostics; authentication will be verified by the Watchtower browser on its next Instagram request.",
        }, headers={"Cache-Control": "no-store"})
    except ValueError as exc:
        return JSONResponse({"ok": False, "message": str(exc)}, status_code=400)
    except Exception as exc:
        _worker_state["last_error"] = f"session import: {exc.__class__.__name__}: {exc}"
        return JSONResponse({"ok": False, "message": "Watchtower could not store the imported session."}, status_code=500)


def _first_visible(page, selectors: list[str]):
    for selector in selectors:
        try:
            locator = page.locator(selector)
            if locator.count() and locator.first.is_visible(timeout=1500):
                return locator.first
        except Exception:
            continue
    return None


def _has_session(context) -> bool:
    try:
        cookies = context.cookies("https://www.instagram.com")
        return any(cookie.get("name") == "sessionid" for cookie in cookies)
    except Exception:
        return False


def _wait_for_instagram_approval(page, context, seconds: int = 90) -> tuple[bool, str]:
    deadline = time.monotonic() + seconds
    _bootstrap_status.update({
        "state": "running",
        "message": "Instagram approval is required. Approve the login once in the Instagram app. Do not submit this form again; Hunter is keeping the virtual browser alive and waiting for the approval.",
        "ok": None,
    })
    while time.monotonic() < deadline:
        if _has_session(context):
            context.storage_state(path=str(BOOTSTRAP_STATE))
            return True, "Instagram approval succeeded. Session state is ready for the Watchtower worker."
        try:
            page.wait_for_timeout(2000)
        except Exception:
            time.sleep(2)
    return False, "Instagram approval did not complete within 90 seconds. No session was created. Do not keep retrying; open /diagnostics and send me the bootstrap status instead."


def _bootstrap_sync(username: str, password: str) -> tuple[str, bool]:
    try:
        BOOTSTRAP_STATE.parent.mkdir(parents=True, exist_ok=True)
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"])
            context = browser.new_context(viewport={"width": 1280, "height": 900})
            page = context.new_page()
            page.goto("https://www.instagram.com/accounts/login/", wait_until="domcontentloaded", timeout=30000)
            page.wait_for_timeout(2500)

            user_field = _first_visible(page, [
                "input[name='username']",
                "input[autocomplete='username']",
                "input[type='text']",
                "input[aria-label*='username' i]",
                "input[aria-label*='phone' i]",
            ])
            pass_field = _first_visible(page, [
                "input[name='password']",
                "input[autocomplete='current-password']",
                "input[type='password']",
            ])

            if not user_field or not pass_field:
                try:
                    body = page.locator("body").inner_text(timeout=5000).strip().replace("\n", " | ")[:500]
                except Exception:
                    body = ""
                current = page.url
                browser.close()
                return (f"Instagram did not render a standard login form. Page: {current}. Visible page text: {body or '[none]'}. This usually means Instagram served an interstitial, consent screen, or blocked login page to the Render browser.", False)

            user_field.fill(username, timeout=10000)
            pass_field.fill(password, timeout=10000)

            submit = _first_visible(page, [
                "button[type='submit']",
                "button:has-text('Log in')",
                "div[role='button']:has-text('Log in')",
            ])
            if not submit:
                browser.close()
                return ("Instagram rendered the login fields but no usable Log in button. The page layout has changed or an interstitial is blocking submission.", False)

            submit.click(timeout=10000)
            page.wait_for_timeout(6000)

            if _has_session(context):
                context.storage_state(path=str(BOOTSTRAP_STATE))
                browser.close()
                return ("Instagram login succeeded. Session state is ready for the Watchtower worker. Open /diagnostics in a few seconds.", True)

            text = ""
            try:
                text = page.locator("body").inner_text(timeout=5000).lower()
            except Exception:
                pass
            current = page.url

            challenge_words = (
                "check your notifications",
                "security code",
                "enter code",
                "confirm it's you",
                "challenge",
                "approve",
                "trying to log in",
                "is this you",
            )
            challenge = any(word in text for word in challenge_words) or "/challenge/" in current.lower() or "/auth_platform/" in current.lower()
            if challenge:
                ok, message = _wait_for_instagram_approval(page, context, seconds=90)
                browser.close()
                return message, ok

            browser.close()
            return (f"Instagram did not establish a session. Current page: {current}. Open /diagnostics and send me the bootstrap status; do not repeatedly retry the login.", False)
    except Exception as exc:
        return (f"Bootstrap failed: {exc.__class__.__name__}: {str(exc)[:700]}", False)


def _bootstrap_runner(username: str, password: str) -> None:
    try:
        message, ok = _bootstrap_sync(username, password)
        _bootstrap_status.update({"state": "finished" if ok else "failed", "message": message, "ok": ok})
    finally:
        _bootstrap_lock.release()


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
    if not _bootstrap_lock.acquire(blocking=False):
        return _page("A login attempt is already running. Keep this page open; it will refresh automatically.", None, refresh=True)

    _bootstrap_status.update({"state": "running", "message": "Login attempt started. If Instagram asks for approval, approve it once in the app; this browser will stay alive for up to 90 seconds.", "ok": None})
    threading.Thread(target=_bootstrap_runner, args=(username, password), name="watchtower-bootstrap", daemon=True).start()
    return _page("Login attempt started. If Instagram asks for approval, approve it once in the app; this browser will stay alive for up to 90 seconds.", None, refresh=True)
