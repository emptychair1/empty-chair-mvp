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
SCENE_COUNT = 10

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

SCENARIOS = [
    {"kind":"same_day","artist":"Mara","old_client":"Avery","client":"Jess","day":"TUE","time":"3:00 PM","duration":"3 hr","matches":12,"lead":"2 hours","deposit":80,"value":450,"hook":"3 PM JUST CANCELED."},
    {"kind":"tomorrow","artist":"Nico","old_client":"Morgan","client":"Sam","day":"WED","time":"11:30 AM","duration":"4 hr","matches":9,"lead":"tomorrow","deposit":100,"value":600,"hook":"TOMORROW'S APPOINTMENT DISAPPEARED."},
    {"kind":"evening","artist":"Rae","old_client":"Jamie","client":"Taylor","day":"THU","time":"6:00 PM","duration":"2 hr","matches":7,"lead":"4 hours","deposit":75,"value":350,"hook":"A 6 PM CANCELLATION JUST OPENED UP."},
    {"kind":"weekend","artist":"Alex","old_client":"Chris","client":"Jordan","day":"SAT","time":"1:00 PM","duration":"5 hr","matches":15,"lead":"Saturday","deposit":120,"value":700,"hook":"SATURDAY OPENED UP."},
    {"kind":"short_notice","artist":"June","old_client":"Riley","client":"Casey","day":"FRI","time":"4:30 PM","duration":"2 hr","matches":5,"lead":"90 minutes","deposit":60,"value":300,"hook":"90 MINUTES BEFORE THE APPOINTMENT."},
    {"kind":"high_value","artist":"Morgan","old_client":"Blake","client":"Drew","day":"SUN","time":"12:00 PM","duration":"6 hr","matches":11,"lead":"tomorrow","deposit":150,"value":900,"hook":"A $900 SESSION CANCELED."},
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
        f"{s['hook']} Watch the whole Empty Chair recovery: the calendar slot disappears, the bench goes to work, "
        "the next client gets the real offer, the deposit lands, and the appointment returns to the calendar.\n\n"
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


def _calendar_screen(s: dict, *, canceled: bool = False, recovered: bool = False) -> str:
    person = s.get("client") if recovered else s.get("old_client")
    title = "Recovered tattoo" if recovered else "Tattoo appointment"
    state = "RECOVERED" if recovered else ("CANCELED" if canceled else "BOOKED")
    event_class = "event recovered" if recovered else ("event canceled" if canceled else "event")
    body = f"""
    <div class='statusbar'><span>9:41</span><span>●●● 5G&nbsp;&nbsp;100%</span></div>
    <div class='top'><span class='red'>‹ Calendars</span><b>{html.escape(str(s.get('day','TUE')))}</b><span class='red'>＋</span></div>
    <div class='date'><div class='weekday'>{html.escape(str(s.get('day','TUE')))}</div><div class='num'>18</div></div>
    <div class='timeline'>
      <div class='hour'><span>11 AM</span></div><div class='hour'><span>12 PM</span></div><div class='hour'><span>1 PM</span></div><div class='hour'><span>2 PM</span></div>
      <div class='{event_class}'><b>{html.escape(str(person))} // {html.escape(title)}</b><span>{html.escape(str(s.get('time')))} · {html.escape(str(s.get('duration')))}</span><span>{_money(int(s.get('value',450)))}</span><strong>{state}</strong></div>
      <div class='hour'><span>4 PM</span></div><div class='hour'><span>5 PM</span></div><div class='hour'><span>6 PM</span></div>
    </div>
    <div class='note'>{'THE SLOT IS BACK ON THE CALENDAR' if recovered else ('THE ORIGINAL APPOINTMENT IS DELETED' if canceled else 'THE ORIGINAL APPOINTMENT EXISTS')}</div>
    """
    css = """
    .screen{background:#fff;color:#111}.statusbar{height:66px;padding:24px 38px 0;display:flex;justify-content:space-between;font-size:22px;font-weight:600}.top{height:110px;padding:28px 34px;display:grid;grid-template-columns:1fr 1fr 1fr;align-items:center;border-bottom:1px solid #ddd;font-size:28px}.top b{text-align:center}.top span:last-child{text-align:right}.red{color:#ff3b30}.date{text-align:center;padding:38px 0 22px}.weekday{font-size:23px;color:#ff3b30;font-weight:700}.num{font-size:64px;font-weight:300}.timeline{position:relative;padding:0 28px}.hour{height:180px;border-top:1px solid #ddd;color:#8e8e93;font-size:21px;padding-top:10px}.event{position:absolute;top:565px;left:145px;right:40px;height:170px;background:#ffd7d3;border-left:8px solid #ff3b30;border-radius:8px;padding:20px 24px;display:flex;flex-direction:column;gap:9px;font-size:25px}.event strong{font-size:18px;color:#ff3b30;letter-spacing:.12em}.event.canceled{opacity:.28;text-decoration:line-through;background:#eee;border-left-color:#aaa}.event.recovered{background:#d9ecff;border-left-color:#0a84ff;text-decoration:none;opacity:1}.event.recovered strong{color:#0a84ff}.note{position:absolute;bottom:70px;left:0;right:0;text-align:center;font:700 19px/1 ui-monospace,SFMono-Regular,Menlo,monospace;letter-spacing:.09em;color:#8e8e93}
    """
    return _scene_shell("Calendar recovery", body, css)


def _offer_screen(s: dict) -> str:
    body = f"""
    <header><span>EMPTY CHAIR</span><span>2.0</span></header>
    <div class='center'><h1>{html.escape(str(s.get('artist','Mara')).upper())}<br>HAS AN OPENING.</h1><div class='space'></div>
    <p class='big'>{html.escape(_when(s))}</p><p>{html.escape(str(s.get('duration','3 hr')))}</p><p>{_money(int(s.get('value',450)))}</p>
    <div class='space'></div><p class='dim'>DEPOSIT</p><p class='big'>{_money(int(s.get('deposit',80)))}</p>
    <div class='button'>TAKE THE CHAIR</div></div>
    """
    css = """
    .screen{background:#0B0905;color:#FFB000;padding:70px 55px;font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace}header{display:flex;justify-content:space-between;border-bottom:1px solid #332300;padding-bottom:20px;font-size:20px;letter-spacing:.08em}.center{text-align:center;padding-top:210px}h1{font-size:54px;font-weight:400;line-height:1.2;color:#FFD36A}.big{font-size:66px;color:#FFD36A;margin:20px 0}.dim{color:#805800;font-size:23px;letter-spacing:.15em}.space{height:55px}.center>p{font-size:34px}.button{margin-top:80px;border:2px solid #FFB000;padding:28px 18px;color:#FFD36A;font-size:30px}
    """
    return _scene_shell("Actual Empty Chair offer", body, css)


def _payment_screen(s: dict) -> str:
    body = f"""
    <header><span>EMPTY CHAIR</span><span>2.0</span></header>
    <div class='center'><h1>LOCK IT IN.</h1><p class='amount'>{_money(int(s.get('deposit',80)))}</p><p class='dim'>applied to your tattoo.</p></div>
    <div class='stack'><div class='cash'>Cash App Pay</div><div class='card'>CARD</div><div class='venmo'>VENMO</div></div>
    <div class='note'>ONLY PAYMENT METHODS THE ARTIST HAS CONFIGURED ARE SHOWN</div>
    """
    css = """
    .screen{background:#0B0905;color:#FFB000;padding:70px 55px;font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace}header{display:flex;justify-content:space-between;border-bottom:1px solid #332300;padding-bottom:20px;font-size:20px;letter-spacing:.08em}.center{text-align:center;padding-top:210px}h1{font-size:58px;font-weight:400;color:#FFD36A}.amount{font-size:108px;color:#FFD36A;margin:65px 0 20px}.dim{color:#805800;font-size:24px}.stack{display:grid;gap:28px;margin-top:150px}.stack div{border:2px solid #FFB000;padding:30px;text-align:center;font-size:30px;color:#FFD36A}.note{position:absolute;bottom:80px;left:60px;right:60px;text-align:center;font-size:18px;color:#805800;letter-spacing:.08em;line-height:1.5}
    """
    return _scene_shell("Payment options", body, css)


def _square_screen(s: dict) -> str:
    deposit = _money(int(s.get('deposit',80)))
    body = f"""
    <div class='sqtop'><div class='logo'>■</div><b>Square</b><span>•••</span></div>
    <div class='balance'><span>Available balance</span><strong>{deposit}</strong></div>
    <div class='activity'><h2>Activity</h2><div class='row'><div><b>Empty Chair deposit</b><span>{html.escape(str(s.get('client','Jess')))} · {html.escape(str(s.get('time','3:00 PM')))}</span></div><strong>+{deposit}</strong></div></div>
    <div class='settled'>Payment completed</div>
    <div class='note'>THE DEPOSIT LANDS IN THE ARTIST'S SQUARE ACCOUNT</div>
    """
    css = """
    .screen{background:#f7f7f7;color:#222;padding:0 42px}.sqtop{height:130px;display:grid;grid-template-columns:70px 1fr 70px;align-items:center;border-bottom:1px solid #ddd;font-size:30px}.sqtop span{text-align:right}.logo{width:42px;height:42px;border:5px solid #111;display:grid;place-items:center;font-size:12px}.balance{margin-top:95px;background:white;border-radius:22px;padding:42px;display:flex;flex-direction:column;gap:20px;box-shadow:0 2px 12px rgba(0,0,0,.08)}.balance span{font-size:25px;color:#666}.balance strong{font-size:86px}.activity{margin-top:60px}.activity h2{font-size:32px}.row{margin-top:20px;background:white;border-radius:18px;padding:32px;display:flex;justify-content:space-between;align-items:center}.row div{display:flex;flex-direction:column;gap:10px}.row b{font-size:28px}.row span{font-size:22px;color:#777}.row>strong{font-size:30px;color:#1d7f3f}.settled{margin-top:45px;text-align:center;font-size:24px;color:#1d7f3f}.note{position:absolute;bottom:85px;left:45px;right:45px;text-align:center;font:700 19px/1.4 ui-monospace,SFMono-Regular,Menlo,monospace;letter-spacing:.08em;color:#777}
    """
    return _scene_shell("Square deposit", body, css)


def _render_scene(s: dict, scene: int) -> str:
    when = _when(s)
    value = _money(int(s.get("value", 450)))
    deposit = _money(int(s.get("deposit", 80)))
    artist = str(s.get("artist", "Mara"))
    client = str(s.get("client", "Jess"))
    matches = int(s.get("matches", 12))
    duration = str(s.get("duration", "3 hr"))

    if scene == 0:
        return _calendar_screen(s, canceled=False, recovered=False)

    if scene == 1:
        return _calendar_screen(s, canceled=True, recovered=False)

    if scene == 2:
        message = (
            "EMPTY CHAIR // OPEN\n\n"
            f"{when} canceled.\n\n"
            f"{value} AT RISK\n\n"
            f"bench........{matches} ready [✓]\n"
            "working................[✓]"
        )
        return _sms_screen("ARTIST PHONE // CANCELLATION DETECTED", message, "THE ARTIST KNOWS WHAT IS AT RISK AND THAT EMPTY CHAIR IS WORKING IT")

    if scene == 3:
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
        return _sms_screen("CLIENT PHONE // TOP MATCH", message, "THE CLIENT GETS THE REAL EMPTY CHAIR OFFER TEXT")

    if scene == 4:
        return _offer_screen(s)

    if scene == 5:
        return _payment_screen(s)

    if scene == 6:
        return _square_screen(s)

    if scene == 7:
        return _calendar_screen(s, canceled=False, recovered=True)

    if scene == 8:
        message = (
            "EMPTY CHAIR // FILLED ✓\n\n"
            f"{client} took {when}.\n\n"
            f"deposit........{deposit} [✓]\n"
            "calendar.................[✓]\n\n"
            f"{value} SAVED"
        )
        return _sms_screen("ARTIST PHONE // RECOVERY COMPLETE", message, "THE ARTIST GETS THE RECOVERY RECEIPT")

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
    return {
        "ok": True,
        "due": True,
        "published": False,
        "id": reel["id"],
        "slot": slot,
        "scene_urls": [f"{BASE_URL}/instagram/reels/render/{reel['id']}/{n}" for n in range(SCENE_COUNT)],
        "upload_url": f"{BASE_URL}/internal/instagram/reels/video/{reel['id']}",
        "video_url": f"{BASE_URL}/instagram/reels/video/{reel['id']}.mp4",
    }


@core.app.get("/instagram/reels/render/{reel_id}/{scene}", response_class=HTMLResponse)
def render_reel_scene(reel_id: str, scene: int):
    reel = core.one("SELECT * FROM growth_ig_reels WHERE id=?", (reel_id,))
    if not reel or scene < 0 or scene >= SCENE_COUNT:
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
    return Response(content=bytes(reel["video_bytes"]), media_type="video/mp4", headers={"Cache-Control": "public,max-age=86400"})


_init()
print("Instagram Reels engine loaded // isolated lane // 1080x1920 // 10-scene recovery story // 2/day", flush=True)
