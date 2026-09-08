"""Founder-only Instagram Reels library for Empty Chair generated content."""
from __future__ import annotations

import html
import json
import os

from fastapi import HTTPException, Request
from fastapi.responses import HTMLResponse

import v2_app as core
import v2_settings as settings
from hunter.operator_auth import is_admin_identity, parse_phones

ADMIN_EMAILS = {
    e.strip().lower()
    for e in os.getenv("EMPTY_CHAIR_ADMIN_EMAILS", "").split(",")
    if e.strip()
}
ADMIN_PHONES = parse_phones(os.getenv("EMPTY_CHAIR_ADMIN_PHONES", ""))


def _founder(request: Request):
    artist = core.current_artist(request)
    if not artist or not is_admin_identity(
        artist,
        admin_emails=ADMIN_EMAILS,
        admin_phones=ADMIN_PHONES,
    ):
        raise HTTPException(404, "Not found")
    return artist


REELS_CSS = """
<style>
.reels-wrap{max-width:760px;margin:0 auto}.reels-head{display:flex;align-items:flex-end;justify-content:space-between;gap:16px;margin-bottom:22px}.reels-head h1{margin:0}.reels-badge{font-size:11px;color:var(--dim);text-align:right}.reel-list{display:grid;gap:24px}.reel-card{border:1px solid var(--off);padding:14px}.reel-meta{display:flex;justify-content:space-between;gap:12px;margin-bottom:12px;font-size:11px;color:var(--dim)}.reel-title{color:var(--bright);font-size:15px}.reel-video{display:block;width:100%;max-height:72svh;background:#000;border:1px solid rgba(255,176,0,.18)}.reel-actions{display:flex;gap:10px;margin-top:12px}.reel-download{display:inline-flex;align-items:center;justify-content:center;min-height:42px;padding:0 16px;border:1px solid var(--amber);color:var(--bright);text-decoration:none;font-size:12px;letter-spacing:.08em}.reel-download:hover{background:rgba(255,176,0,.08)}.reel-caption{white-space:pre-wrap;color:var(--dim);font-size:11px;line-height:1.5;margin:12px 0 0}.empty{border:1px dashed var(--off);padding:28px 16px;text-align:center;color:var(--dim)}
</style>
"""


@core.app.get("/owner/ig-reels", response_class=HTMLResponse)
def founder_ig_reels(request: Request):
    _founder(request)
    try:
        reels = core.all_rows(
            "SELECT id,local_day,slot,scenario_json,caption,status,created_at,published_at "
            "FROM growth_ig_reels ORDER BY created_at DESC LIMIT 20"
        )
    except Exception:
        reels = []

    cards = []
    for reel in reels:
        try:
            scenario = json.loads(str(reel.get("scenario_json") or "{}"))
        except Exception:
            scenario = {}
        hook = html.escape(str(scenario.get("hook") or "Generated Reel"))
        status = html.escape(str(reel.get("status") or "PREPARED").upper())
        day = html.escape(str(reel.get("local_day") or ""))
        slot = html.escape(str(reel.get("slot") or ""))
        rid = html.escape(str(reel["id"]), quote=True)
        caption = html.escape(str(reel.get("caption") or ""))
        video = ""
        actions = ""
        if str(reel.get("status") or "").upper() in {"RENDERED", "PUBLISHED"}:
            video_url = f"/instagram/reels/video/{rid}.mp4"
            video = (
                f'<video class="reel-video" controls playsinline preload="metadata" '
                f'src="{video_url}"></video>'
            )
            safe_name = html.escape(f"empty-chair-{slot}.mp4", quote=True)
            actions = (
                '<div class="reel-actions">'
                f'<a class="reel-download" href="{video_url}" download="{safe_name}">DOWNLOAD MP4</a>'
                '</div>'
            )
        else:
            video = '<div class="empty">VIDEO NOT RENDERED YET</div>'
        cards.append(
            f'''<article class="reel-card">
              <div class="reel-meta"><span>{day} // {slot}</span><span>{status}</span></div>
              <div class="reel-title">{hook}</div>
              <div class="space"></div>
              {video}
              {actions}
              <p class="reel-caption">{caption}</p>
            </article>'''
        )

    library = "".join(cards) if cards else '<div class="empty">NO GENERATED REELS YET</div>'
    body = f"""
    <div class='reels-wrap'>
      <div class='reels-head'>
        <div><p class='dim' style='margin:0 0 5px'>FOUNDER // CONTENT</p><h1>IG REELS</h1></div>
        <div class='reels-badge'>LATEST 20<br>GENERATED REELS</div>
      </div>
      <div class='reel-list'>{library}</div>
    </div>
    """
    return core.page("IG Reels", body, head=REELS_CSS)


# Patch the founder settings page after v2_settings has registered it. This keeps
# the normal settings UI untouched for customers and only inserts the founder Reel link.
_original_settings_home = settings.settings_home
for route in list(core.app.router.routes):
    if getattr(route, "path", None) == "/settings" and "GET" in (getattr(route, "methods", set()) or set()):
        core.app.router.routes.remove(route)


@core.app.get("/settings", response_class=HTMLResponse)
def settings_home_with_reels(request: Request):
    response = _original_settings_home(request)
    artist = core.current_artist(request)
    if not artist or not is_admin_identity(
        artist,
        admin_emails=ADMIN_EMAILS,
        admin_phones=ADMIN_PHONES,
    ):
        return response
    body = response.body.decode("utf-8")
    reel_row = (
        '<a class="settings-row" href="/owner/ig-reels">'
        '<span>IG REELS<small>generated videos // preview library</small></span>'
        '<span>›</span></a>'
    )
    marker = '<a class="settings-row" href="/owner/hunter">'
    if reel_row not in body:
        if marker in body:
            body = body.replace(marker, reel_row + marker, 1)
        else:
            body = body.replace('<div class="settings-list">', '<div class="settings-list">' + reel_row, 1)
    return HTMLResponse(content=body, status_code=response.status_code, headers=dict(response.headers))


print("Founder IG Reels library loaded // generated video previews + downloads // settings nav enabled", flush=True)
