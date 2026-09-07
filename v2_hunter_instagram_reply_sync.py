"""Automatically sync inbound Instagram replies into Hunter.

Uses only official Meta Graph API/webhook surfaces. The existing /webhooks/instagram
verification endpoint remains unchanged; this module replaces only the POST handler so
comment growth events and inbound messaging events share the same signed webhook.

A background conversations reconciliation pass is a backup for missed webhooks. It
never sends DMs, follows accounts, or performs actions on Instagram.
"""
from __future__ import annotations

import json
import os
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

from fastapi import Request
from fastapi.responses import JSONResponse, Response

import v2_app as core
import v2_hunter_operator as hunter
import v2_hunter_outreach_runtime_fix as runtime
import v2_instagram_growth as growth

REPLIED = "REPLIED"
POLL_SECONDS = max(60, int(os.getenv("HUNTER_IG_REPLY_POLL_SECONDS", "180")))

EVENT_TABLE = """CREATE TABLE IF NOT EXISTS hunter_instagram_reply_events (
    message_id TEXT PRIMARY KEY,
    sender_ig_id TEXT,
    username TEXT,
    account_id TEXT,
    message_text TEXT,
    message_created_at TEXT,
    matched INTEGER NOT NULL DEFAULT 0,
    source TEXT NOT NULL,
    created_at TEXT NOT NULL
)"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ensure(db: core.DB) -> None:
    runtime.ensure_runtime_outreach(db)
    db.execute(EVENT_TABLE)
    db.commit()


def _graph_get(path: str, params: dict[str, str] | None = None) -> dict:
    if not growth.META_TOKEN:
        return {}
    query = dict(params or {})
    query["access_token"] = growth.META_TOKEN
    url = f"https://graph.facebook.com/{growth.GRAPH_VERSION}/{path.lstrip('/')}?{urllib.parse.urlencode(query)}"
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as response:
        raw = response.read().decode()
    return json.loads(raw) if raw else {}


def _graph_post(path: str, fields: dict[str, str]) -> dict:
    if not growth.META_TOKEN:
        return {}
    data = urllib.parse.urlencode({**fields, "access_token": growth.META_TOKEN}).encode()
    req = urllib.request.Request(
        f"https://graph.facebook.com/{growth.GRAPH_VERSION}/{path.lstrip('/')}",
        data=data,
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as response:
        raw = response.read().decode()
    return json.loads(raw) if raw else {}


def subscribe_messaging() -> bool:
    """Subscribe the connected professional account to comment + messaging webhooks."""
    if not (growth.META_TOKEN and growth.IG_USER_ID):
        print("Hunter IG reply sync // Meta token/user id not configured", flush=True)
        return False
    try:
        result = _graph_post(
            f"{growth.IG_USER_ID}/subscribed_apps",
            {"subscribed_fields": "comments,messages,messaging_postbacks"},
        )
        print(f"Hunter IG reply webhook subscription // {result}", flush=True)
        return bool(result.get("success", True))
    except Exception as exc:
        print(f"Hunter IG reply webhook subscription failed: {exc}", flush=True)
        return False


def _profile_for_sender(sender_id: str) -> dict:
    if not sender_id:
        return {}
    try:
        return _graph_get(sender_id, {"fields": "id,username,name"})
    except Exception:
        return {}


def _clean_username(value: str | None) -> str:
    return str(value or "").strip().lstrip("@").lower()


def _parse_time(value) -> str:
    if value is None or value == "":
        return _now()
    if isinstance(value, (int, float)):
        # Meta webhook timestamps are commonly milliseconds.
        seconds = float(value)
        if seconds > 10_000_000_000:
            seconds /= 1000.0
        try:
            return datetime.fromtimestamp(seconds, timezone.utc).isoformat()
        except Exception:
            return _now()
    text = str(value)
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(timezone.utc).isoformat()
    except Exception:
        return text


def _match_account(db: core.DB, username: str, sender_id: str) -> dict | None:
    username = _clean_username(username)
    candidates = []
    if username:
        candidates.append(username)
    if sender_id:
        # Some snapshots may already contain the scoped Instagram id.
        row = db.execute(
            """SELECT t.account_id,t.username,o.stage,o.dm_sent_at
               FROM hunter_operator_targets t
               JOIN hunter_outreach_v2 o ON o.account_id=t.account_id
               WHERE o.stage='WAITING_REPLY'
                 AND (t.account_id=? OR t.snapshot_json LIKE ?)
               LIMIT 1""",
            (f"ig:{sender_id}", f"%{sender_id}%"),
        ).fetchone()
        if row:
            return dict(row)
    for handle in candidates:
        row = db.execute(
            """SELECT t.account_id,t.username,o.stage,o.dm_sent_at
               FROM hunter_operator_targets t
               JOIN hunter_outreach_v2 o ON o.account_id=t.account_id
               WHERE o.stage='WAITING_REPLY' AND LOWER(t.username)=?
               LIMIT 1""",
            (handle,),
        ).fetchone()
        if row:
            return dict(row)
    return None


def record_inbound_message(
    *,
    message_id: str,
    sender_id: str,
    username: str = "",
    text: str = "",
    created_at=None,
    source: str,
) -> bool:
    """Persist one inbound message and advance a matching WAITING_REPLY artist."""
    message_id = str(message_id or "").strip()
    sender_id = str(sender_id or "").strip()
    if not message_id or not sender_id:
        return False
    if sender_id == str(growth.IG_USER_ID):
        return False

    db = core.DB()
    try:
        _ensure(db)
        if db.execute("SELECT message_id FROM hunter_instagram_reply_events WHERE message_id=?", (message_id,)).fetchone():
            return False

        profile = _profile_for_sender(sender_id) if not username else {}
        resolved_username = _clean_username(username or profile.get("username"))
        message_time = _parse_time(created_at)
        target = _match_account(db, resolved_username, sender_id)
        matched = False
        account_id = None

        if target:
            account_id = str(target.get("account_id") or "")
            dm_sent_at = str(target.get("dm_sent_at") or "")
            # Never treat an older conversation message as a reply to a newer Hunter DM.
            if not dm_sent_at or message_time >= dm_sent_at:
                stamp = _now()
                db.execute(
                    f"UPDATE {runtime.TABLE} SET stage=?,replied_at=?,updated_at=? WHERE account_id=? AND stage='WAITING_REPLY'",
                    (REPLIED, message_time, stamp, account_id),
                )
                matched = True

        db.execute(
            """INSERT INTO hunter_instagram_reply_events
               (message_id,sender_ig_id,username,account_id,message_text,message_created_at,matched,source,created_at)
               VALUES(?,?,?,?,?,?,?,?,?)""",
            (
                message_id,
                sender_id,
                resolved_username or None,
                account_id,
                str(text or "")[:1000],
                message_time,
                1 if matched else 0,
                source,
                _now(),
            ),
        )
        db.commit()
        if matched:
            print(f"Hunter IG reply matched // @{resolved_username or sender_id} -> {account_id}", flush=True)
        return matched
    except Exception:
        db.raw.rollback()
        raise
    finally:
        db.close()


def _message_fields(message: dict, *, default_sender: str = "", default_username: str = "") -> tuple[str, str, str, str, object]:
    sender = message.get("sender") or message.get("from") or {}
    sender_id = str(sender.get("id") or message.get("sender_id") or default_sender or "")
    username = str(sender.get("username") or default_username or "")
    payload = message.get("message") if isinstance(message.get("message"), dict) else message
    message_id = str(payload.get("mid") or payload.get("id") or message.get("mid") or message.get("id") or "")
    text = str(payload.get("text") or payload.get("message") or message.get("text") or "")
    timestamp = payload.get("timestamp") or payload.get("created_time") or message.get("timestamp") or message.get("created_time")
    return message_id, sender_id, username, text, timestamp


def process_webhook_payload(payload: dict) -> int:
    matched = 0
    for entry in payload.get("entry", []) or []:
        # Instagram Messaging webhooks commonly deliver an entry.messaging array.
        for event in entry.get("messaging", []) or []:
            message = event.get("message") or {}
            if message.get("is_echo"):
                continue
            mid, sender_id, username, text, timestamp = _message_fields(
                {**message, "sender": event.get("sender") or {}, "timestamp": event.get("timestamp")}
            )
            if record_inbound_message(
                message_id=mid,
                sender_id=sender_id,
                username=username,
                text=text,
                created_at=timestamp,
                source="webhook",
            ):
                matched += 1

        # Some webhook versions expose message content as changes[field=messages].
        for change in entry.get("changes", []) or []:
            if str(change.get("field") or "") not in {"messages", "messaging"}:
                continue
            value = change.get("value") or {}
            items = value if isinstance(value, list) else [value]
            for item in items:
                mid, sender_id, username, text, timestamp = _message_fields(item)
                if record_inbound_message(
                    message_id=mid,
                    sender_id=sender_id,
                    username=username,
                    text=text,
                    created_at=timestamp,
                    source="webhook_change",
                ):
                    matched += 1
    return matched


def _conversation_messages(conversation: dict) -> list[dict]:
    messages = conversation.get("messages") or {}
    if isinstance(messages, dict):
        return list(messages.get("data") or [])
    return list(messages or [])


def reconcile_once() -> dict[str, int]:
    """Backup reconciliation using the official conversations/messages read endpoints."""
    stats = {"conversations": 0, "messages": 0, "matched": 0}
    if not (growth.META_TOKEN and growth.IG_USER_ID):
        return stats
    try:
        payload = _graph_get(
            f"{growth.IG_USER_ID}/conversations",
            {
                "platform": "instagram",
                "limit": "50",
                "fields": "id,updated_time,participants,messages.limit(10){id,created_time,from,to,message}",
            },
        )
    except Exception as exc:
        print(f"Hunter IG reply poll failed: {exc}", flush=True)
        return stats

    for conversation in payload.get("data", []) or []:
        stats["conversations"] += 1
        participants = (conversation.get("participants") or {}).get("data", []) or []
        by_id = {str(p.get("id") or ""): p for p in participants}
        for message in _conversation_messages(conversation):
            sender = message.get("from") or {}
            sender_id = str(sender.get("id") or "")
            if not sender_id or sender_id == str(growth.IG_USER_ID):
                continue
            stats["messages"] += 1
            participant = by_id.get(sender_id) or {}
            mid, _, username, text, timestamp = _message_fields(
                message,
                default_sender=sender_id,
                default_username=str(participant.get("username") or ""),
            )
            if record_inbound_message(
                message_id=mid,
                sender_id=sender_id,
                username=username,
                text=text,
                created_at=timestamp,
                source="poll",
            ):
                stats["matched"] += 1
    return stats


def _worker() -> None:
    time.sleep(8)
    subscribe_messaging()
    while True:
        try:
            stats = reconcile_once()
            if stats["matched"]:
                print(f"Hunter IG reply poll // {stats}", flush=True)
        except Exception as exc:
            print(f"Hunter IG reply reconcile error: {exc}", flush=True)
        time.sleep(POLL_SECONDS)


# Replace only the POST webhook. Keep growth.instagram_verify as the GET verification route.
for route in list(core.app.router.routes):
    if getattr(route, "path", None) == "/webhooks/instagram" and "POST" in (getattr(route, "methods", set()) or set()):
        core.app.router.routes.remove(route)


@core.app.post("/webhooks/instagram")
async def instagram_webhook_with_hunter_replies(request: Request):
    body = await request.body()
    signature = request.headers.get("x-hub-signature-256")
    if not growth.valid_signature(body, signature):
        try:
            growth.log(None, "instagram.webhook_rejected", {"bytes": len(body), "signature_present": bool(signature)})
        except Exception:
            pass
        return Response(status_code=403)

    try:
        payload = json.loads(body or b"{}")
        fields = []
        for entry in payload.get("entry", []) or []:
            for change in entry.get("changes", []) or []:
                fields.append(str(change.get("field") or ""))
        growth.log(
            None,
            "instagram.webhook_received",
            {
                "object": payload.get("object"),
                "entries": len(payload.get("entry", []) or []),
                "fields": fields[:20],
                "messaging_events": sum(len(entry.get("messaging", []) or []) for entry in payload.get("entry", []) or []),
                "bytes": len(body),
            },
        )

        # Preserve the existing comment -> private trial reply behavior.
        for entry in payload.get("entry", []) or []:
            for change in entry.get("changes", []) or []:
                if change.get("field") in {"comments", "live_comments"}:
                    growth.handle_comment(change.get("value") or {})

        matched = process_webhook_payload(payload)
        if matched:
            growth.log(None, "hunter.instagram_replies_matched", {"count": matched})
    except Exception as exc:
        try:
            growth.log(None, "instagram.webhook_error", {"error": str(exc)[:1000]})
        except Exception:
            pass
        print(f"IG webhook/Hunter reply error: {exc}", flush=True)
    return JSONResponse({"ok": True})


if core.WORKER_ENABLED:
    threading.Thread(target=_worker, daemon=True, name="hunter-instagram-reply-sync").start()

print("Hunter automatic Instagram reply sync loaded", flush=True)
