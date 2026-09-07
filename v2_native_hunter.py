"""Native Hunter swipe queue.

The native app can fetch one public Instagram artist at a time and record a founder
choice. A FOLLOWED swipe opens Instagram for the human to tap Follow; Empty Chair
never performs the Instagram follow action itself.
"""
from __future__ import annotations

from fastapi import Header, HTTPException, Request

import v2_app as core
import v2_hunter_operator as hunter
from v2_hunter_operator_phone_auth import is_admin_artist
from v2_native_calendar import _bearer
from hunter.operator_auth import actor_identity


def _native_founder(authorization: str | None):
    device = _bearer(authorization)
    artist = core.one("SELECT * FROM artists WHERE id=?", (device["artist_id"],))
    if not is_admin_artist(artist):
        raise HTTPException(404, "Not found")
    return device, artist


def _stats(db: core.DB) -> dict:
    today = hunter._today_prefix()
    return {
        "remaining": int(db.execute(
            "SELECT COUNT(*) AS n FROM hunter_operator_targets WHERE decision='PENDING' AND username IS NOT NULL"
        ).fetchone()["n"]),
        "handled_today": int(db.execute(
            "SELECT COUNT(*) AS n FROM hunter_operator_targets WHERE decision='HANDLED' AND decided_at LIKE ?",
            (today + "%",),
        ).fetchone()["n"]),
        "skipped_today": int(db.execute(
            "SELECT COUNT(*) AS n FROM hunter_operator_targets WHERE decision='SKIPPED' AND decided_at LIKE ?",
            (today + "%",),
        ).fetchone()["n"]),
    }


@core.app.get("/native/hunter/next")
def native_hunter_next(authorization: str | None = Header(None)):
    _native_founder(authorization)
    db = core.DB()
    try:
        hunter.ensure_tables(db)
        row = db.execute(
            """SELECT * FROM hunter_operator_targets
               WHERE decision='PENDING' AND username IS NOT NULL AND profile_url IS NOT NULL
               ORDER BY first_ingested_at ASC, score DESC, username ASC
               LIMIT 1"""
        ).fetchone()
        stats = _stats(db)
    finally:
        db.close()
    if not row:
        return {"ok": True, "target": None, "stats": stats}
    target = hunter._display_target(dict(row))
    return {
        "ok": True,
        "target": {
            "account_id": str(target.get("account_id") or ""),
            "username": str(target.get("username") or "").lstrip("@"),
            "name": str(target.get("name") or ""),
            "market": str(target.get("market") or ""),
            "source": str(target.get("activity_source") or ""),
            "profile_url": str(target.get("profile_url") or ""),
        },
        "stats": stats,
    }


@core.app.post("/native/hunter/{account_id}/decision")
async def native_hunter_decision(
    account_id: str,
    request: Request,
    authorization: str | None = Header(None),
):
    device, artist = _native_founder(authorization)
    body = await request.json()
    decision = str(body.get("decision") or "").upper()
    if decision not in {"HANDLED", "SKIPPED"}:
        raise HTTPException(400, "decision must be HANDLED or SKIPPED")
    actor = actor_identity(artist) or f"native:{device['platform']}"
    try:
        changed = hunter.set_decision(account_id, decision, actor)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    if not changed:
        raise HTTPException(404, "Target not found")
    return {"ok": True, "decision": decision}
