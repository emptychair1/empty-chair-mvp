"""Render wrapper that adds a safe, token-protected session verification page."""
from __future__ import annotations

import html
import os
from urllib.parse import parse_qs

from fastapi import Request
from fastapi.responses import HTMLResponse

import hunter.watchtower_service as service
import hunter.watchtower_render  # noqa: F401  # registers bootstrap/diagnostics routes
from hunter.watchtower_render import app

VERIFY_USERNAME = os.getenv("WATCHTOWER_VERIFY_USERNAME", "nickbriggstattoos").strip().lstrip("@")


def _page(message: str = "", ok: bool | None = None) -> HTMLResponse:
    tone = "#53d769" if ok else "#ffb020" if ok is False else "#ddd"
    safe = html.escape(message)
    body = f"""<!doctype html>
<html><head><meta name='viewport' content='width=device-width,initial-scale=1'>
<title>Hunter Watchtower Verify</title>
<style>
body{{background:#0b0b0c;color:#f4f4f4;font-family:-apple-system,BlinkMacSystemFont,Segoe UI,sans-serif;margin:0;padding:28px}}
main{{max-width:540px;margin:0 auto}}h1{{font-size:30px;margin:0 0 8px}}p{{line-height:1.45;color:#bbb}}
label{{display:block;margin:18px 0 6px;font-weight:700}}input{{width:100%;box-sizing:border-box;padding:14px;border:1px solid #444;border-radius:10px;background:#161618;color:white;font-size:16px}}
button{{width:100%;margin-top:22px;padding:15px;border:0;border-radius:10px;background:#8b5cf6;color:white;font-size:17px;font-weight:800}}
.msg{{margin:18px 0;padding:14px;border:1px solid {tone};border-radius:10px;color:{tone};white-space:pre-wrap}}
small{{display:block;color:#888;margin-top:18px;line-height:1.45}}
</style></head><body><main>
<h1>Verify imported Instagram session</h1>
<p>This queues two read-only Story probes. The first loads the imported Safari session into Chromium; the second verifies the session on a real Instagram request.</p>
{f"<div class='msg'>{safe}</div>" if message else ""}
<form method='post' action='/verify'>
<label>Watchtower control token</label><input type='password' name='token' autocomplete='off' required>
<button type='submit'>Verify imported session</button>
</form>
<small>No Instagram password, session cookie, or token is displayed or returned by this page.</small>
</main></body></html>"""
    return HTMLResponse(body, headers={"Cache-Control": "no-store"})


@app.get("/verify", response_class=HTMLResponse)
def verify_form() -> HTMLResponse:
    if service._worker_state.get("authenticated"):
        return _page("Watchtower is already authenticated.", True)
    return _page()


@app.post("/verify", response_class=HTMLResponse)
async def verify_session(request: Request) -> HTMLResponse:
    raw = (await request.body()).decode("utf-8", errors="replace")
    form = parse_qs(raw, keep_blank_values=True)
    token = (form.get("token") or [""])[0]
    expected = os.getenv("WATCHTOWER_API_TOKEN", "").strip()
    if not expected or token != expected:
        return _page("Invalid Watchtower control token.", False)
    if not VERIFY_USERNAME:
        return _page("WATCHTOWER_VERIFY_USERNAME is not configured.", False)

    try:
        first = service.enqueue(VERIFY_USERNAME, "instagram_story")
        second = service.enqueue(VERIFY_USERNAME, "instagram_story")
    except Exception as exc:
        return _page(f"Could not queue verification: {exc.__class__.__name__}: {str(exc)[:300]}", False)

    return _page(
        "Verification queued. Open /diagnostics in about 15 seconds. "
        f"Jobs: {first['id'][:8]}…, {second['id'][:8]}…",
        True,
    )
