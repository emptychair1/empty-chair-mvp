"""Empty Chair Instagram growth loop.

Official Meta surfaces only: ingest comments on Empty Chair media, privately reply to
opt-in CTA comments, attribute trial starts, and keep running through revenue milestones.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import threading
import time
import urllib.parse
import urllib.request
import uuid
from datetime import datetime, timezone

import v2_app as core
from fastapi import Request
from fastapi.responses import JSONResponse, RedirectResponse, Response

META_TOKEN = os.getenv("INSTAGRAM_ACCESS_TOKEN", "").strip()
IG_USER_ID = os.getenv("INSTAGRAM_USER_ID", "").strip()
VERIFY_TOKEN = os.getenv("INSTAGRAM_WEBHOOK_VERIFY_TOKEN", "EC-CHAIR-VERIFY-7Q4K9M2X").strip()
APP_SECRET = os.getenv("META_APP_SECRET", "").strip()
GRAPH_VERSION = os.getenv("META_GRAPH_VERSION", "v24.0").strip()
TARGET_MRR_CENTS = int(os.getenv("EMPTY_CHAIR_GROWTH_TARGET_MRR_CENTS", "100000"))
CTA_WORDS = {x.strip().lower() for x in os.getenv("EMPTY_CHAIR_IG_CTA_WORDS", "chair,empty").split(",") if x.strip()}
WORKER_SECONDS = max(300, int(os.getenv("EMPTY_CHAIR_GROWTH_WORKER_SECONDS", "3600")))

SCHEMA = [
    """CREATE TABLE IF NOT EXISTS growth_instagram_leads (
        id TEXT PRIMARY KEY, ig_user_id TEXT NOT NULL, username TEXT, comment_id TEXT UNIQUE NOT NULL,
        media_id TEXT, keyword TEXT, token TEXT UNIQUE NOT NULL, status TEXT NOT NULL DEFAULT 'COMMENTED',
        artist_id TEXT, created_at TEXT NOT NULL, replied_at TEXT, clicked_at TEXT, trial_at TEXT, paid_at TEXT
    )""",
    """CREATE TABLE IF NOT EXISTS growth_instagram_events (
        id TEXT PRIMARY KEY, lead_id TEXT, kind TEXT NOT NULL, payload TEXT NOT NULL, created_at TEXT NOT NULL
    )""",
]


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def init():
    d = core.DB()
    try:
        for stmt in SCHEMA:
            d.execute(stmt)
        d.commit()
    finally:
        d.close()


def log(lead_id: str | None, kind: str, payload: dict):
    core.run("INSERT INTO growth_instagram_events(id,lead_id,kind,payload,created_at) VALUES(?,?,?,?,?)",
             (str(uuid.uuid4()), lead_id, kind, json.dumps(payload, separators=(",", ":")), now()))


def current_mrr_cents() -> int:
    for q in (
        "SELECT COUNT(*) AS n FROM artists WHERE subscription_status='active'",
        "SELECT COUNT(*) AS n FROM artists WHERE subscription_status IN ('active','ACTIVE')",
    ):
        try:
            row = core.one(q)
            return int((row or {}).get("n") or 0) * 9700
        except Exception:
            continue
    return 0


def growth_live() -> bool:
    # Milestones are reporting checkpoints, never shutdown conditions.
    return True


def graph_post(path: str, form: dict[str, str]) -> dict:
    data = urllib.parse.urlencode({**form, "access_token": META_TOKEN}).encode()
    req = urllib.request.Request(f"https://graph.facebook.com/{GRAPH_VERSION}/{path.lstrip('/')}", data=data, method="POST")
    with urllib.request.urlopen(req, timeout=30) as r:
        raw = r.read().decode()
        return json.loads(raw) if raw else {}


def private_reply(comment_id: str, text: str) -> bool:
    if not META_TOKEN:
        print(f"[IG growth disabled] reply {comment_id}: {text}", flush=True)
        return False
    try:
        graph_post(f"{IG_USER_ID}/messages", {"recipient": json.dumps({"comment_id": comment_id}), "message": json.dumps({"text": text})})
        return True
    except Exception as exc:
        print(f"IG private reply failed: {exc}", flush=True)
        return False


def handle_comment(value: dict):
    if not growth_live():
        return
    comment_id = str(value.get("id") or value.get("comment_id") or "")
    text = str(value.get("text") or "").strip()
    sender = value.get("from") or {}
    sender_id = str(sender.get("id") or value.get("from_id") or "")
    username = str(sender.get("username") or value.get("username") or "")
    media = value.get("media") or {}
    media_id = str(media.get("id") or value.get("media_id") or "")
    words = {w.strip(".,!?;:#@()[]{}\"'").lower() for w in text.split()}
    keyword = next((w for w in CTA_WORDS if w in words), "")
    if not (comment_id and sender_id and keyword):
        return
    if core.one("SELECT id FROM growth_instagram_leads WHERE comment_id=?", (comment_id,)):
        return
    lead_id, token = str(uuid.uuid4()), secrets.token_urlsafe(18)
    core.run("INSERT INTO growth_instagram_leads(id,ig_user_id,username,comment_id,media_id,keyword,token,status,created_at) VALUES(?,?,?,?,?,?,?,?,?)",
             (lead_id, sender_id, username, comment_id, media_id, keyword, token, "COMMENTED", now()))
    url = f"{core.BASE_URL}/ig/{token}"
    text_out = f"WHEN THEY CANCEL, WE FILL THE CHAIR.\n\nTry Empty Chair free for 7 days:\n{url}"
    ok = private_reply(comment_id, text_out)
    core.run("UPDATE growth_instagram_leads SET status=?,replied_at=? WHERE id=?", ("REPLIED" if ok else "REPLY_FAILED", now() if ok else None, lead_id))
    log(lead_id, "instagram.private_reply", {"ok": ok, "media_id": media_id, "keyword": keyword})


def valid_signature(body: bytes, header: str | None) -> bool:
    if not APP_SECRET:
        return True
    if not header or not header.startswith("sha256="):
        return False
    expected = hmac.new(APP_SECRET.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(header.split("=", 1)[1], expected)


@core.app.get("/webhooks/instagram")
def instagram_verify(request: Request):
    qp = request.query_params
    if qp.get("hub.mode") == "subscribe" and VERIFY_TOKEN and qp.get("hub.verify_token") == VERIFY_TOKEN:
        return Response(content=qp.get("hub.challenge", ""), media_type="text/plain")
    return Response(status_code=403)


@core.app.post("/webhooks/instagram")
async def instagram_webhook(request: Request):
    body = await request.body()
    if not valid_signature(body, request.headers.get("x-hub-signature-256")):
        return Response(status_code=403)
    try:
        payload = json.loads(body or b"{}")
        for entry in payload.get("entry", []):
            for change in entry.get("changes", []):
                if change.get("field") in {"comments", "live_comments"}:
                    handle_comment(change.get("value") or {})
    except Exception as exc:
        print(f"IG webhook error: {exc}", flush=True)
    return JSONResponse({"ok": True})


@core.app.get("/ig/{token}")
def instagram_trial(token: str):
    lead = core.one("SELECT * FROM growth_instagram_leads WHERE token=?", (token,))
    if not lead:
        return Response(status_code=404)
    if not lead.get("clicked_at"):
        core.run("UPDATE growth_instagram_leads SET clicked_at=?,status='CLICKED' WHERE id=?", (now(), lead["id"]))
        log(lead["id"], "instagram.clicked", {})
    response = RedirectResponse("/signup", status_code=303)
    response.set_cookie("ec_growth", token, max_age=60 * 60 * 24 * 14, httponly=True, secure=core.BASE_URL.startswith("https://"), samesite="lax")
    return response


def reconcile():
    leads = core.all_rows("SELECT * FROM growth_instagram_leads WHERE clicked_at IS NOT NULL AND paid_at IS NULL")
    for lead in leads:
        aid = lead.get("artist_id")
        if not aid:
            continue
        artist = core.one("SELECT * FROM artists WHERE id=?", (aid,)) or {}
        status = str(artist.get("subscription_status") or "").lower()
        if status == "active":
            core.run("UPDATE growth_instagram_leads SET paid_at=?,status='PAID' WHERE id=?", (now(), lead["id"]))
            log(lead["id"], "instagram.paid", {"artist_id": aid, "mrr_cents": 9700})


def worker():
    while True:
        try:
            reconcile()
        except Exception as exc:
            print(f"IG growth reconcile failed: {exc}", flush=True)
        time.sleep(WORKER_SECONDS)


init()
if core.WORKER_ENABLED:
    threading.Thread(target=worker, daemon=True, name="instagram-growth").start()
