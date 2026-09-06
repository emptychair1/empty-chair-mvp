"""Ensure the connected Instagram professional account is subscribed to comment webhooks."""
from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

import v2_app as core
import v2_instagram_growth as growth


def _subscribe() -> None:
    if not (growth.META_TOKEN and growth.IG_USER_ID):
        growth.log(None, "instagram.subscription_skipped", {"token": bool(growth.META_TOKEN), "ig_user_id": bool(growth.IG_USER_ID)})
        return
    data = urllib.parse.urlencode({
        "subscribed_fields": "comments",
        "access_token": growth.META_TOKEN,
    }).encode()
    req = urllib.request.Request(
        f"https://graph.instagram.com/{growth.GRAPH_VERSION}/{growth.IG_USER_ID}/subscribed_apps",
        data=data,
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            raw = response.read().decode()
            payload = json.loads(raw) if raw else {}
        growth.log(None, "instagram.subscription_ok", {"response": payload})
        print(f"IG comment webhook subscription OK: {payload}", flush=True)
    except urllib.error.HTTPError as exc:
        body = exc.read().decode(errors="replace")[:1500]
        growth.log(None, "instagram.subscription_failed", {"status": exc.code, "body": body})
        print(f"IG comment webhook subscription failed HTTP {exc.code}: {body}", flush=True)
    except Exception as exc:
        growth.log(None, "instagram.subscription_failed", {"error": str(exc)[:1500]})
        print(f"IG comment webhook subscription failed: {exc}", flush=True)


def _startup() -> None:
    time.sleep(5)
    _subscribe()


if core.WORKER_ENABLED:
    threading.Thread(target=_startup, daemon=True, name="instagram-webhook-subscription").start()
