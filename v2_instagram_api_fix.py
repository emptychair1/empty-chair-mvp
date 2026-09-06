"""Use the Instagram Login graph host for Instagram messaging calls."""
from __future__ import annotations

import json
import urllib.parse
import urllib.request

import v2_instagram_growth as growth


def graph_post(path: str, form: dict[str, str]) -> dict:
    data = urllib.parse.urlencode({**form, "access_token": growth.META_TOKEN}).encode()
    req = urllib.request.Request(
        f"https://graph.instagram.com/{growth.GRAPH_VERSION}/{path.lstrip('/')}",
        data=data,
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        raw = r.read().decode()
        return json.loads(raw) if raw else {}


growth.graph_post = graph_post
