"""Hunter Sprint 9 operator console for the production v2 app.

This extension ingests safe Hunter review snapshots, stores them in Empty Chair's database,
preserves manual decisions across refreshes, and exposes an admin-only review console.
Approval is internal state only; no outreach is sent from this module.
"""
from __future__ import annotations

import hashlib
import hmac
import html
import json
import os
from datetime import datetime, timezone
from urllib.parse import quote

from fastapi import HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

import v2_app as core
from hunter.operator_console import DECISIONS, SCHEMA

INGEST_TOKEN = os.getenv("HUNTER_OPERATOR_INGEST_TOKEN", "")
ADMIN_EMAILS = {
    email.strip().lower()
    for email in os.getenv("EMPTY_CHAIR_ADMIN_EMAILS", "").split(",")
    if email.strip()
}

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


def ingest_snapshot(snapshot: dict) -> int:
    if snapshot.get("schema") != SCHEMA or not isinstance(snapshot.get("targets"), list):
        raise ValueError(f"Expected {SCHEMA} payload")
    if len(snapshot["targets"]) > 5000:
        raise ValueError("snapshot target limit exceeded")

    db = core.DB()
    try:
        ensure_tables(db)
        ingested_at = now()
        count = 0
        for target in snapshot["targets"]:
            if not isinstance(target, dict):
                continue
            account_id = target.get("account_id")
            if not isinstance(account_id, str) or not account_id:
                continue
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
                    account_id,
                    target.get("hunter_target_id"),
                    target.get("username"),
                    target.get("profile_url"),
                    int(target.get("score") or 0),
                    target.get("score_state"),
                    target.get("queue_state"),
                    "PENDING",
                    safe_json(target),
                    snapshot.get("source_generated_at"),
                    ingested_at,
                    ingested_at,
                ),
            )
            count += 1
        meta = {key: value for key, value in snapshot.items() if key != "targets"}
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
    if normalized not in DECISIONS or normalized == "PENDING":
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
            (
                audit_id(account_id, actor, created_at),
                account_id,
                "DECISION",
                actor,
                previous,
                normalized,
                created_at,
                safe_json({"bulk": bulk}),
            ),
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
    return {"ok": True, "schema": SCHEMA, "target_count": count}


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
    changed = 0
    try:
        for account_id in account_ids:
            if set_decision(account_id, str(form.get("decision") or ""), artist["email"], bulk=True):
                changed += 1
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return RedirectResponse(f"/owner/hunter?bulk={changed}", status_code=303)


def location_text(value: object) -> str:
    if not isinstance(value, dict):
        return "Unknown"
    return ", ".join(str(value.get(key)) for key in ("city", "region", "country") if value.get(key)) or "Unknown"


def safe_link(value: object) -> str | None:
    url = str(value or "")
    return url if url.startswith(("https://", "http://")) else None


def card(item: dict) -> str:
    account_id = str(item.get("account_id") or "")
    username = esc(item.get("username") or account_id)
    profile = safe_link(item.get("profile_url"))
    profile_html = f"<a href='{esc(profile)}' target='_blank' rel='noopener noreferrer'>@{username}</a>" if profile else f"@{username}"
    score = int(item.get("score") or 0)
    state = esc(item.get("score_state") or item.get("queue_state") or "UNKNOWN")
    decision = esc(item.get("decision") or "PENDING")
    stage = esc(item.get("furthest_stage") or "—")
    revenue = int(item.get("revenue_cents") or 0) / 100
    rules = "".join(
        f"<li><b>{esc(c.get('rule'))}</b> {int(c.get('points') or 0):+d}<small>{esc(c.get('evidence'))}</small></li>"
        for c in item.get("components", []) if isinstance(c, dict)
    ) or "<li>No scoring evidence recorded.</li>"
    signals = "".join(
        f"<div class='signal'><b>{esc(s.get('matched_phrase') or s.get('source') or 'signal')}</b><p>{esc(s.get('snippet') or s.get('title') or '')}</p>"
        + (f"<a href='{esc(safe_link(s.get('source_url')))}' target='_blank' rel='noopener noreferrer'>source</a>" if safe_link(s.get("source_url")) else "")
        + "</div>"
        for s in item.get("signals", []) if isinstance(s, dict)
    ) or "<div class='signal dim'>No source excerpt in this snapshot.</div>"
    path_id = quote(account_id, safe="")
    return f"""<article class='card'>
      <label class='pick'><input type='checkbox' name='account_id' value='{esc(account_id)}' form='bulk-form'> select</label>
      <div class='head'><div><div class='kicker'>{state} // {decision}</div><h2>{profile_html}</h2><div class='dim'>{esc(location_text(item.get('location')))}</div></div><div class='score'>{score}</div></div>
      <div class='facts'><span>stage <b>{stage}</b></span><span>revenue <b>${revenue:,.2f}</b></span><span>priority <b>{esc(item.get('priority') or '—')}</b></span><span>activity <b>{esc(item.get('last_activity_at') or 'unknown')}</b></span></div>
      <details><summary>WHY HUNTER RANKED THIS</summary><ul>{rules}</ul></details>
      <details><summary>SOURCE EVIDENCE</summary>{signals}</details>
      <details><summary>ACTION + ATTRIBUTION</summary><p class='dim'>queue={esc(item.get('queue_state'))} // last_action={esc(item.get('last_action_at') or '—')} // target={esc(item.get('hunter_target_id') or '—')} // reason={esc(item.get('reason') or '—')}</p></details>
      <div class='actions'><form method='post' action='/owner/hunter/{path_id}/decision'><input type='hidden' name='decision' value='APPROVED'><button class='go'>APPROVE</button></form><form method='post' action='/owner/hunter/{path_id}/decision'><input type='hidden' name='decision' value='SUPPRESSED'><button>SUPPRESS</button></form><form method='post' action='/owner/hunter/{path_id}/decision'><input type='hidden' name='decision' value='BAD_FIT'><button>BAD FIT</button></form></div>
      <small>Approval records operator intent only. It does not contact this artist.</small>
    </article>"""


@core.app.get("/owner/hunter", response_class=HTMLResponse)
def operator_console(request: Request):
    admin_artist(request)
    db = core.DB()
    try:
        ensure_tables(db)
        rows = [dict(r) for r in db.execute("SELECT * FROM hunter_operator_targets ORDER BY score DESC,last_ingested_at DESC").fetchall()]
        meta_row_raw = db.execute("SELECT * FROM hunter_operator_meta WHERE id='latest'").fetchone()
        meta_row = dict(meta_row_raw) if meta_row_raw else None
        audits = [dict(r) for r in db.execute("SELECT * FROM hunter_operator_audit ORDER BY created_at DESC LIMIT 50").fetchall()]
    finally:
        db.close()

    targets = []
    for row in rows:
        item = load_json(row.get("snapshot_json"), {})
        if not isinstance(item, dict):
            item = {}
        item["decision"] = row.get("decision")
        targets.append(item)

    state_filter = str(request.query_params.get("state") or "ALL").upper()
    decision_filter = str(request.query_params.get("decision") or "ALL").upper()
    sort = str(request.query_params.get("sort") or "score").lower()
    query = str(request.query_params.get("q") or "").strip().lower()

    def visible(item: dict) -> bool:
        if state_filter != "ALL":
            if state_filter == "PAID" and item.get("furthest_stage") != "PAID": return False
            if state_filter != "PAID" and state_filter not in {str(item.get("score_state") or ""), str(item.get("queue_state") or "")}: return False
        if decision_filter != "ALL" and decision_filter != str(item.get("decision") or "PENDING"): return False
        if query:
            haystack = f"{item.get('username','')} {location_text(item.get('location'))} {item.get('account_id','')}".lower()
            if query not in haystack: return False
        return True

    targets = [item for item in targets if visible(item)]
    if sort == "revenue": targets.sort(key=lambda x: (-int(x.get("revenue_cents") or 0), -int(x.get("score") or 0)))
    elif sort == "recency": targets.sort(key=lambda x: str(x.get("last_activity_at") or ""), reverse=True)
    else: targets.sort(key=lambda x: (-int(x.get("score") or 0), str(x.get("username") or "")))

    meta = load_json(meta_row.get("snapshot_json"), {}) if meta_row else {}
    warnings = meta.get("validation_warnings", []) if isinstance(meta, dict) else []
    recommendations = meta.get("learning_recommendations", []) if isinstance(meta, dict) else []
    notices = "".join(f"<div class='notice'><b>{esc(x.get('stage'))}</b> // {esc(x.get('code'))}</div>" for x in warnings if isinstance(x, dict))
    notices += "".join(f"<div class='notice'><b>{esc(x.get('rule'))}</b> // {esc(x.get('current_weight'))} → {esc(x.get('recommended_weight'))} // HUMAN APPROVAL REQUIRED</div>" for x in recommendations if isinstance(x, dict))
    cards = "".join(card(item) for item in targets) or "<div class='empty'>NO TARGETS MATCH THESE FILTERS.</div>"
    audit_html = "".join(f"<tr><td>{esc(row.get('created_at'))}</td><td>{esc(row.get('account_id'))}</td><td>{esc(row.get('previous_decision'))} → {esc(row.get('new_decision'))}</td><td>{esc(row.get('actor'))}</td></tr>" for row in audits) or "<tr><td colspan='4'>NO DECISIONS YET.</td></tr>"
    pending = sum(1 for row in rows if row.get("decision") == "PENDING")
    approved = sum(1 for row in rows if row.get("decision") == "APPROVED")
    revenue = int(meta.get("revenue_cents") or 0) / 100 if isinstance(meta, dict) else 0

    options_state = "".join(f"<option {'selected' if state_filter == value else ''}>{value}</option>" for value in ("ALL","HOT","WARM","ACTIONED","PAID"))
    options_decision = "".join(f"<option {'selected' if decision_filter == value else ''}>{value}</option>" for value in ("ALL","PENDING","APPROVED","SUPPRESSED","BAD_FIT"))
    options_sort = "".join(f"<option value='{value}' {'selected' if sort == value else ''}>{value}</option>" for value in ("score","recency","revenue"))

    return HTMLResponse(f"""<!doctype html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>HUNTER // OPERATOR</title><style>
    :root{{--bg:#0B0905;--amber:#FFB000;--bright:#FFD36A;--dim:#805800;--off:#332300}}*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--amber);font-family:ui-monospace,SFMono-Regular,Menlo,monospace}}main{{max-width:1180px;margin:auto;padding:24px}}a{{color:var(--bright)}}h1{{font-size:34px}}h2{{margin:4px 0}}.kicker{{font-size:11px;letter-spacing:.12em}}.dim,small{{color:var(--dim)}}.metrics{{display:grid;grid-template-columns:repeat(5,1fr);gap:8px;margin:18px 0}}.metric,.notice,.card,.empty{{border:1px solid var(--off);padding:14px}}.metric b{{display:block;color:var(--bright);font-size:24px}}.notice{{margin:7px 0}}.toolbar,.actions,.facts{{display:flex;gap:8px;flex-wrap:wrap;margin:12px 0}}select,input,button{{background:transparent;color:var(--bright);border:1px solid var(--dim);padding:10px;font:inherit}}button{{cursor:pointer}}button.go{{border-color:var(--amber)}}.card{{margin:12px 0;position:relative}}.head{{display:flex;justify-content:space-between}}.score{{font-size:40px;color:var(--bright)}}.pick{{position:absolute;right:14px;top:70px;font-size:11px}}details{{border-top:1px solid var(--off);padding:10px 0}}summary{{cursor:pointer}}li small{{display:block}}.signal{{border-left:2px solid var(--off);padding:7px 10px;margin:7px 0}}.signal p{{font-size:12px}}table{{width:100%;border-collapse:collapse;font-size:12px}}td,th{{text-align:left;padding:7px;border-bottom:1px solid var(--off)}}@media(max-width:760px){{.metrics{{grid-template-columns:repeat(2,1fr)}}.pick{{position:static}}}}
    </style></head><body><main><div class='kicker'>EMPTY CHAIR // HUNTER // SPRINT 9</div><h1>OPERATOR CONSOLE</h1><p class='dim'>HUMAN REVIEW GATE. APPROVAL NEVER SENDS OUTREACH.</p><div class='metrics'><div class='metric'>TARGETS<b>{len(rows)}</b></div><div class='metric'>PENDING<b>{pending}</b></div><div class='metric'>APPROVED<b>{approved}</b></div><div class='metric'>PAID<b>{int(meta.get('paid_count') or 0) if isinstance(meta,dict) else 0}</b></div><div class='metric'>REVENUE<b>${revenue:,.0f}</b></div></div>{notices}
    <form class='toolbar' method='get'><select name='state'>{options_state}</select><select name='decision'>{options_decision}</select><select name='sort'>{options_sort}</select><input name='q' value='{esc(request.query_params.get('q') or '')}' placeholder='artist or location'><button>FILTER</button></form>
    <form id='bulk-form' class='toolbar' method='post' action='/owner/hunter/bulk'><select name='decision'><option value='APPROVED'>APPROVE SELECTED</option><option value='SUPPRESSED'>SUPPRESS SELECTED</option><option value='BAD_FIT'>MARK BAD FIT</option></select><button>APPLY</button><button type='button' onclick="document.querySelectorAll('.pick input').forEach(x=>x.checked=true)">SELECT VISIBLE</button></form>{cards}
    <h2>AUDIT TRAIL</h2><table><tr><th>WHEN</th><th>TARGET</th><th>DECISION</th><th>OPERATOR</th></tr>{audit_html}</table><p class='dim'>LATEST SNAPSHOT // {esc(meta_row.get('updated_at') if meta_row else 'NOT INGESTED')}</p></main></body></html>""", headers={"Cache-Control":"no-store"})
