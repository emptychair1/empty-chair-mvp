"""Owner-only Hunter operator console and safe snapshot ingest.

The console stores Hunter's ranked review snapshot, preserves manual decisions across
pipeline refreshes, and records an audit trail. Approval is review state only: this module
never contacts a target and never enables Sprint 5 execution.
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

import app as core
from hunter.operator_console import DECISIONS, SCHEMA

INGEST_TOKEN = os.getenv("HUNTER_OPERATOR_INGEST_TOKEN", "")
ADMIN_EMAILS = {
    core.normalize_email(email)
    for email in os.getenv("EMPTY_CHAIR_ADMIN_EMAILS", "").split(",")
    if core.normalize_email(email)
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _e(value: object) -> str:
    return html.escape(str(value or ""), quote=True)


def _safe_json(value: object) -> str:
    return json.dumps(value, separators=(",", ":"), ensure_ascii=False)


def _load_json(value: object, fallback):
    try:
        parsed = json.loads(str(value or ""))
    except (TypeError, ValueError, json.JSONDecodeError):
        return fallback
    return parsed


def _is_admin(user) -> bool:
    return bool(user and core.normalize_email(user["email"]) in ADMIN_EMAILS)


def _admin_user(request: Request):
    user, redirect = core.login_required_redirect(request)
    if redirect:
        return None, redirect
    if not _is_admin(user):
        raise HTTPException(404, "Not found")
    return user, None


def _ensure_tables(conn) -> None:
    core.db_execute(
        conn,
        """CREATE TABLE IF NOT EXISTS hunter_operator_targets (
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
        )""",
    )
    core.db_execute(
        conn,
        """CREATE TABLE IF NOT EXISTS hunter_operator_meta (
            id TEXT PRIMARY KEY,
            snapshot_json TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )""",
    )
    core.db_execute(
        conn,
        """CREATE TABLE IF NOT EXISTS hunter_operator_audit (
            id TEXT PRIMARY KEY,
            account_id TEXT,
            action TEXT NOT NULL,
            actor TEXT NOT NULL,
            previous_decision TEXT,
            new_decision TEXT,
            created_at TEXT NOT NULL,
            detail_json TEXT NOT NULL
        )""",
    )
    conn.commit()


def _auth_ingest(request: Request) -> None:
    if not INGEST_TOKEN:
        raise HTTPException(503, "Hunter operator ingest is not configured")
    supplied = request.headers.get("authorization", "")
    expected = f"Bearer {INGEST_TOKEN}"
    if not hmac.compare_digest(supplied, expected):
        raise HTTPException(401, "Unauthorized")


def _audit_id(account_id: str, action: str, actor: str, now: str) -> str:
    raw = f"{account_id}:{action}:{actor}:{now}".encode()
    return "hoa_" + hashlib.sha256(raw).hexdigest()[:24]


def _ingest_snapshot(conn, snapshot: dict) -> int:
    if snapshot.get("schema") != SCHEMA or not isinstance(snapshot.get("targets"), list):
        raise ValueError(f"Expected {SCHEMA} payload")
    if len(snapshot["targets"]) > 5000:
        raise ValueError("snapshot target limit exceeded")

    now = _now()
    source_generated_at = snapshot.get("source_generated_at")
    count = 0
    for target in snapshot["targets"]:
        if not isinstance(target, dict):
            continue
        account_id = target.get("account_id")
        if not isinstance(account_id, str) or not account_id:
            continue
        core.db_execute(
            conn,
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
                _safe_json(target),
                source_generated_at,
                now,
                now,
            ),
        )
        count += 1

    core.db_execute(
        conn,
        """INSERT INTO hunter_operator_meta (id,snapshot_json,updated_at)
           VALUES ('latest',?,?)
           ON CONFLICT(id) DO UPDATE SET snapshot_json=excluded.snapshot_json,updated_at=excluded.updated_at""",
        (_safe_json({k: v for k, v in snapshot.items() if k != "targets"}), now),
    )
    conn.commit()
    return count


@core.app.post("/internal/hunter/operator/snapshot")
async def hunter_operator_ingest(request: Request):
    _auth_ingest(request)
    length = request.headers.get("content-length")
    if length and length.isdigit() and int(length) > 5_000_000:
        raise HTTPException(413, "Snapshot too large")
    try:
        snapshot = await request.json()
    except Exception as exc:
        raise HTTPException(400, "Invalid JSON") from exc
    conn = core.connect()
    try:
        _ensure_tables(conn)
        try:
            count = _ingest_snapshot(conn, snapshot)
        except ValueError as exc:
            conn.rollback()
            raise HTTPException(400, str(exc)) from exc
    finally:
        conn.close()
    return {"ok": True, "target_count": count, "schema": SCHEMA}


def _set_decision(conn, account_id: str, decision: str, actor: str, detail: dict | None = None) -> bool:
    normalized = str(decision or "").upper()
    if normalized not in DECISIONS or normalized == "PENDING":
        raise ValueError("invalid operator decision")
    row = core.db_fetchone(
        conn,
        "SELECT decision FROM hunter_operator_targets WHERE account_id=?",
        (account_id,),
    )
    if not row:
        return False
    previous = str(row["decision"] or "PENDING")
    now = _now()
    core.db_execute(
        conn,
        """UPDATE hunter_operator_targets
           SET decision=?,decided_at=?,decided_by=? WHERE account_id=?""",
        (normalized, now, actor, account_id),
    )
    core.db_execute(
        conn,
        """INSERT INTO hunter_operator_audit
           (id,account_id,action,actor,previous_decision,new_decision,created_at,detail_json)
           VALUES (?,?,?,?,?,?,?,?)""",
        (
            _audit_id(account_id, "DECISION", actor, now),
            account_id,
            "DECISION",
            actor,
            previous,
            normalized,
            now,
            _safe_json(detail or {}),
        ),
    )
    return True


@core.app.post("/owner/hunter/{account_id}/decision")
async def hunter_operator_decision(request: Request, account_id: str):
    user, redirect = _admin_user(request)
    if redirect:
        return redirect
    form = await request.form()
    decision = str(form.get("decision") or "").upper()
    conn = core.connect()
    try:
        _ensure_tables(conn)
        try:
            changed = _set_decision(conn, account_id, decision, user["email"])
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        if not changed:
            raise HTTPException(404, "Target not found")
        conn.commit()
    finally:
        conn.close()
    return RedirectResponse("/owner/hunter", status_code=303)


@core.app.post("/owner/hunter/bulk")
async def hunter_operator_bulk(request: Request):
    user, redirect = _admin_user(request)
    if redirect:
        return redirect
    form = await request.form()
    decision = str(form.get("decision") or "").upper()
    account_ids = [str(x) for x in form.getlist("account_id") if str(x)]
    if not account_ids:
        return RedirectResponse("/owner/hunter", status_code=303)
    if len(account_ids) > 200:
        raise HTTPException(400, "Bulk review limit is 200 targets")
    conn = core.connect()
    try:
        _ensure_tables(conn)
        changed = 0
        try:
            for account_id in account_ids:
                if _set_decision(conn, account_id, decision, user["email"], {"bulk": True}):
                    changed += 1
        except ValueError as exc:
            conn.rollback()
            raise HTTPException(400, str(exc)) from exc
        conn.commit()
    finally:
        conn.close()
    return RedirectResponse(f"/owner/hunter?bulk={changed}", status_code=303)


def _location_text(value: object) -> str:
    if not isinstance(value, dict):
        return "Unknown"
    parts = [value.get("city"), value.get("region"), value.get("country")]
    return ", ".join(str(x) for x in parts if x) or "Unknown"


def _safe_link(url: object) -> str | None:
    value = str(url or "")
    return value if value.startswith(("https://", "http://")) else None


def _target_card(item: dict) -> str:
    account_id = _e(item.get("account_id"))
    username = _e(item.get("username") or item.get("account_id"))
    profile = _safe_link(item.get("profile_url"))
    profile_html = f"<a href='{_e(profile)}' target='_blank' rel='noopener noreferrer'>@{username}</a>" if profile else f"@{username}"
    score = int(item.get("score") or 0)
    state = _e(item.get("score_state") or item.get("queue_state") or "UNKNOWN")
    decision = _e(item.get("decision") or "PENDING")
    stage = _e(item.get("furthest_stage") or "—")
    revenue = int(item.get("revenue_cents") or 0) / 100
    components = "".join(
        f"<li><strong>{_e(c.get('rule'))}</strong> {int(c.get('points') or 0):+d}<span>{_e(c.get('evidence'))}</span></li>"
        for c in item.get("components", []) if isinstance(c, dict)
    ) or "<li>No scoring evidence recorded.</li>"
    signals = "".join(
        f"<div class='signal'><b>{_e(s.get('matched_phrase') or s.get('source') or 'signal')}</b>"
        f"<p>{_e(s.get('snippet') or s.get('title') or '')}</p>"
        + (f"<a href='{_e(_safe_link(s.get('source_url')))}' target='_blank' rel='noopener noreferrer'>source</a>" if _safe_link(s.get("source_url")) else "")
        + "</div>"
        for s in item.get("signals", []) if isinstance(s, dict)
    ) or "<div class='signal muted'>No source excerpt in this snapshot.</div>"
    return f"""
    <article class='target-card' data-state='{state}' data-decision='{decision}'>
      <label class='pick'><input type='checkbox' name='account_id' value='{account_id}' form='bulk-form'> select</label>
      <div class='target-head'>
        <div><div class='kicker'>{state} · {decision}</div><h3>{profile_html}</h3><div class='muted'>{_e(_location_text(item.get('location')))}</div></div>
        <div class='score'>{score}</div>
      </div>
      <div class='facts'><span>Stage <b>{stage}</b></span><span>Revenue <b>${revenue:,.2f}</b></span><span>Priority <b>{_e(item.get('priority') or '—')}</b></span><span>Activity <b>{_e(item.get('last_activity_at') or 'unknown')}</b></span></div>
      <details><summary>Why Hunter ranked this</summary><ul class='rules'>{components}</ul></details>
      <details><summary>Source evidence</summary>{signals}</details>
      <details><summary>Action + attribution</summary><div class='detail-grid'><span>Queue: {_e(item.get('queue_state'))}</span><span>Last action: {_e(item.get('last_action_at') or '—')}</span><span>Hunter target: {_e(item.get('hunter_target_id') or '—')}</span><span>Reason: {_e(item.get('reason') or '—')}</span></div></details>
      <div class='actions'>
        <form method='post' action='/owner/hunter/{quote(str(item.get('account_id') or ''), safe="")}/decision'><input type='hidden' name='decision' value='APPROVED'><button class='approve'>Approve</button></form>
        <form method='post' action='/owner/hunter/{quote(str(item.get('account_id') or ''), safe="")}/decision'><input type='hidden' name='decision' value='SUPPRESSED'><button>Suppress</button></form>
        <form method='post' action='/owner/hunter/{quote(str(item.get('account_id') or ''), safe="")}/decision'><input type='hidden' name='decision' value='BAD_FIT'><button>Bad fit</button></form>
      </div>
      <p class='safety'>Approval records operator intent only. It does not contact this artist.</p>
    </article>"""


@core.app.get("/owner/hunter", response_class=HTMLResponse)
def hunter_operator_console(request: Request):
    user, redirect = _admin_user(request)
    if redirect:
        return redirect
    conn = core.connect()
    try:
        _ensure_tables(conn)
        rows = core.db_fetchall(conn, "SELECT * FROM hunter_operator_targets ORDER BY score DESC,last_ingested_at DESC")
        meta_row = core.db_fetchone(conn, "SELECT snapshot_json,updated_at FROM hunter_operator_meta WHERE id='latest'")
        audit_rows = core.db_fetchall(conn, "SELECT * FROM hunter_operator_audit ORDER BY created_at DESC LIMIT 50")
    finally:
        conn.close()

    targets = []
    for row in rows:
        item = _load_json(row["snapshot_json"], {})
        if not isinstance(item, dict):
            item = {}
        item["decision"] = row["decision"]
        item["decided_at"] = row["decided_at"]
        item["decided_by"] = row["decided_by"]
        targets.append(item)

    state_filter = str(request.query_params.get("state") or "ALL").upper()
    decision_filter = str(request.query_params.get("decision") or "ALL").upper()
    sort = str(request.query_params.get("sort") or "score")
    q = str(request.query_params.get("q") or "").strip().lower()

    def visible(item: dict) -> bool:
        if state_filter != "ALL":
            if state_filter == "PAID":
                if item.get("furthest_stage") != "PAID":
                    return False
            elif state_filter not in {str(item.get("score_state") or ""), str(item.get("queue_state") or "")}:
                return False
        if decision_filter != "ALL" and str(item.get("decision") or "PENDING") != decision_filter:
            return False
        if q:
            haystack = " ".join((str(item.get("username") or ""), _location_text(item.get("location")), str(item.get("account_id") or ""))).lower()
            if q not in haystack:
                return False
        return True

    targets = [item for item in targets if visible(item)]
    if sort == "revenue":
        targets.sort(key=lambda x: (-int(x.get("revenue_cents") or 0), -int(x.get("score") or 0)))
    elif sort == "recency":
        targets.sort(key=lambda x: str(x.get("last_activity_at") or ""), reverse=True)
    else:
        targets.sort(key=lambda x: (-int(x.get("score") or 0), str(x.get("username") or "")))

    meta = _load_json(meta_row["snapshot_json"], {}) if meta_row else {}
    warnings = meta.get("validation_warnings", []) if isinstance(meta, dict) else []
    recommendations = meta.get("learning_recommendations", []) if isinstance(meta, dict) else []
    warning_html = "".join(f"<div class='notice warn'><b>{_e(x.get('stage'))}</b> · {_e(x.get('code'))}</div>" for x in warnings if isinstance(x, dict))
    recommendation_html = "".join(
        f"<div class='notice'><b>{_e(x.get('rule'))}</b> · {_e(x.get('current_weight'))} → {_e(x.get('recommended_weight'))} · human approval required</div>"
        for x in recommendations if isinstance(x, dict)
    )
    cards = "".join(_target_card(item) for item in targets) or "<div class='empty'>No targets match these filters.</div>"
    audits = "".join(
        f"<tr><td>{_e(row['created_at'])}</td><td>{_e(row['account_id'])}</td><td>{_e(row['previous_decision'])} → {_e(row['new_decision'])}</td><td>{_e(row['actor'])}</td></tr>"
        for row in audit_rows
    ) or "<tr><td colspan='4'>No operator decisions yet.</td></tr>"

    total = len(rows)
    pending = sum(1 for row in rows if row["decision"] == "PENDING")
    approved = sum(1 for row in rows if row["decision"] == "APPROVED")
    paid = int(meta.get("paid_count") or 0) if isinstance(meta, dict) else 0
    revenue = int(meta.get("revenue_cents") or 0) / 100 if isinstance(meta, dict) else 0

    return HTMLResponse(f"""<!doctype html><html><head><meta name='viewport' content='width=device-width,initial-scale=1'><title>Hunter Operator Console</title><style>
    body{{margin:0;background:#080a08;color:#f1eee7;font-family:Inter,system-ui,sans-serif}}main{{max-width:1180px;margin:auto;padding:24px}}a{{color:#d8ff45}}h1{{font-size:42px;margin:4px 0}}h3{{margin:3px 0;font-size:22px}}.kicker{{font:800 10px monospace;color:#d8ff45;letter-spacing:.12em;text-transform:uppercase}}.muted,.safety{{color:#8f978c;font-size:12px}}.metrics{{display:grid;grid-template-columns:repeat(5,1fr);gap:8px;margin:18px 0}}.metric,.notice,.target-card,.empty{{border:1px solid #30362e;background:#0e110e;padding:14px}}.metric b{{display:block;font-size:25px}}.toolbar{{display:flex;gap:8px;flex-wrap:wrap;margin:14px 0}}select,input,button{{background:#151915;color:#f1eee7;border:1px solid #3b4238;padding:10px}}button{{cursor:pointer;font-weight:800}}button.approve{{background:#d8ff45;color:#080a08;border-color:#d8ff45}}.notice{{margin:7px 0;font-size:12px}}.warn{{border-color:#8e6f22}}.target-card{{margin:12px 0;position:relative}}.target-head{{display:flex;justify-content:space-between;gap:12px}}.score{{font:bold 38px monospace;color:#d8ff45}}.facts,.detail-grid{{display:flex;flex-wrap:wrap;gap:12px;margin:12px 0;font-size:12px}}details{{border-top:1px solid #252b24;padding:10px 0}}summary{{cursor:pointer;font-weight:800}}.rules li{{margin:7px 0}}.rules span{{display:block;color:#91998f;font-size:12px}}.signal{{border-left:2px solid #414a3e;padding:6px 10px;margin:8px 0}}.signal p{{margin:4px 0;font-size:12px;line-height:1.45}}.actions{{display:flex;gap:7px;flex-wrap:wrap}}.pick{{position:absolute;right:14px;top:64px;font-size:11px;color:#8f978c}}table{{width:100%;border-collapse:collapse;font-size:12px}}th,td{{text-align:left;padding:8px;border-bottom:1px solid #252b24}}.section{{margin-top:28px}}@media(max-width:760px){{.metrics{{grid-template-columns:repeat(2,1fr)}}.target-head{{padding-right:0}}.pick{{position:static;display:block;margin-bottom:8px}}h1{{font-size:34px}}}}
    </style></head><body><main><div class='kicker'>Hunter · Sprint 9</div><h1>Operator Console</h1><p class='muted'>Ranked Hunter targets for human review. Approvals are internal decisions only; this console never sends outreach.</p>
    <div class='metrics'><div class='metric'>Targets<b>{total}</b></div><div class='metric'>Pending<b>{pending}</b></div><div class='metric'>Approved<b>{approved}</b></div><div class='metric'>Paid<b>{paid}</b></div><div class='metric'>Revenue<b>${revenue:,.0f}</b></div></div>
    {warning_html}{recommendation_html}
    <form class='toolbar' method='get'><select name='state'>{''.join(f"<option {'selected' if state_filter==x else ''}>{x}</option>" for x in ['ALL','HOT','WARM','ACTIONED','PAID'])}</select><select name='decision'>{''.join(f"<option {'selected' if decision_filter==x else ''}>{x}</option>" for x in ['ALL','PENDING','APPROVED','SUPPRESSED','BAD_FIT'])}</select><select name='sort'>{''.join(f"<option value='{x}' {'selected' if sort==x else ''}>{x}</option>" for x in ['score','recency','revenue'])}</select><input name='q' value='{_e(request.query_params.get('q') or '')}' placeholder='artist or location'><button>Filter</button></form>
    <form id='bulk-form' class='toolbar' method='post' action='/owner/hunter/bulk'><select name='decision'><option value='APPROVED'>Approve selected</option><option value='SUPPRESSED'>Suppress selected</option><option value='BAD_FIT'>Mark bad fit</option></select><button type='submit'>Apply to selected</button><button type='button' onclick="document.querySelectorAll('.pick input').forEach(x=>x.checked=true)">Select visible</button></form>
    {cards}
    <section class='section'><div class='kicker'>Audit trail</div><h2>Recent decisions</h2><table><thead><tr><th>When</th><th>Target</th><th>Decision</th><th>Operator</th></tr></thead><tbody>{audits}</tbody></table></section>
    <p class='muted'>Latest snapshot: {_e(meta_row['updated_at'] if meta_row else 'not ingested yet')}</p></main></body></html>""", headers={"Cache-Control": "no-store"})
