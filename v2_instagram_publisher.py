"""Recurring branded Instagram publisher for the Empty Chair organic growth loop."""
from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

import v2_app as core
import v2_instagram_content as content
import v2_instagram_growth as growth

POST_INTERVAL_SECONDS = 8 * 60 * 60
STARTUP_DELAY_SECONDS = 20


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


def _wait_ready(creation_id: str, attempts: int = 18, delay: int = 5) -> None:
    last = {}
    for _ in range(attempts):
        last = _get(creation_id, {"fields": "status_code,status"})
        status = str(last.get("status_code") or "").upper()
        core.event("growth.instagram_media_status", None, {"creation_id": creation_id, "status": status})
        if status == "FINISHED":
            return
        if status in {"ERROR", "EXPIRED"}:
            raise RuntimeError(f"Instagram media processing failed: {last}")
        time.sleep(delay)
    raise RuntimeError(f"Instagram media not ready: {last}")


def _recently_published() -> bool:
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=7)).isoformat()
    try:
        row = core.one("SELECT id FROM growth_content WHERE status='PUBLISHED' AND published_at>=? LIMIT 1", (cutoff,))
        return bool(row)
    except Exception:
        return False


def publish_next() -> str | None:
    if not (growth.META_TOKEN and growth.IG_USER_ID):
        return None
    if _recently_published():
        return None

    item = content.next_content()
    if not item:
        content.seed(60)
        item = content.next_content()
    if not item:
        return None

    content_id = str(item["id"])
    image_url = f"{core.BASE_URL}/growth/card/{content_id}.png"
    caption = str(item.get("caption") or "")
    core.event("growth.instagram_publish_attempt", None, {"content_id": content_id, "image_url": image_url})

    created = _post(f"{growth.IG_USER_ID}/media", {"image_url": image_url, "caption": caption})
    creation_id = str(created.get("id") or "")
    if not creation_id:
        raise RuntimeError(f"Instagram media container failed: {created}")
    _wait_ready(creation_id)

    published = _post(f"{growth.IG_USER_ID}/media_publish", {"creation_id": creation_id})
    media_id = str(published.get("id") or "")
    if not media_id:
        raise RuntimeError(f"Instagram publish failed: {published}")

    content.mark_published(content_id, media_id)
    print(f"IG organic post published: {media_id}", flush=True)
    return media_id


def worker():
    time.sleep(STARTUP_DELAY_SECONDS)
    while True:
        try:
            publish_next()
        except Exception as exc:
            core.event("growth.instagram_publish_failed", None, {"error": str(exc)[:1500]})
            print(f"IG organic publish failed: {exc}", flush=True)
        time.sleep(30 * 60 if _recently_published() else 10 * 60)


if core.WORKER_ENABLED:
    threading.Thread(target=worker, daemon=True, name="instagram-organic-publisher").start()
