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

# Scenario values change, but every message below is rendered from the same successful
# production recovery path that Empty Chair actually sends: artist OPEN -> client OPEN
# -> deposit/booking -> artist FILLED + client YOURS.
SCENARIOS = [
    {"kind":"same_day","artist":"Mara","client":"Jess","day":"TUE","time":"3:00 PM","duration":"3 hr","matches":12,"lead":"2 hours","deposit":80,"value":450,"hook":"3 PM JUST CANCELED."},
    {"kind":"tomorrow","artist":"Nico","client":"Sam","day":"WED","time":"11:30 AM","duration":"4 hr","matches":9,"lead":"tomorrow","deposit":100,"value":600,"hook":"TOMORROW'S APPOINTMENT DISAPPEARED."},
    {"kind":"evening","artist":"Rae","client":"Taylor","day":"THU","time":"6:00 PM","duration":"2 hr","matches":7,"lead":"4 hours","deposit":75,"value":350,"hook":"A 6 PM CANCELLATION JUST OPENED UP."},
    {"kind":"weekend","artist":"Alex","client":"Jordan","day":"SAT","time":"1:00 PM","duration":"5 hr","matches":15,"lead":"Saturday","deposit":120,"value":700,"hook":"SATURDAY OPENED UP."},
    {"kind":"short_notice","artist":"June","client":"Casey","day":"FRI","time":"4:30 PM","duration":"2 hr","matches":5,"lead":"90 minutes","deposit":60,"value":300,"hook":"90 MINUTES BEFORE THE APPOINTMENT."},
    {"kind":"high_value","artist":"Morgan","client":"Drew","day":"SUN","time":"12:00 PM","duration":"6 hr","matches":11,"lead":"tomorrow","deposit":150,"value":900,"hook":"A $900 SESSION CANCELED."},
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
        f"{s['hook']} This is the actual Empty Chair text flow: the artist gets the cancellation alert, "
        "the next client gets the opening, the deposit lands, and both sides get confirmation.\n\n"
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


def _money(value: int) -> str:
    return f"${int(value):,}"


def _when(s: dict) -> str:
    return f"{s.get('day', 'TUE')} // {s.get('time', '3:00 PM')}"


def _sms_screen(audience: str, message: str, note: str) -> str:
    escaped = html.escape(message)
    body = f"""
    <div class='statusbar'><span>9:41</span><span>●●● 5G&nbsp;&nbsp;100%</span></div>
    <div class='nav'><span class='back'>‹</span><div><div class='avatar'>EC</div><div class='name'>Empty Chair</div></div><span></span></div>
    <div class='audience'>{html.escape(audience)}</div>
    <div class='thread'><div class='bubble'><pre>{escaped}</pre></div><div class='delivered'>Delivered</div></div>
    <div class='composer'><span>＋</span><div>iMessage</div><span>🎙</span></div>
    <div class='reel-note'>{html.escape(note)}</div>
    """
    css = """
    .screen{background:#f5f5f7;color:#111}.statusbar{height:66px;padding:24px 38px 0;display:flex;justify-content:space-between;font-size:22px;font-weight:600}.nav{height:138px;border-bottom:1px solid #d8d8dc;display:grid;grid-template-columns:90px 1fr 90px;align-items:center;text-align:center;background:rgba(249,249,249,.96)}.back{font-size:64px;color:#087cff;font-weight:300}.avatar{width:70px;height:70px;border-radius:50%;background:#0B0905;color:#FFD36A;margin:0 auto 6px;display:grid;place-items:center;font:700 23px/1 ui-monospace,SFMono-Regular,Menlo,monospace}.name{font-size:21px}.audience{position:absolute;top:226px;left:0;right:0;text-align:center;font:700 19px/1.2 ui-monospace,SFMono-Regular,Menlo,monospace;letter-spacing:.15em;color:#8e8e93}.thread{padding:105px 34px 220px}.bubble{background:#e5e5ea;border-radius:38px 38px 38px 10px;padding:30px 32px;max-width:88%;display:inline-block}.bubble pre{margin:0;white-space:pre-wrap;word-break:break-word;font:31px/1.34 ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;color:#111}.delivered{font-size:18px;color:#8e8e93;margin:8px 0 0 18px}.composer{position:absolute;bottom:52px;left:28px;right:28px;height:62px;display:grid;grid-template-columns:56px 1fr 56px;gap:10px;align-items:center;color:#8e8e93;font-size:25px}.composer div{border:2px solid #c7c7cc;border-radius:34px;padding:13px 20px}.reel-note{position:absolute;bottom:138px;left:0;right:0;text-align:center;font:700 17px/1.2 ui-monospace,SFMono-Regular,Menlo,monospace;letter-spacing:.08em;color:#8e8e93}
    """
    return _scene_shell(f"{audience} text from Empty Chair", body, css)


def _render_scene(s: dict, scene: int) -> str:
    # These are the actual SMS templates used by the successful production recovery path.
    # We intentionally do not invent client replies: clients claim through the TAKE THE CHAIR link.
    when = _when(s)
    value = _money(int(s.get("value", 450)))
    deposit = _money(int(s.get("deposit", 80)))
    artist = str(s.get("artist", "Mara"))
    client = str(s.get("client", "Jess"))
    matches = int(s.get("matches", 12))
    duration = str(s.get("duration", "3 hr"))

    if scene == 0:
        message = (
            "EMPTY CHAIR // OPEN\n\n"
            f"{when} canceled.\n\n"
            f"{value} AT RISK\n\n"
            f"{matches} matches ready.\n\n"
            "working..."
        )
        return _sms_screen("ARTIST PHONE // CANCELLATION DETECTED", message, "THIS IS WHAT THE ARTIST ACTUALLY GETS")

    if scene == 1:
        message = (
            "EMPTY CHAIR // OPEN\n\n"
            f"{artist} has an opening.\n\n"
            f"{when}\n"
            f"{duration}\n"
            f"{value}\n\n"
            "+----------------------+\n"
            "|   TAKE THE CHAIR     |\n"
            "+----------------------+\n"
            f"{BASE_URL}/o/••••••••\n\n"
            f"held for {core.OFFER_MINUTES} min.\n\n"
            "Reply STOP to opt out."
        )
        return _sms_screen("CLIENT PHONE // TOP MATCH", message, "THE CLIENT CLAIMS THROUGH THE LINK — NO FAKE TEXT REPLY")

    if scene == 2:
        body = f"""
        <div class='brand'>EMPTY CHAIR</div>
        <div class='eyebrow'>CLIENT CLAIMS + PAYS DEPOSIT</div>
        <div class='ascii'>+----------------------+<br>|&nbsp;&nbsp;&nbsp;TAKE THE CHAIR&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;|<br>+----------------------+</div>
        <div class='pay'>{deposit}</div>
        <div class='copy'>Deposit is paid through the real Empty Chair claim flow.<br>No text reply is required.</div>
        <div class='arrow'>↓</div>
        <div class='copy bright'>EMPTY CHAIR BOOKS THE SLOT<br>AND SENDS BOTH CONFIRMATIONS.</div>
        """
        return _scene_shell(
            "Claim and deposit",
            body,
            ".screen{background:#0B0905;color:#FFB000;padding:110px 78px;text-align:center;font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace}.brand{font-size:27px;letter-spacing:.25em;text-align:left}.eyebrow{margin-top:240px;font-size:26px;letter-spacing:.08em;color:#805800}.ascii{margin-top:70px;font-size:38px;line-height:1.38;color:#FFD36A}.pay{font-size:104px;font-weight:700;color:#FFD36A;margin-top:75px}.copy{font-size:28px;line-height:1.55;margin-top:38px}.arrow{font-size:68px;margin:70px 0 30px}.bright{color:#FFD36A}"
        )

    if scene == 3:
        message = (
            "EMPTY CHAIR // FILLED ✓\n\n"
            f"{client} took {when}.\n\n"
            f"deposit........{deposit} [✓]\n"
            "calendar.................[✓]\n\n"
            f"{value} SAVED"
        )
        return _sms_screen("ARTIST PHONE // RECOVERY COMPLETE", message, "THE ARTIST GETS THE RECEIPT")

    message = (
        "EMPTY CHAIR // YOURS\n\n"
        "+----------------------+\n"
        "|     TAKE A SEAT.     |\n"
        "+----------------------+\n\n"
        f"{artist}\n"
        f"{when}\n\n"
        f"deposit..........{deposit} [✓]\n"
        "appointment...........[✓]\n\n"
        "You're booked."
    )
    return _sms_screen("CLIENT PHONE // BOOKING CONFIRMED", message, "THE CLIENT GETS THE FINAL CONFIRMATION")


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
print("Instagram Reels engine loaded // exact production SMS exchange // 1080x1920 // 2/day", flush=True)
