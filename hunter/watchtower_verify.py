"""Render wrapper that adds a safe, token-protected Story verification page."""
from __future__ import annotations

import asyncio
import html
import json
import os
from urllib.parse import parse_qs

from fastapi import Request
from fastapi.responses import HTMLResponse

import hunter.watchtower_service as service
from hunter.watchtower_broadcast_patch import install as install_broadcast_patch
install_broadcast_patch(service)
import hunter.watchtower_render as render
from hunter.watchtower_render import app

VERIFY_USERNAME = os.getenv("WATCHTOWER_VERIFY_USERNAME", "nickbriggstattoos").strip().lstrip("@")
BRIDGE_TOKEN = os.getenv("HUNTER_WATCHTOWER_BRIDGE_TOKEN", "").strip()

@app.middleware("http")
async def authorize_empty_chair_bridge(request: Request, call_next):
    """Translate the app-only bridge credential into the existing Watchtower control credential."""
    supplied = request.headers.get("authorization", "")
    if BRIDGE_TOKEN and supplied == f"Bearer {BRIDGE_TOKEN}" and service.API_TOKEN:
        headers = [(k, v) for k, v in request.scope.get("headers", []) if k.lower() != b"authorization"]
        headers.append((b"authorization", f"Bearer {service.API_TOKEN}".encode()))
        request.scope["headers"] = headers
    return await call_next(request)

_original_install_bootstrap_state = render._install_bootstrap_state

def _install_durable_or_local_state(context) -> None:
    if render.BOOTSTRAP_STATE.exists():
        _original_install_bootstrap_state(context)
        return
    try:
        payload = service.durable.load_session_state()
        if payload:
            cookies = payload.get("cookies") or []
            if cookies:
                context.add_cookies(cookies)
    except Exception as exc:
        service._worker_state["last_error"] = f"durable session restore: {exc.__class__.__name__}: {exc}"

render._install_bootstrap_state = _install_durable_or_local_state


def _page(message: str = "", ok: bool | None = None) -> HTMLResponse:
    tone = "#53d769" if ok else "#ffb020" if ok is False else "#ddd"
    safe = html.escape(message)
    body = f"""<!doctype html><html><head><meta name='viewport' content='width=device-width,initial-scale=1'><title>Hunter Watchtower Verify</title><style>
body{{background:#0b0b0c;color:#f4f4f4;font-family:-apple-system,BlinkMacSystemFont,Segoe UI,sans-serif;margin:0;padding:28px}}main{{max-width:540px;margin:0 auto}}h1{{font-size:30px;margin:0 0 8px}}p{{line-height:1.45;color:#bbb}}label{{display:block;margin:18px 0 6px;font-weight:700}}input{{width:100%;box-sizing:border-box;padding:14px;border:1px solid #444;border-radius:10px;background:#161618;color:white;font-size:16px}}button{{width:100%;margin-top:22px;padding:15px;border:0;border-radius:10px;background:#8b5cf6;color:white;font-size:17px;font-weight:800}}.msg{{margin:18px 0;padding:14px;border:1px solid {tone};border-radius:10px;color:{tone};white-space:pre-wrap;overflow-wrap:anywhere}}small{{display:block;color:#888;margin-top:18px;line-height:1.45}}</style></head><body><main>
<h1>Verify cloud Story collection</h1><p>This runs two read-only Story probes against <strong>@{html.escape(VERIFY_USERNAME)}</strong> and shows the actual cloud collector result.</p>{f"<div class='msg'>{safe}</div>" if message else ""}<form method='post' action='/verify'><label>Watchtower control token</label><input type='password' name='token' autocomplete='off' required><button type='submit'>Run cloud Story probe</button></form><small>Only collector status, score, and matched recovery signals are shown. Instagram credentials, cookies, and Story body text are never returned by this page.</small></main></body></html>"""
    return HTMLResponse(body, headers={"Cache-Control":"no-store"})


def _job_result(job_id: str) -> dict | None:
    try:
        row = service.durable.get_job(job_id) if service.durable.enabled() else None
        if row is None and not service.durable.enabled():
            with service.db() as conn:
                row = conn.execute("SELECT id,username,status,result_json,error FROM watchtower_jobs WHERE id=?", (job_id,)).fetchone()
        if not row: return None
        payload = service.row_payload(row); result = payload.get("result") or {}
        return {"id":payload["id"],"username":payload["username"],"job_status":payload["status"],"collector_status":result.get("status"),"intent_score":result.get("intent_score"),"matches":result.get("matches") or [],"error":payload.get("error")}
    except Exception: return None


def _format_result(first: dict | None, second: dict | None) -> tuple[str,bool]:
    items=[i for i in (first,second) if i]
    if not items: return "No verification jobs were found.",False
    lines=["CLOUD STORY PROBE RESULTS"]; passed=False
    for index,item in enumerate(items,1):
        collector=item.get("collector_status") or "pending"
        lines += ["",f"Probe {index}: {item.get('job_status')}",f"Collector: {collector}",f"Intent score: {item.get('intent_score') if item.get('intent_score') is not None else '-'}",f"Matches: {', '.join(item.get('matches') or []) or '-'}"]
        if item.get("error"): lines.append(f"Error: {item['error'][:500]}")
        if collector in {"recovery_story_found","story_visible_no_recovery_text","unknown_no_viewable_story"}: passed=True
    if passed: lines += ["","PASS: Render reached Instagram with the authenticated cloud browser and the Story collector returned a real collector result."]
    elif all(i.get("job_status") in {"finished","failed"} for i in items): lines += ["","FAIL: the cloud Story collector did not return a successful authenticated result."]
    else: lines += ["","Still processing. Run the probe again in a few seconds if needed."]
    return "\n".join(lines),passed


@app.get("/verify", response_class=HTMLResponse)
def verify_form() -> HTMLResponse:
    if service._worker_state.get("authenticated"): return _page("Watchtower is authenticated and ready. Run the cloud Story probe below.",True)
    return _page("Watchtower is not authenticated yet. Import the existing Instagram session at /bootstrap first.",False)


@app.post("/verify", response_class=HTMLResponse)
async def verify_session(request: Request) -> HTMLResponse:
    form=parse_qs((await request.body()).decode("utf-8",errors="replace"),keep_blank_values=True)
    token=(form.get("token") or [""])[0]; expected=os.getenv("WATCHTOWER_API_TOKEN","").strip()
    if not expected or token != expected: return _page("Invalid Watchtower control token.",False)
    if not VERIFY_USERNAME: return _page("WATCHTOWER_VERIFY_USERNAME is not configured.",False)
    try:
        first=service.enqueue(VERIFY_USERNAME,"instagram_story"); second=service.enqueue(VERIFY_USERNAME,"instagram_story")
    except Exception as exc: return _page(f"Could not queue verification: {exc.__class__.__name__}: {str(exc)[:300]}",False)
    first_result=second_result=None
    for _ in range(35):
        first_result=_job_result(first["id"]); second_result=_job_result(second["id"])
        if first_result and second_result and first_result.get("job_status") in {"finished","failed"} and second_result.get("job_status") in {"finished","failed"}: break
        await asyncio.sleep(1)
    message,passed=_format_result(first_result,second_result); return _page(message,passed)
