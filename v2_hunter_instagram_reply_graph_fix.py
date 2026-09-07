"""Route Hunter Instagram reply sync through the Instagram Graph host.

The app authenticates Instagram messaging with Instagram Login. The core Instagram
messaging patch already uses graph.instagram.com, but the Hunter reply-sync module
accidentally hard-coded graph.facebook.com for subscription, sender lookup, and
conversation reconciliation. Patch those reads/writes before the reply worker wakes.
"""
from __future__ import annotations

import json
import urllib.parse
import urllib.request

import v2_hunter_instagram_reply_sync as sync
import v2_instagram_growth as growth


def graph_get(path: str, params: dict[str, str] | None = None) -> dict:
    if not growth.META_TOKEN:
        return {}
    query = dict(params or {})
    query["access_token"] = growth.META_TOKEN
    url = (
        f"https://graph.instagram.com/{growth.GRAPH_VERSION}/{path.lstrip('/')}?"
        f"{urllib.parse.urlencode(query)}"
    )
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as response:
        raw = response.read().decode()
    return json.loads(raw) if raw else {}


def graph_post(path: str, fields: dict[str, str]) -> dict:
    if not growth.META_TOKEN:
        return {}
    data = urllib.parse.urlencode({**fields, "access_token": growth.META_TOKEN}).encode()
    req = urllib.request.Request(
        f"https://graph.instagram.com/{growth.GRAPH_VERSION}/{path.lstrip('/')}",
        data=data,
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as response:
        raw = response.read().decode()
    return json.loads(raw) if raw else {}


sync._graph_get = graph_get
sync._graph_post = graph_post

print("Hunter Instagram reply Graph host fix loaded // graph.instagram.com", flush=True)
