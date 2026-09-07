"""Simple Hunter operator queue for the production v2 app.

Hunter gives the founder one fresh tattoo artist at a time, opens that artist's public
Instagram profile, and records Handled or Skip. No follow action, DM, outreach, login
automation, or private-data access happens here.
"""
from __future__ import annotations

import hashlib
import hmac
import html
import json
import os
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from urllib.parse import quote

from fastapi import HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

import v2_app as core
from hunter.operator_console import DECISIONS, SCHEMA

FRESH_BUCKET_SCHEMA = "empty-chair-hunter-fresh-contact-bucket-v1"
SIMPLE_DECISIONS = {"HANDLED", "SKIPPED"}
INGEST_TOKEN = os.getenv("HUNTER_OPERATOR_INGEST_TOKEN", "")
ADMIN_EMAILS = {
    email.strip().lower()
    for email in os.getenv("EMPTY_CHAIR_ADMIN_EMAILS", "").split(",")
    if email.strip()
}
META_TOKEN = os.getenv("INSTAGRAM_ACCESS_TOKEN", "").strip()
IG_USER_ID = os.getenv("INSTAGRAM_USER_ID", "").strip()
GRAPH_VERSION = os.getenv("META_GRAPH_VERSION", "v24.0").strip()

TARGET_TABLE = """CREATE TABLE IF NOT EXISTS hunter_operator_targets (
    account_id TEXT PRIMARY KEY,
    hunter_target_id TEXT,
    username TEXT,
    profile_url TEXT,
    score INTEGER NOT NULL DEFAULT 0,
    score_state TEXT,
    queue_state TEXT,
    decision TEXT NOT NULL DEFAULT 'PENDING',
    snapshot_json TEXT NOT NULL,
    source_generated_at TEXT,
    first_ingested_at TEXT NOT NULL,
    last_ingested_at TEXT NOT NULL,
    decided_at TEXT,
    decided_by TEXT
)"""
META_TABLE = """CREATE TABLE IF NOT EXISTS hunter_operator_meta (
    id TEXT PRIMARY KEY,
    snapshot_json TEXT NOT NULL,
    updated_at TEXT NOT NULL
)"""
AUDIT_TABLE = """CREATE TABLE IF NOT EXISTS hunter_operator_audit (
    id TEXT PRIMARY KEY,
    account_id TEXT,
    action TEXT NOT NULL,
    actor TEXT NOT NULL,
    previous_decision TEXT,
    new_decision TEXT,
    created_at TEXT NOT NULL,
    detail_json TEXT NOT NULL
)"""

_followers_cache = {"value": None, "at": 0.0}


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def esc(value: object) -> str:
    return html.escape(str(value or ""), quote=True)


def safe_json(value: object) -> str:
    return json.dumps(value, separators=(",", ":"), ensure_ascii=False)


def load_json(value: object, fallback):
    try:
        return json.loads(str(value or ""))
    except Exception:
        return fallback


def ensure_tables(db: core.DB) -> None:
    for stmt in (TARGET_TABLE, META_TABLE, AUDIT_TABLE):
        db.execute(stmt)
    db.commit()


def admin_artist(request: Request):
    artist = core.current_artist(request)
    if not artist or str(artist.get("email") or "").strip().lower() not in ADMIN_EMAILS:
        raise HTTPException(404, "Not found")
    return artist


def auth_ingest(request: Request) -> None:
    if not INGEST_TOKEN:
        raise HTTPException(503, "Hunter operator ingest is not configured")
    supplied = request.headers.get("authorization", "")
    if not hmac.compare_digest(supplied, f"Bearer {INGEST_TOKEN}"):
        raise HTTPException(401, "Unauthorized")


def audit_id(account_id: str, actor: str, created_at: str) -> str:
    raw = f"{account_id}:{actor}:{created_at}".encode()
    return "hoa_" + hashlib.sha256(raw).hexdigest()[:24]


def _fresh_target(artist: dict) -> dict | None:
    username = str(artist.get("username") or "").strip().lstrip("@").lower()
    if not username:
        return None
    contact = artist.get("contact") if isinstance(artist.get("contact"), dict) else {}
    return {
        "account_id": f"ig:{username}",
        "hunter_target_id": f"fresh:{username}",
        "username": username,
        "name": artist.get("name"),
        "profile_url": artist.get("profile_url") or contact.get("instagram_url") or f"https://www.instagram.com/{username}/",
        "market": artist.get("market"),
        "activity_source": artist.get("activity_source"),
        "activity_source_url": artist.get("activity_source_url"),
        "event_start": artist.get("event_start"),
        "event_end": artist.get("event_end"),
        "fresh_activity": bool(artist.get("fresh_activity")),
        "contact": contact,
        "score": int(contact.get("contactability") or 40),
        "score_state": "FRESH",
        "queue_state": "READY",
    }


def _normalize_snapshot(snapshot: dict) -> tuple[list[dict], str | None, dict]:
    schema = snapshot.get("schema")
    if schema == FRESH_BUCKET_SCHEMA:
        artists = snapshot.get("artists")
        if not isinstance(artists, list):
            raise ValueError(f"Expected {FRESH_BUCKET_SCHEMA} payload")
        targets = []
        for artist in artists:
            if isinstance(artist, dict):
                target = _fresh_target(artist)
                if target:
                    targets.append(target)
        meta = {key: value for key, value in snapshot.items() if key != "artists"}
        return targets, snapshot.get("generated_at"), meta
    if schema == SCHEMA and isinstance(snapshot.get("targets"), list):
        return list(snapshot["targets"]), snapshot.get("source_generated_at"), {
            key: value for key, value in snapshot.items() if key != "targets"
        }
    raise ValueError(f"Expected {FRESH_BUCKET_SCHEMA} or {SCHEMA} payload")


def ingest_snapshot(snapshot: dict) -> int:
    targets, source_generated_at, meta = _normalize_snapshot(snapshot)
    if len(targets) > 5000:
        raise ValueError("snapshot target limit exceeded")
    db = core.DB()
    try:
        ensure_tables(db)
        ingested_at = now()
        count = 0
        for target in targets:
            if not isinstance(target, dict):
                continue
            account_id = target.get("account_id")
            if not isinstance(account_id, str) or not account_id:
                continue
            username = str(target.get("username") or "").strip().lstrip("@").lower()
            if not username:
                continue
            profile_url = str(target.get("profile_url") or f"https://www.instagram.com/{username}/")
            if not profile_url.startswith(("https://", "http://")):
                profile_url = f"https://www.instagram.com/{username}/"
            db.execute(
                """INSERT INTO hunter_operator_targets (
                    account_id,hunter_target_id,username,profile_url,score,score_state,queue_state,
                    decision,snapshot_json,source_generated_at,first_ingested_at,last_ingested_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(account_id) DO UPDATE SET
                    hunter_target_id=excluded.hunter_target_id,
                    username=excluded.username,
                    profile_url=excluded.profile_url,
                    score=excluded.score,
                    score_state=excluded.score_state,
                    queue_state=excluded.queue_state,
                    snapshot_json=excluded.snapshot_json,
                    source_generated_at=excluded.source_generated_at,
                    last_ingested_at=excluded.last_ingested_at""",
                (
                    account_id, target.get("hunter_target_id"), username, profile_url,
                    int(target.get("score") or 0), target.get("score_state"), target.get("queue_state"),
                    "PENDING", safe_json(target), source_generated_at, ingested_at, ingested_at,
                ),
            )
            count += 1
        db.execute(
            """INSERT INTO hunter_operator_meta(id,snapshot_json,updated_at) VALUES('latest',?,?)
               ON CONFLICT(id) DO UPDATE SET snapshot_json=excluded.snapshot_json,updated_at=excluded.updated_at""",
            (safe_json(meta), ingested_at),
        )
        db.commit()
        return count
    except Exception:
        db.raw.rollback()
        raise
    finally:
        db.close()


def set_decision(account_id: str, decision: str, actor: str, *, bulk: bool = False) -> bool:
    normalized = str(decision or "").upper()
    allowed = set(DECISIONS) | SIMPLE_DECISIONS
    if normalized not in allowed or normalized == "PENDING":
        raise ValueError("invalid operator decision")
    db = core.DB()
    try:
        ensure_tables(db)
        row = db.execute("SELECT decision FROM hunter_operator_targets WHERE account_id=?", (account_id,)).fetchone()
        if not row:
            return False
        previous = str(dict(row).get("decision") or "PENDING")
        created_at = now()
        db.execute(
            "UPDATE hunter_operator_targets SET decision=?,decided_at=?,decided_by=? WHERE account_id=?",
            (normalized, created_at, actor, account_id),
        )
        db.execute(
            """INSERT INTO hunter_operator_audit
               (id,account_id,action,actor,previous_decision,new_decision,created_at,detail_json)
               VALUES(?,?,?,?,?,?,?,?)""",
            (audit_id(account_id, actor, created_at), account_id, "DECISION", actor,
             previous, normalized, created_at, safe_json({"bulk": bulk})),
        )
        db.commit()
        return True
    except Exception:
        db.raw.rollback()
        raise
    finally:
        db.close()


@core.app.post("/internal/hunter/operator/snapshot")
async def operator_ingest(request: Request):
    auth_ingest(request)
    length = request.headers.get("content-length")
    if length and length.isdigit() and int(length) > 5_000_000:
        raise HTTPException(413, "Snapshot too large")
    try:
        snapshot = await request.json()
        count = ingest_snapshot(snapshot)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except Exception as exc:
        raise HTTPException(400, "Invalid Hunter operator snapshot") from exc
    return {"ok": True, "schema": snapshot.get("schema"), "target_count": count}


@core.app.post("/owner/hunter/{account_id}/decision")
async def operator_decision(request: Request, account_id: str):
    artist = admin_artist(request)
    form = await request.form()
    try:
        changed = set_decision(account_id, str(form.get("decision") or ""), artist["email"])
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    if not changed:
        raise HTTPException(404, "Target not found")
    return RedirectResponse("/owner/hunter", status_code=303)


@core.app.post("/owner/hunter/bulk")
async def operator_bulk(request: Request):
    artist = admin_artist(request)
    form = await request.form()
    account_ids = [str(value) for value in form.getlist("account_id") if str(value)]
    if len(account_ids) > 200:
        raise HTTPException(400, "Bulk review limit is 200")
    for account_id in account_ids:
        set_decision(account_id, str(form.get("decision") or ""), artist["email"], bulk=True)
    return RedirectResponse("/owner/hunter", status_code=303)


def _display_target(row: dict) -> dict:
    item = load_json(row.get("snapshot_json"), {})
    if not isinstance(item, dict):
        item = {}
    item.setdefault("account_id", row.get("account_id"))
    item.setdefault("username", row.get("username"))
    item.setdefault("profile_url", row.get("profile_url"))
    item.setdefault("score", row.get("score"))
    item["decision"] = row.get("decision")
    return item


def _today_prefix() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def _website_visits() -> int:
    try:
        row = core.one(
            "SELECT COUNT(*) AS n FROM growth_instagram_leads WHERE clicked_at IS NOT NULL AND keyword='bio'"
        )
        return int((row or {}).get("n") or 0)
    except Exception:
        return 0


def _instagram_followers() -> int | None:
    stamp = time.time()
    if stamp - float(_followers_cache["at"] or 0) < 600:
        return _followers_cache["value"]
    value = None
    if META_TOKEN and IG_USER_ID:
        try:
            query = urllib.parse.urlencode({"fields": "followers_count", "access_token": META_TOKEN})
            url = f"https://graph.facebook.com/{GRAPH_VERSION}/{IG_USER_ID}?{query}"
            with urllib.request.urlopen(url, timeout=6) as response:
                payload = json.loads(response.read().decode() or "{}")
            if payload.get("followers_count") is not None:
                value = int(payload["followers_count"])
        except Exception as exc:
            print(f"Hunter follower count unavailable: {exc}", flush=True)
    _followers_cache["value"] = value
    _followers_cache["at"] = stamp
    return value


@core.app.get("/owner/hunter", response_class=HTMLResponse)
def operator_console(request: Request):
    admin_artist(request)
    db = core.DB()
    try:
        ensure_tables(db)
        pending_rows = [dict(r) for r in db.execute(
            """SELECT * FROM hunter_operator_targets
               WHERE decision='PENDING' AND username IS NOT NULL AND profile_url IS NOT NULL
               ORDER BY first_ingested_at ASC, score DESC, username ASC"""
        ).fetchall()]
        today = _today_prefix()
        new_today = int(db.execute(
            "SELECT COUNT(*) AS n FROM hunter_operator_targets WHERE first_ingested_at LIKE ?", (today + "%",)
        ).fetchone()["n"])
        handled_today = int(db.execute(
            "SELECT COUNT(*) AS n FROM hunter_operator_targets WHERE decision='HANDLED' AND decided_at LIKE ?", (today + "%",)
        ).fetchone()["n"])
        skipped_today = int(db.execute(
            "SELECT COUNT(*) AS n FROM hunter_operator_targets WHERE decision='SKIPPED' AND decided_at LIKE ?", (today + "%",)
        ).fetchone()["n"])
    finally:
        db.close()

    followers = _instagram_followers()
    website_visits = _website_visits()
    follower_display = f"{followers:,}" if followers is not None else "—"
    remaining = len(pending_rows)
    current = _display_target(pending_rows[0]) if pending_rows else None

    if current:
        account_id = str(current.get("account_id") or "")
        username_raw = str(current.get("username") or "").strip().lstrip("@")
        username = esc(username_raw)
        name = esc(current.get("name") or "")
        market = esc(current.get("market") or "")
        source = esc(current.get("activity_source") or "")
        # Instagram's HTTPS universal-link form gives iOS the best chance to hand off
        # directly to the installed app. iOS/Safari may still require a system prompt.
        instagram_profile = f"https://www.instagram.com/_u/{quote(username_raw, safe='._')}/"
        path_id = quote(account_id, safe="")
        identity = f"<div class='name'>{name}</div>" if name and name.lower() != username.lower() else ""
        context = " · ".join(bit for bit in (market, source) if bit)
        card = f"""
        <section class='card'>
          <div class='eyebrow'>NEXT ARTIST</div>
          {identity}
          <h1>@{username}</h1>
          <p class='context'>{context or 'Fresh tattoo artist'}</p>
          <a class='instagram' href='{esc(instagram_profile)}'>OPEN INSTAGRAM</a>
          <div class='actions'>
            <form method='post' action='/owner/hunter/{path_id}/decision'>
              <input type='hidden' name='decision' value='HANDLED'>
              <button class='handled'>HANDLED</button>
            </form>
            <form method='post' action='/owner/hunter/{path_id}/decision'>
              <input type='hidden' name='decision' value='SKIPPED'>
              <button class='skip'>SKIP</button>
            </form>
          </div>
          <p class='hint'>Open the profile, follow or review it yourself, then tap Handled. Hunter never follows automatically.</p>
        </section>"""
    else:
        card = """
        <section class='card empty'>
          <div class='check'>✓</div>
          <h1>YOU'RE CAUGHT UP</h1>
          <p>Hunter has no new artists waiting right now.</p>
        </section>"""

    return HTMLResponse(f"""<!doctype html>
<html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1,viewport-fit=cover'>
<title>Hunter</title><style>
:root{{--bg:#090909;--panel:#121212;--line:#292929;--text:#f4f1e8;--muted:#8d8a82;--accent:#ffb000;--green:#b7ff76}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--text);font-family:ui-monospace,SFMono-Regular,Menlo,monospace;min-height:100vh}}
main{{width:min(100%,560px);margin:0 auto;padding:calc(22px + env(safe-area-inset-top)) 18px calc(30px + env(safe-area-inset-bottom))}}
.top{{display:flex;align-items:flex-end;justify-content:space-between;margin-bottom:18px}}.brand{{font-size:18px;font-weight:900;letter-spacing:.08em}}.remaining{{text-align:right;color:var(--muted);font-size:11px}}.remaining b{{display:block;color:var(--text);font-size:24px}}
.stats{{display:grid;grid-template-columns:repeat(3,1fr);gap:8px;margin-bottom:8px}}.growth{{display:grid;grid-template-columns:repeat(2,1fr);gap:8px;margin-bottom:14px}}.stat{{border:1px solid var(--line);border-radius:12px;padding:10px;font-size:10px;color:var(--muted)}}.stat b{{display:block;color:var(--text);font-size:19px;margin-bottom:2px}}
.card{{background:var(--panel);border:1px solid var(--line);border-radius:18px;padding:24px 18px;min-height:390px;display:flex;flex-direction:column;justify-content:center}}.eyebrow{{color:var(--accent);font-size:11px;font-weight:800;letter-spacing:.16em;margin-bottom:12px}}.name{{color:var(--muted);font-size:14px;margin-bottom:3px}}h1{{font-size:30px;line-height:1.1;margin:0 0 8px;overflow-wrap:anywhere}}.context{{color:var(--muted);margin:0 0 25px;font-size:12px;line-height:1.5}}
.instagram{{display:block;text-align:center;text-decoration:none;background:var(--text);color:#050505;padding:17px;border-radius:12px;font-weight:900;font-size:15px;margin-bottom:10px}}.actions{{display:grid;grid-template-columns:2fr 1fr;gap:9px}}form{{margin:0}}button{{width:100%;border-radius:12px;padding:15px 8px;font:inherit;font-weight:900;cursor:pointer}}.handled{{background:var(--accent);border:1px solid var(--accent);color:#090909}}.skip{{background:transparent;border:1px solid #444;color:var(--muted)}}.hint{{font-size:10px;color:#666;line-height:1.5;text-align:center;margin:16px 8px 0}}.empty{{text-align:center;min-height:300px}}.empty p{{color:var(--muted)}}.check{{font-size:48px;color:var(--green);margin-bottom:10px}}
</style></head><body><main>
<div class='top'><div class='brand'>HUNTER</div><div class='remaining'><b>{remaining}</b>WAITING</div></div>
<div class='stats'><div class='stat'><b>{new_today}</b>NEW TODAY</div><div class='stat'><b>{handled_today}</b>HANDLED</div><div class='stat'><b>{skipped_today}</b>SKIPPED</div></div>
<div class='growth'><div class='stat'><b>{follower_display}</b>FOLLOWERS</div><div class='stat'><b>{website_visits:,}</b>WEBSITE VISITS</div></div>
{card}
</main></body></html>""", headers={"Cache-Control": "no-store"})
