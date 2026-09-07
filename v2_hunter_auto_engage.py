"""Official Instagram auto-engagement for Hunter.

After the founder marks a Hunter target HANDLED (the existing manual-follow handoff),
queue one conservative engagement attempt. After a short delay, Hunter uses Meta's
official Instagram Graph API to discover the target's latest eligible public professional
media and like at most one post/reel.

Requirements at runtime:
- Facebook Login-backed Instagram token
- instagram_manage_engagement permission
- Instagram professional account id

No browser automation, session cookies, private endpoints, automatic follows, comments,
or DMs are used here.
"""
from __future__ import annotations

import json
import os
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

import v2_app as core
import v2_hunter_operator as hunter

GRAPH_VERSION = os.getenv("META_GRAPH_VERSION", "v24.0").strip()
ACCESS_TOKEN = (
    os.getenv("INSTAGRAM_ENGAGEMENT_ACCESS_TOKEN", "").strip()
    or os.getenv("INSTAGRAM_ACCESS_TOKEN", "").strip()
)
IG_USER_ID = (
    os.getenv("INSTAGRAM_ENGAGEMENT_IG_USER_ID", "").strip()
    or os.getenv("INSTAGRAM_USER_ID", "").strip()
)
ENABLED = os.getenv("HUNTER_AUTO_ENGAGE_ENABLED", "true").strip().lower() in {"1", "true", "yes", "on"}
DELAY_SECONDS = max(60, int(os.getenv("HUNTER_AUTO_ENGAGE_DELAY_SECONDS", "120")))
WORKER_SECONDS = max(30, int(os.getenv("HUNTER_AUTO_ENGAGE_WORKER_SECONDS", "60")))
DAILY_CAP = max(1, min(50, int(os.getenv("HUNTER_AUTO_ENGAGE_DAILY_CAP", "30"))))

TABLE = """CREATE TABLE IF NOT EXISTS hunter_auto_engagement (
    account_id TEXT PRIMARY KEY,
    username TEXT NOT NULL,
    followed_at TEXT NOT NULL,
    eligible_after TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'PENDING',
    media_id TEXT,
    media_permalink TEXT,
    attempted_at TEXT,
    liked_at TEXT,
    detail TEXT,
    updated_at TEXT NOT NULL
)"""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime | None = None) -> str:
    return (value or _now()).isoformat()


def _ensure(db: core.DB) -> None:
    hunter.ensure_tables(db)
    db.execute(TABLE)
    db.commit()


def _graph_get(path: str, params: dict[str, str]) -> dict:
    if not ACCESS_TOKEN:
        raise RuntimeError("Instagram engagement access token is not configured")
    query = urllib.parse.urlencode({**params, "access_token": ACCESS_TOKEN})
    url = f"https://graph.facebook.com/{GRAPH_VERSION}/{path.lstrip('/')}?{query}"
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=20) as response:
        raw = response.read().decode()
    return json.loads(raw) if raw else {}


def _graph_post(path: str, fields: dict[str, str]) -> dict:
    if not ACCESS_TOKEN:
        raise RuntimeError("Instagram engagement access token is not configured")
    data = urllib.parse.urlencode({**fields, "access_token": ACCESS_TOKEN}).encode()
    req = urllib.request.Request(
        f"https://graph.facebook.com/{GRAPH_VERSION}/{path.lstrip('/')}",
        data=data,
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=20) as response:
        raw = response.read().decode()
    return json.loads(raw) if raw else {}


def _error_text(exc: Exception) -> str:
    if isinstance(exc, urllib.error.HTTPError):
        try:
            body = exc.read().decode(errors="replace")
        except Exception:
            body = ""
        return f"HTTP {exc.code}: {body[:1200]}"
    return str(exc)[:1200]


def _latest_public_media(username: str) -> dict | None:
    """Resolve the latest discoverable Feed/Reel media for a public professional account."""
    if not IG_USER_ID:
        raise RuntimeError("Instagram engagement user id is not configured")
    handle = str(username or "").strip().lstrip("@").lower()
    if not handle:
        return None
    fields = (
        f"business_discovery.username({handle})"
        "{media.limit(5){id,timestamp,media_type,permalink}}"
    )
    payload = _graph_get(IG_USER_ID, {"fields": fields})
    business = payload.get("business_discovery") or {}
    items = (business.get("media") or {}).get("data") or []
    eligible = [
        item for item in items
        if isinstance(item, dict)
        and item.get("id")
        and str(item.get("media_type") or "").upper() in {"IMAGE", "VIDEO", "CAROUSEL_ALBUM", "REELS"}
    ]
    if not eligible:
        return None
    eligible.sort(key=lambda item: str(item.get("timestamp") or ""), reverse=True)
    return eligible[0]


def _daily_liked_count(db: core.DB) -> int:
    prefix = _now().date().isoformat() + "%"
    row = db.execute(
        f"SELECT COUNT(*) AS n FROM hunter_auto_engagement WHERE status='LIKED' AND liked_at LIKE ?",
        (prefix,),
    ).fetchone()
    return int(dict(row).get("n") or 0) if row else 0


def enqueue(account_id: str) -> None:
    if not ENABLED:
        return
    db = core.DB()
    try:
        _ensure(db)
        row = db.execute(
            "SELECT username,decided_at FROM hunter_operator_targets WHERE account_id=? AND decision='HANDLED'",
            (account_id,),
        ).fetchone()
        if not row:
            return
        item = dict(row)
        username = str(item.get("username") or "").strip().lstrip("@").lower()
        if not username:
            return
        followed_at = str(item.get("decided_at") or _iso())
        eligible_after = _iso(_now() + timedelta(seconds=DELAY_SECONDS))
        stamp = _iso()
        db.execute(
            f"""INSERT INTO hunter_auto_engagement
                (account_id,username,followed_at,eligible_after,status,updated_at)
                VALUES(?,?,?,?,?,?)
                ON CONFLICT(account_id) DO NOTHING""",
            (account_id, username, followed_at, eligible_after, "PENDING", stamp),
        )
        db.commit()
    finally:
        db.close()


def _set_result(
    db: core.DB,
    account_id: str,
    *,
    status: str,
    media_id: str | None = None,
    permalink: str | None = None,
    detail: str | None = None,
    liked: bool = False,
) -> None:
    stamp = _iso()
    db.execute(
        f"""UPDATE hunter_auto_engagement
            SET status=?,media_id=?,media_permalink=?,attempted_at=?,liked_at=?,detail=?,updated_at=?
            WHERE account_id=?""",
        (
            status,
            media_id,
            permalink,
            stamp,
            stamp if liked else None,
            detail,
            stamp,
            account_id,
        ),
    )
    db.commit()


def process_one(account_id: str) -> str:
    db = core.DB()
    try:
        _ensure(db)
        row = db.execute(
            "SELECT * FROM hunter_auto_engagement WHERE account_id=?",
            (account_id,),
        ).fetchone()
        if not row:
            return "MISSING"
        item = dict(row)
        if str(item.get("status") or "") != "PENDING":
            return str(item.get("status") or "")
        if _daily_liked_count(db) >= DAILY_CAP:
            return "DAILY_CAP"

        username = str(item.get("username") or "")
        try:
            media = _latest_public_media(username)
            if not media:
                _set_result(
                    db,
                    account_id,
                    status="NO_ELIGIBLE_MEDIA",
                    detail="No public professional Feed/Reel media was discoverable through the official API.",
                )
                return "NO_ELIGIBLE_MEDIA"
            media_id = str(media.get("id") or "")
            permalink = str(media.get("permalink") or "") or None
            result = _graph_post(f"{IG_USER_ID}/likes", {"media_id": media_id})
            if result.get("success") is False:
                _set_result(
                    db,
                    account_id,
                    status="FAILED",
                    media_id=media_id,
                    permalink=permalink,
                    detail=json.dumps(result, separators=(",", ":"))[:1200],
                )
                return "FAILED"
            _set_result(
                db,
                account_id,
                status="LIKED",
                media_id=media_id,
                permalink=permalink,
                detail="Official Meta instagram_manage_engagement like succeeded.",
                liked=True,
            )
            print(f"Hunter auto engage // liked @{username} media {media_id}", flush=True)
            return "LIKED"
        except Exception as exc:
            detail = _error_text(exc)
            lower = detail.lower()
            blocked = any(
                marker in lower
                for marker in (
                    "instagram_manage_engagement",
                    "permission",
                    "facebook login",
                    "platform_beta_restricted",
                    "requires advanced access",
                )
            )
            status = "PERMISSION_REQUIRED" if blocked else "FAILED"
            _set_result(db, account_id, status=status, detail=detail)
            print(f"Hunter auto engage // @{username} {status}: {detail}", flush=True)
            return status
    except Exception:
        try:
            db.raw.rollback()
        except Exception:
            pass
        raise
    finally:
        db.close()


def process_due() -> dict[str, int]:
    stats = {"pending": 0, "processed": 0, "liked": 0}
    if not ENABLED:
        return stats
    db = core.DB()
    try:
        _ensure(db)
        rows = db.execute(
            """SELECT account_id FROM hunter_auto_engagement
               WHERE status='PENDING' AND eligible_after<=?
               ORDER BY eligible_after ASC
               LIMIT 5""",
            (_iso(),),
        ).fetchall()
        stats["pending"] = len(rows)
    finally:
        db.close()
    for row in rows:
        stats["processed"] += 1
        if process_one(str(dict(row).get("account_id") or "")) == "LIKED":
            stats["liked"] += 1
        time.sleep(2)
    return stats


def status_counts() -> dict[str, int]:
    db = core.DB()
    try:
        _ensure(db)
        result: dict[str, int] = {}
        for row in db.execute(
            "SELECT status,COUNT(*) AS n FROM hunter_auto_engagement GROUP BY status"
        ).fetchall():
            item = dict(row)
            result[str(item.get("status") or "UNKNOWN")] = int(item.get("n") or 0)
        return result
    finally:
        db.close()


def _worker() -> None:
    time.sleep(10)
    while True:
        try:
            stats = process_due()
            if stats["processed"]:
                print(f"Hunter auto engage worker // {stats}", flush=True)
        except Exception as exc:
            print(f"Hunter auto engage worker failed: {exc}", flush=True)
        time.sleep(WORKER_SECONDS)


# Queue an official engagement attempt whenever the existing Hunter decision path records
# HANDLED. This preserves the current manual-follow handoff and does not change SKIPPED.
_original_set_decision = hunter.set_decision


def _set_decision_with_auto_engage(account_id: str, decision: str, actor: str, *, bulk: bool = False) -> bool:
    changed = _original_set_decision(account_id, decision, actor, bulk=bulk)
    if changed and str(decision or "").upper() == "HANDLED":
        try:
            enqueue(account_id)
        except Exception as exc:
            print(f"Hunter auto engage enqueue failed for {account_id}: {exc}", flush=True)
    return changed


hunter.set_decision = _set_decision_with_auto_engage

if core.WORKER_ENABLED and ENABLED:
    threading.Thread(target=_worker, daemon=True, name="hunter-auto-engage").start()

print(
    f"Hunter official auto engage loaded // enabled={ENABLED} // delay={DELAY_SECONDS}s // daily_cap={DAILY_CAP}",
    flush=True,
)
