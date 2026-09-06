"""One-time launch publisher for the Empty Chair Instagram growth loop."""
from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

import v2_app as core
import v2_instagram_growth as growth

TEST_IMAGE_URL = "https://tryemptychair.com/static/01_artist.png"
TEST_CAPTION = "EMPTY CHAIR // TEST\n\nTATTOO ARTIST?\nCOMMENT CHAIR\n\nWHEN THEY CANCEL, WE FILL THE CHAIR."


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


def already_published() -> bool:
    try:
        return bool(core.one("SELECT id FROM events WHERE kind='growth.instagram_launch_posted' LIMIT 1"))
    except Exception:
        return False


def _wait_ready(creation_id: str, attempts: int = 12, delay: int = 5) -> None:
    last = {}
    for _ in range(attempts):
        last = _get(creation_id, {"fields": "status_code,status"})
        status = str(last.get("status_code") or "").upper()
        core.event("growth.instagram_media_status", None, {"creation_id": creation_id, "status": status, "raw": last})
        if status == "FINISHED":
            return
        if status in {"ERROR", "EXPIRED"}:
            raise RuntimeError(f"Instagram media processing failed: {last}")
        time.sleep(delay)
    raise RuntimeError(f"Instagram media not ready after {attempts * delay}s: {last}")


def publish_test_post() -> str | None:
    core.event("growth.instagram_launch_attempt", None, {"token": bool(growth.META_TOKEN), "ig_user_id": bool(growth.IG_USER_ID), "image_url": TEST_IMAGE_URL})
    if not (growth.META_TOKEN and growth.IG_USER_ID) or already_published():
        return None
    created = _post(f"{growth.IG_USER_ID}/media", {"image_url": TEST_IMAGE_URL, "caption": TEST_CAPTION})
    creation_id = str(created.get("id") or "")
    if not creation_id:
        raise RuntimeError(f"Instagram media container failed: {created}")
    _wait_ready(creation_id)
    published = _post(f"{growth.IG_USER_ID}/media_publish", {"creation_id": creation_id})
    media_id = str(published.get("id") or "")
    if not media_id:
        raise RuntimeError(f"Instagram publish failed: {published}")
    core.event("growth.instagram_launch_posted", None, {"media_id": media_id, "caption": TEST_CAPTION})
    print(f"IG launch post published: {media_id}", flush=True)
    return media_id


def _startup():
    time.sleep(15)
    try:
        publish_test_post()
    except Exception as exc:
        core.event("growth.instagram_launch_failed", None, {"error": str(exc)[:1500]})
        print(f"IG launch publish failed: {exc}", flush=True)


if core.WORKER_ENABLED:
    threading.Thread(target=_startup, daemon=True, name="instagram-launch-publisher").start()
