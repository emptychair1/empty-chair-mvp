"""Recurring organic Instagram publisher for Empty Chair.

Uses the already-proven Instagram Content Publishing API path and an existing JPEG asset.
No new dependencies. The worker is defensive: every iteration is isolated, and each daily
slot is idempotent in the events table.
"""
from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

import v2_app as core
import v2_instagram_growth as growth

IMAGE_URL = "https://app.tryemptychair.com/static/hero-openings-recovery.jpg"

POSTS = [
    (
        "morning",
        "A CANCELLATION SHOULD NOT BECOME YOUR DAY OFF.\n\n"
        "Empty Chair watches your calendar. When they cancel, we fill the chair.\n\n"
        "7 DAYS FREE // LINK IN BIO",
    ),
    (
        "afternoon",
        "YOUR CLIENT CANCELED. YOUR INCOME DOESN'T HAVE TO.\n\n"
        "Empty Chair finds the replacement, takes the deposit, and puts them on your calendar.\n\n"
        "7 DAYS FREE // LINK IN BIO",
    ),
    (
        "evening",
        "STOP POSTING 'LAST MINUTE OPENING' AND HOPING.\n\n"
        "When they cancel, Empty Chair already knows who to call.\n\n"
        "7 DAYS FREE // LINK IN BIO",
    ),
]

# 10 AM, 2 PM, 6 PM Eastern while daylight saving time is active.
# Exact local-time perfection is less important than three separated daily windows; each
# slot has a two-hour catch-up window so Render restarts do not permanently miss a post.
SLOTS_UTC = {
    "morning": (14, 16),
    "afternoon": (18, 20),
    "evening": (22, 24),
}


def _post(path: str, form: dict[str, str]) -> dict:
    data = urllib.parse.urlencode({**form, "access_token": growth.META_TOKEN}).encode()
    req = urllib.request.Request(
        f"https://graph.instagram.com/{growth.GRAPH_VERSION}/{path.lstrip('/')}",
        data=data,
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            raw = r.read().decode()
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        body = exc.read().decode(errors="replace")[:1200]
        raise RuntimeError(f"HTTP {exc.code}: {body}") from exc


def _get(path: str, params: dict[str, str]) -> dict:
    query = urllib.parse.urlencode({**params, "access_token": growth.META_TOKEN})
    req = urllib.request.Request(
        f"https://graph.instagram.com/{growth.GRAPH_VERSION}/{path.lstrip('/')}?{query}",
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            raw = r.read().decode()
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        body = exc.read().decode(errors="replace")[:1200]
        raise RuntimeError(f"HTTP {exc.code}: {body}") from exc


def _wait_ready(creation_id: str, attempts: int = 12, delay: int = 5) -> None:
    last = {}
    for _ in range(attempts):
        last = _get(creation_id, {"fields": "status_code,status"})
        status = str(last.get("status_code") or "").upper()
        core.event("growth.instagram_media_status", None, {
            "creation_id": creation_id,
            "status": status,
        })
        if status == "FINISHED":
            return
        if status in {"ERROR", "EXPIRED"}:
            raise RuntimeError(f"Instagram media processing failed: {last}")
        time.sleep(delay)
    raise RuntimeError(f"Instagram media not ready after {attempts * delay}s: {last}")


def _slot_key(day: str, slot: str) -> str:
    return f"growth.instagram.organic.{day}.{slot}"


def _already_done(day: str, slot: str) -> bool:
    try:
        row = core.one("SELECT id FROM events WHERE kind=? LIMIT 1", (_slot_key(day, slot),))
        return bool(row)
    except Exception:
        return False


def publish(caption: str, day: str, slot: str) -> str | None:
    if not (growth.META_TOKEN and growth.IG_USER_ID):
        return None
    if _already_done(day, slot):
        return None

    core.event("growth.instagram_publish_attempt", None, {
        "day": day,
        "slot": slot,
        "image_url": IMAGE_URL,
    })

    created = _post(f"{growth.IG_USER_ID}/media", {
        "image_url": IMAGE_URL,
        "caption": caption,
    })
    creation_id = str(created.get("id") or "")
    if not creation_id:
        raise RuntimeError(f"Instagram media container failed: {created}")

    _wait_ready(creation_id)
    published = _post(f"{growth.IG_USER_ID}/media_publish", {"creation_id": creation_id})
    media_id = str(published.get("id") or "")
    if not media_id:
        raise RuntimeError(f"Instagram publish failed: {published}")

    core.event(_slot_key(day, slot), None, {
        "media_id": media_id,
        "slot": slot,
        "caption": caption,
    })
    core.event("growth.instagram_content_published", None, {
        "media_id": media_id,
        "slot": slot,
        "day": day,
    })
    print(f"IG organic post published // {day} // {slot} // {media_id}", flush=True)
    return media_id


def _due_post(now_utc: datetime):
    hour = now_utc.hour
    for slot, start_end in SLOTS_UTC.items():
        start, end = start_end
        # evening's end is represented as 24.
        if start <= hour < end:
            for name, caption in POSTS:
                if name == slot:
                    return slot, caption
    return None, None


def run_once(now_utc: datetime | None = None) -> None:
    now_utc = now_utc or datetime.now(timezone.utc)
    slot, caption = _due_post(now_utc)
    if not slot or not caption:
        return
    publish(caption, now_utc.date().isoformat(), slot)


def _worker():
    # Do not compete with application startup. A publisher failure must never affect boot.
    time.sleep(45)
    while True:
        try:
            run_once()
        except Exception as exc:
            try:
                core.event("growth.instagram_publish_failed", None, {"error": str(exc)[:1500]})
            except Exception:
                pass
            print(f"IG organic publish failed: {exc}", flush=True)
        time.sleep(300)


if core.WORKER_ENABLED:
    threading.Thread(target=_worker, daemon=True, name="instagram-organic-publisher").start()
