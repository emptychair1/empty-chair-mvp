"""Automatic Empty Chair CRT feed-post generator + publisher.

The app owns the message, styling, post state, image hosting, and Meta publish call.
GitHub Actions only acts as the headless clock/browser: it screenshots the real HTML
render, uploads that JPEG back to the app, then tells the app to publish it.
"""
from __future__ import annotations

import hashlib
import hmac
import html
import os
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from fastapi import HTTPException, Request
from fastapi.responses import HTMLResponse, Response

import v2_app as core
import v2_instagram_growth as growth
import v2_instagram_publisher as publisher

INGEST_TOKEN = os.getenv("HUNTER_OPERATOR_INGEST_TOKEN", "")
BASE_URL = os.getenv("EMPTY_CHAIR_BASE_URL", "https://app.tryemptychair.com").rstrip("/")
EASTERN = ZoneInfo("America/New_York")

POST_TABLE = """CREATE TABLE IF NOT EXISTS growth_crt_posts (
    id TEXT PRIMARY KEY,
    local_day TEXT NOT NULL,
    slot TEXT NOT NULL,
    message TEXT NOT NULL,
    ornament TEXT NOT NULL,
    caption TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'PREPARED',
    image_bytes BYTEA,
    media_id TEXT,
    created_at TEXT NOT NULL,
    published_at TEXT,
    UNIQUE(local_day, slot)
)"""

SLOTS = {
    "morning": 9,
    "afternoon": 14,
    "evening": 19,
}

INTRO_MESSAGES = [
    "CANCELLATION -> OPENING\nOPENING -> FILLED\n\n7-DAY FREE TRIAL\nNO CARD REQUIRED",
    "NO NEW SOFTWARE.\nNO NEW WORKFLOW.\nHEADLESS.\n\n7-DAY FREE TRIAL\nNO CARD REQUIRED",
    "RECOVER ONE SPOT.\nIT CAN PAY FOR\nEMPTY CHAIR.\n\n7-DAY FREE TRIAL\nNO CARD REQUIRED",
    "A CANCELLATION\nDOESN'T HAVE TO\nSTAY EMPTY.\n\n7-DAY FREE TRIAL\nNO CARD REQUIRED",
    "CALENDAR CHANGES.\nEMPTY CHAIR REACTS.\nTHE GAP GETS FILLED.\n\n7-DAY FREE TRIAL\nNO CARD REQUIRED",
    "WHEN THEY CANCEL,\nWE HELP FILL\nTHE CHAIR.\n\n7-DAY FREE TRIAL\nNO CARD REQUIRED",
]

MESSAGES = [
    "A CANCELLATION\nDOESN'T HAVE TO\nSTAY EMPTY.\n\n7-DAY FREE TRIAL",
    "NO NEW SOFTWARE.\nNO NEW WORKFLOW.\nHEADLESS.\n\n7-DAY FREE TRIAL",
    "RECOVER ONE SPOT.\nIT CAN PAY FOR\nEMPTY CHAIR.\n\n7-DAY FREE TRIAL",
    "THE CHAIR OPENED.\nFILL IT BEFORE\nTHE DAY IS GONE.\n\n7-DAY FREE TRIAL",
    "WHEN THEY CANCEL,\nEMPTY CHAIR GETS\nTO WORK.\n\n7-DAY FREE TRIAL",
    "EMPTY TIME\nDOESN'T HAVE TO BE\nLOST REVENUE.\n\n7-DAY FREE TRIAL",
    "ONE OPENING.\nONE RECOVERED CLIENT.\nONE LESS EMPTY CHAIR.\n\n7-DAY FREE TRIAL",
    "YOUR CALENDAR\nCHANGED.\nYOUR INCOME DOESN'T\nHAVE TO.\n\n7-DAY FREE TRIAL",
    "HEADLESS RECOVERY.\nNO DASHBOARD TO BABYSIT.\n\n7-DAY FREE TRIAL",
    "CANCELED -> OPEN.\nOPEN -> FILLED.\n\n7-DAY FREE TRIAL",
    "STOP LETTING\nCANCELLATIONS DECIDE\nYOUR PAYCHECK.\n\n7-DAY FREE TRIAL",
    "FILL THE GAP.\nRECOVER THE DAY.\n\n7-DAY FREE TRIAL",
]

ORNAMENTS = [
    "================================",
    ">>----------------------------<<",
    "+------------------------------+",
    ":: :: :: :: :: :: :: :: :: ::",
    "[==============================]",
    "<><><><><><><><><><><><><><>",
    "//----------------------------\\\\",
    "....::::....::::....::::....",
]

HASHTAGS = (
    "#tattooartist #tattooshop #tattoostudio #tattoobusiness "
    "#tattooappointments #tattoocancellation #tattooavailability "
    "#booksopen #tattooindustry #emptychair"
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _auth(request: Request) -> None:
    if not INGEST_TOKEN:
        raise HTTPException(503, "Autopilot token is not configured")
    supplied = request.headers.get("authorization", "")
    if not hmac.compare_digest(supplied, f"Bearer {INGEST_TOKEN}"):
        raise HTTPException(401, "Unauthorized")


def _init() -> None:
    db = core.DB()
    try:
        db.execute(POST_TABLE)
        db.commit()
    finally:
        db.close()


def _pick(values: list[str], day: str, slot: str, salt: str) -> str:
    digest = hashlib.sha256(f"{day}:{slot}:{salt}".encode()).digest()
    return values[int.from_bytes(digest[:4], "big") % len(values)]


def _local_day(now_utc: datetime | None = None) -> tuple[datetime, str]:
    local = (now_utc or datetime.now(timezone.utc)).astimezone(EASTERN)
    return local, local.date().isoformat()


def _due_slot(now_utc: datetime | None = None) -> tuple[str | None, str]:
    local, day = _local_day(now_utc)
    for slot, hour in SLOTS.items():
        if local.hour == hour:
            return slot, day
    return None, day


def _caption(message: str) -> str:
    readable = " ".join(line.strip() for line in message.splitlines() if line.strip())
    return (
        f"{readable}\n\n"
        "Empty Chair recovers canceled tattoo appointments in the background. "
        "No new software to babysit. No new workflow to manage. One recovered spot can cover the cost.\n\n"
        "7-DAY FREE TRIAL // NO CARD REQUIRED // LINK IN BIO\n\n"
        f"{HASHTAGS}"
    )


def _intro_published_count() -> int:
    row = core.one("SELECT COUNT(*) AS n FROM growth_crt_posts WHERE slot LIKE 'intro-%' AND status='PUBLISHED'") or {"n": 0}
    return int(row.get("n") or 0)


def _next_intro(day: str) -> dict | None:
    # Finish any already-prepared intro first so retries never skip or duplicate a post.
    pending = core.one(
        "SELECT * FROM growth_crt_posts WHERE slot LIKE 'intro-%' AND status!='PUBLISHED' ORDER BY slot ASC LIMIT 1"
    )
    if pending:
        return pending
    index = _intro_published_count()
    if index >= len(INTRO_MESSAGES):
        return None
    slot = f"intro-{index + 1:02d}"
    message = INTRO_MESSAGES[index]
    ornament = ORNAMENTS[index % len(ORNAMENTS)]
    post_id = "crt_intro_" + hashlib.sha256(slot.encode()).hexdigest()[:16]
    core.run(
        "INSERT INTO growth_crt_posts(id,local_day,slot,message,ornament,caption,status,created_at) VALUES(?,?,?,?,?,?,?,?)",
        (post_id, day, slot, message, ornament, _caption(message), "PREPARED", _now()),
    )
    return core.one("SELECT * FROM growth_crt_posts WHERE id=?", (post_id,))


def _ensure_post(day: str, slot: str) -> dict:
    existing = core.one("SELECT * FROM growth_crt_posts WHERE local_day=? AND slot=?", (day, slot))
    if existing:
        return existing
    message = _pick(MESSAGES, day, slot, "message")
    ornament = _pick(ORNAMENTS, day, slot, "ornament")
    post_id = "crt_" + hashlib.sha256(f"{day}:{slot}".encode()).hexdigest()[:20]
    core.run(
        "INSERT INTO growth_crt_posts(id,local_day,slot,message,ornament,caption,status,created_at) VALUES(?,?,?,?,?,?,?,?)",
        (post_id, day, slot, message, ornament, _caption(message), "PREPARED", _now()),
    )
    return core.one("SELECT * FROM growth_crt_posts WHERE id=?", (post_id,))


def _render(post: dict) -> str:
    message = html.escape(str(post.get("message") or ""))
    ornament = html.escape(str(post.get("ornament") or ""))
    return f"""<!doctype html>
<html><head><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">
<style>
*{{box-sizing:border-box}}html,body{{margin:0;width:1080px;height:1080px;overflow:hidden;background:#0B0905}}
body{{position:relative;display:grid;place-items:center;color:#ffb000;font-family:'Courier New',Courier,monospace;text-shadow:0 0 4px rgba(255,176,0,.7),0 0 13px rgba(255,176,0,.22)}}
body:before{{content:'';position:absolute;inset:0;pointer-events:none;background:repeating-linear-gradient(to bottom,rgba(255,176,0,.055) 0,rgba(255,176,0,.055) 2px,transparent 2px,transparent 6px);opacity:.72}}
body:after{{content:'';position:absolute;inset:0;pointer-events:none;background:radial-gradient(ellipse at center,transparent 54%,rgba(0,0,0,.34) 100%)}}
.screen{{width:88%;text-align:center;position:relative;z-index:2;transform:translateY(-8px)}}
.brand{{font-size:27px;letter-spacing:.28em;margin-bottom:64px;opacity:.78}}.orn{{font-size:27px;letter-spacing:.05em;white-space:pre;margin:34px 0;color:#e69e00}}
.msg{{white-space:pre-line;font-weight:700;font-size:68px;line-height:1.18;letter-spacing:.025em;color:#ffc04a;text-shadow:0 0 5px rgba(255,192,74,.8),0 0 18px rgba(255,176,0,.28)}}
.footer{{font-size:22px;letter-spacing:.17em;margin-top:66px;opacity:.67}}
</style></head><body><div class=\"screen\"><div class=\"brand\">EMPTY CHAIR // RECOVERY SYSTEM</div><div class=\"orn\">{ornament}</div><div class=\"msg\">{message}</div><div class=\"orn\">{ornament}</div><div class=\"footer\">TRYEMPTYCHAIR.COM</div></div></body></html>"""


def _prepared_payload(post: dict, *, bootstrap: bool) -> dict:
    if str(post.get("status")) == "PUBLISHED":
        return {"ok": True, "due": True, "published": True, "slot": post["slot"], "id": post["id"], "bootstrap": bootstrap}
    return {
        "ok": True,
        "due": True,
        "published": False,
        "slot": post["slot"],
        "id": post["id"],
        "bootstrap": bootstrap,
        "render_url": f"{BASE_URL}/instagram/autopilot/render/{post['id']}",
        "image_url": f"{BASE_URL}/instagram/autopilot/image/{post['id']}.jpg",
    }


@core.app.post("/internal/instagram/autopilot/prepare")
def prepare(request: Request):
    _auth(request)
    _, day = _local_day()

    # Bootstrap the profile first. Until all six intro posts are live, every hourly
    # autopilot run publishes the next intro post. Then the system automatically
    # falls back to the normal 3-post/day schedule.
    intro = _next_intro(day)
    if intro:
        return _prepared_payload(intro, bootstrap=True)

    slot, day = _due_slot()
    if not slot:
        return {"ok": True, "due": False, "day": day, "bootstrap": False}
    return _prepared_payload(_ensure_post(day, slot), bootstrap=False)


@core.app.get("/instagram/autopilot/render/{post_id}", response_class=HTMLResponse)
def render(post_id: str):
    post = core.one("SELECT * FROM growth_crt_posts WHERE id=?", (post_id,))
    if not post:
        raise HTTPException(404, "Not found")
    return HTMLResponse(_render(post))


@core.app.post("/internal/instagram/autopilot/image/{post_id}")
async def upload_image(post_id: str, request: Request):
    _auth(request)
    post = core.one("SELECT id,status FROM growth_crt_posts WHERE id=?", (post_id,))
    if not post:
        raise HTTPException(404, "Not found")
    body = await request.body()
    if not body or len(body) > 5_000_000:
        raise HTTPException(400, "Invalid image")
    core.run("UPDATE growth_crt_posts SET image_bytes=?,status=? WHERE id=?", (body, "RENDERED", post_id))
    return {"ok": True, "id": post_id, "bytes": len(body)}


@core.app.get("/instagram/autopilot/image/{post_id}.jpg")
def image(post_id: str):
    post = core.one("SELECT image_bytes FROM growth_crt_posts WHERE id=?", (post_id,))
    if not post or not post.get("image_bytes"):
        raise HTTPException(404, "Not found")
    return Response(content=bytes(post["image_bytes"]), media_type="image/jpeg", headers={"Cache-Control": "public,max-age=86400"})


@core.app.post("/internal/instagram/autopilot/publish/{post_id}")
def publish(post_id: str, request: Request):
    _auth(request)
    post = core.one("SELECT * FROM growth_crt_posts WHERE id=?", (post_id,))
    if not post:
        raise HTTPException(404, "Not found")
    if str(post.get("status")) == "PUBLISHED":
        return {"ok": True, "published": False, "reason": "already_published", "media_id": post.get("media_id")}
    if not post.get("image_bytes"):
        raise HTTPException(409, "Image has not been rendered")
    if not (growth.META_TOKEN and growth.IG_USER_ID):
        raise HTTPException(503, "Instagram publishing credentials are not configured")

    image_url = f"{BASE_URL}/instagram/autopilot/image/{post_id}.jpg"
    created = publisher._post(f"{growth.IG_USER_ID}/media", {"image_url": image_url, "caption": str(post["caption"])})
    creation_id = str(created.get("id") or "")
    if not creation_id:
        raise HTTPException(502, f"Instagram media container failed: {created}")
    publisher._wait_ready(creation_id)
    result = publisher._post(f"{growth.IG_USER_ID}/media_publish", {"creation_id": creation_id})
    media_id = str(result.get("id") or "")
    if not media_id:
        raise HTTPException(502, f"Instagram publish failed: {result}")

    core.run(
        "UPDATE growth_crt_posts SET status='PUBLISHED',media_id=?,published_at=? WHERE id=?",
        (media_id, _now(), post_id),
    )
    core.event("growth.instagram_crt_autopilot_published", None, {"post_id": post_id, "media_id": media_id, "slot": post["slot"]})
    return {"ok": True, "published": True, "media_id": media_id, "slot": post["slot"]}


_init()
print("Empty Chair CRT Instagram autopilot loaded // 6 intro posts then 3 feed posts/day", flush=True)
