"""Isolated Instagram Reels scenario engine.

This module is deliberately additive. It does not modify the existing CRT feed-post
state, renderer, schedule, or publisher. Reels have their own table, schedule, routes,
and lifecycle so a Reel failure cannot block the proven feed-post lane.
"""
from __future__ import annotations

import hashlib
import hmac
import html
import json
import os
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from fastapi import HTTPException, Request
from fastapi.responses import HTMLResponse, Response

import v2_app as core

INGEST_TOKEN = os.getenv("HUNTER_OPERATOR_INGEST_TOKEN", "")
BASE_URL = os.getenv("EMPTY_CHAIR_BASE_URL", "https://app.tryemptychair.com").rstrip("/")
EASTERN = ZoneInfo("America/New_York")

# Exactly two Reels/day. GitHub may poll hourly; only these local hours become due.
REEL_SLOTS = {"morning": 10, "evening": 18}

REEL_TABLE = """CREATE TABLE IF NOT EXISTS growth_ig_reels (
    id TEXT PRIMARY KEY,
    local_day TEXT NOT NULL,
    slot TEXT NOT NULL,
    scenario_json TEXT NOT NULL,
    caption TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'PREPARED',
    video_bytes BYTEA,
    media_id TEXT,
    created_at TEXT NOT NULL,
    published_at TEXT,
    UNIQUE(local_day, slot)
)"""

# These stories are constrained to the actual Empty Chair recovery path: a calendar
# cancellation creates an opening, outreach is sent, a client claims, deposit/payment
# can be secured, and the recovered appointment returns to the calendar.
SCENARIOS = [
    {"kind":"same_day","artist":"Mara","client":"Jess","time":"3:00 PM","lead":"2 hours","deposit":80,"value":450,"hook":"3 PM JUST CANCELED.","reply":"I can take it."},
    {"kind":"tomorrow","artist":"Nico","client":"Sam","time":"11:30 AM","lead":"tomorrow","deposit":100,"value":600,"hook":"TOMORROW'S APPOINTMENT DISAPPEARED.","reply":"Yes — book me."},
    {"kind":"evening","artist":"Rae","client":"Taylor","time":"6:00 PM","lead":"4 hours","deposit":75,"value":350,"hook":"A 6 PM CANCELLATION JUST OPENED UP.","reply":"I'm free. I'll take it."},
    {"kind":"weekend","artist":"Alex","client":"Jordan","time":"1:00 PM","lead":"Saturday","deposit":120,"value":700,"hook":"SATURDAY OPENED UP.","reply":"Yes please."},
    {"kind":"short_notice","artist":"June","client":"Casey","time":"4:30 PM","lead":"90 minutes","deposit":60,"value":300,"hook":"90 MINUTES BEFORE THE APPOINTMENT.","reply":"I can be there."},
    {"kind":"high_value","artist":"Morgan","client":"Drew","time":"12:00 PM","lead":"tomorrow","deposit":150,"value":900,"hook":"A $900 SESSION CANCELED.","reply":"Send me the deposit link."},
]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _auth(request: Request) -> None:
    if not INGEST_TOKEN:
        raise HTTPException(503, "Reels ingest token is not configured")
    if not hmac.compare_digest(request.headers.get("authorization", ""), f"Bearer {INGEST_TOKEN}"):
        raise HTTPException(401, "Unauthorized")


def _init() -> None:
    db = core.DB()
    try:
        db.execute(REEL_TABLE)
        db.commit()
    finally:
        db.close()


def _local(now_utc: datetime | None = None):
    local = (now_utc or datetime.now(timezone.utc)).astimezone(EASTERN)
    return local, local.date().isoformat()


def _due_slot(now_utc: datetime | None = None):
    local, day = _local(now_utc)
    for slot, hour in REEL_SLOTS.items():
        if local.hour == hour:
            return slot, day
    return None, day


def _scenario(day: str, slot: str) -> dict:
    digest = hashlib.sha256(f"reel:{day}:{slot}".encode()).digest()
    return dict(SCENARIOS[int.from_bytes(digest[:4], "big") % len(SCENARIOS)])


def _caption(s: dict) -> str:
    return (
        f"{s['hook']} Empty Chair turns a canceled tattoo appointment back into an opening, "
        "reaches the next client, secures the spot, and gets the recovered appointment back on the calendar.\n\n"
        "7 DAYS FREE // LINK IN BIO\n\n#tattooartist #tattooshop #tattoocancellation #booksopen #emptychair"
    )


def _ensure(day: str, slot: str) -> dict:
    existing = core.one("SELECT * FROM growth_ig_reels WHERE local_day=? AND slot=?", (day, slot))
    if existing:
        return existing
    s = _scenario(day, slot)
    reel_id = "reel_" + hashlib.sha256(f"{day}:{slot}".encode()).hexdigest()[:20]
    core.run(
        "INSERT INTO growth_ig_reels(id,local_day,slot,scenario_json,caption,status,created_at) VALUES(?,?,?,?,?,?,?)",
        (reel_id, day, slot, json.dumps(s), _caption(s), "PREPARED", _now()),
    )
    return core.one("SELECT * FROM growth_ig_reels WHERE id=?", (reel_id,))


def _scene_shell(title: str, body: str, extra: str = "") -> str:
    return f"""<!doctype html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>
<style>*{{box-sizing:border-box}}html,body{{margin:0;width:1080px;height:1920px;overflow:hidden}}body{{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;background:#fff;color:#111}}.screen{{width:1080px;height:1920px;position:relative;overflow:hidden}}{extra}</style></head><body><main class='screen' aria-label='{html.escape(title)}'>{body}</main></body></html>"""


def _render_scene(s: dict, scene: int) -> str:
    # No decorative phone shell: each HTML document IS the 9:16 device screen.
    if scene == 0:
        body = f"<div class='hook'>{html.escape(s['hook'])}</div><div class='sub'>{html.escape(s['lead'])} before the opening.</div>"
        return _scene_shell("Hook", body, ".screen{background:#0B0905;color:#FFD36A;display:flex;flex-direction:column;justify-content:center;padding:100px}.hook{font:800 92px/1.02 'Courier New',monospace}.sub{margin-top:50px;font:34px/1.4 'Courier New',monospace;color:#FFB000}")
    if scene == 1:
        body = f"<div class='bar'>Messages <b>{html.escape(s['client'])}</b></div><div class='thread'><div class='bubble'>A tattoo opening just became available at {html.escape(s['time'])}. Want it?</div><div class='bubble me'>{html.escape(s['reply'])}</div></div><div class='composer'>iMessage</div>"
        return _scene_shell("Messages", body, ".screen{background:#f5f5f7}.bar{text-align:center;padding:72px 40px 28px;font-size:30px;border-bottom:1px solid #ddd}.thread{padding:70px 34px}.bubble{background:#e5e5ea;border-radius:34px;padding:22px 28px;font-size:34px;line-height:1.3;max-width:76%;margin:22px 0}.me{background:#0b84ff;color:white;margin-left:auto}.composer{position:absolute;bottom:54px;left:34px;right:34px;border:2px solid #d1d1d6;border-radius:30px;padding:18px 28px;color:#8e8e93;font-size:27px}")
    if scene == 2:
        body = f"<div class='brand'>EMPTY CHAIR</div><div class='label'>OPENING</div><div class='card'><b>{html.escape(s['time'])}</b><span>Recovery in progress</span><span>Client claimed opening</span></div><div class='label'>DEPOSIT</div><div class='money'>${int(s['deposit'])}</div>"
        return _scene_shell("Empty Chair recovery", body, ".screen{background:#0B0905;color:#FFB000;padding:100px 70px;font-family:'Courier New',monospace}.brand{font-size:34px;letter-spacing:.24em;margin-bottom:120px}.label{font-size:24px;letter-spacing:.18em;color:#805800;margin:48px 0 18px}.card{border:2px solid #332300;padding:38px;display:flex;flex-direction:column;gap:24px;font-size:32px}.card b{font-size:58px;color:#FFD36A}.money{font-size:96px;color:#FFD36A;font-weight:bold}")
    if scene == 3:
        body = f"<div class='calhead'>Calendar</div><div class='day'>TODAY</div><div class='hours'><div>11 AM</div><div>12 PM</div><div>1 PM</div><div>2 PM</div><div class='event'>{html.escape(s['time'])}<br><b>{html.escape(s['client'])}</b><br>Recovered appointment</div><div>5 PM</div><div>6 PM</div></div>"
        return _scene_shell("Calendar", body, ".screen{background:#fff;padding:70px 45px}.calhead{font-size:52px;font-weight:700}.day{margin:55px 0 28px;color:#d00;font-size:28px;font-weight:700}.hours{display:grid;gap:0;font-size:25px;color:#777}.hours>div{height:190px;border-top:1px solid #ddd;padding-top:12px}.event{margin-left:130px!important;margin-top:-10px;height:170px!important;border:0!important;border-left:8px solid #d00!important;background:#fff1f0;padding:18px!important;color:#222;border-radius:8px;font-size:28px}")
    body = f"<div class='done'>CHAIR FILLED.</div><div class='value'>${int(s['value'])} appointment recovered</div><div class='brand'>EMPTY CHAIR</div>"
    return _scene_shell("Result", body, ".screen{background:#0B0905;color:#FFD36A;display:flex;flex-direction:column;justify-content:center;align-items:center;text-align:center;padding:80px;font-family:'Courier New',monospace}.done{font-size:104px;font-weight:bold}.value{font-size:42px;color:#FFB000;margin-top:50px}.brand{position:absolute;bottom:110px;font-size:28px;letter-spacing:.25em;color:#805800}")


@core.app.post("/internal/instagram/reels/prepare")
def prepare_reel(request: Request):
    _auth(request)
    slot, day = _due_slot()
    if not slot:
        return {"ok": True, "due": False, "day": day}
    reel = _ensure(day, slot)
    if str(reel.get("status")) == "PUBLISHED":
        return {"ok": True, "due": True, "published": True, "id": reel["id"], "slot": slot}
    return {"ok": True, "due": True, "published": False, "id": reel["id"], "slot": slot,
            "scene_urls": [f"{BASE_URL}/instagram/reels/render/{reel['id']}/{n}" for n in range(5)],
            "upload_url": f"{BASE_URL}/internal/instagram/reels/video/{reel['id']}",
            "video_url": f"{BASE_URL}/instagram/reels/video/{reel['id']}.mp4"}


@core.app.get("/instagram/reels/render/{reel_id}/{scene}", response_class=HTMLResponse)
def render_reel_scene(reel_id: str, scene: int):
    reel = core.one("SELECT * FROM growth_ig_reels WHERE id=?", (reel_id,))
    if not reel or scene < 0 or scene > 4:
        raise HTTPException(404, "Not found")
    return HTMLResponse(_render_scene(json.loads(str(reel["scenario_json"])), scene))


@core.app.post("/internal/instagram/reels/video/{reel_id}")
async def upload_reel_video(reel_id: str, request: Request):
    _auth(request)
    reel = core.one("SELECT id FROM growth_ig_reels WHERE id=?", (reel_id,))
    if not reel:
        raise HTTPException(404, "Not found")
    body = await request.body()
    if not body or len(body) > 100_000_000:
        raise HTTPException(400, "Invalid video")
    core.run("UPDATE growth_ig_reels SET video_bytes=?,status='RENDERED' WHERE id=?", (body, reel_id))
    return {"ok": True, "id": reel_id, "bytes": len(body)}


@core.app.get("/instagram/reels/video/{reel_id}.mp4")
def reel_video(reel_id: str):
    reel = core.one("SELECT video_bytes FROM growth_ig_reels WHERE id=?", (reel_id,))
    if not reel or not reel.get("video_bytes"):
        raise HTTPException(404, "Not found")
    return Response(content=bytes(reel["video_bytes"]), media_type="video/mp4", headers={"Cache-Control":"public,max-age=86400"})


_init()
print("Instagram Reels engine loaded // isolated lane // 1080x1920 // 2/day", flush=True)
