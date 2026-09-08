"""Harden the authenticated browser broadcast-channel collector without changing Watchtower's public API."""
from __future__ import annotations

import html as html_lib
import re
from urllib.parse import urlparse

CHANNEL_URL_RE = re.compile(
    r"(?:https?://(?:www\.)?instagram\.com/channel/[^\s\"'<>\\]+|https?://ig\.me/j/[^\s\"'<>\\]+|/channel/[A-Za-z0-9._?=&%/-]+)",
    re.I,
)


def _real_channel_url(value: str) -> bool:
    value = (value or "").strip()
    if not value:
        return False
    try:
        parsed = urlparse(value if value.startswith("http") else f"https://www.instagram.com{value}")
    except Exception:
        return False
    host = parsed.netloc.lower()
    path = parsed.path.rstrip("/")
    if host.endswith("ig.me"):
        return path.startswith("/j/") and len(path.split("/j/", 1)[-1]) >= 4
    if not host.endswith("instagram.com") or not path.startswith("/channel/"):
        return False
    slug = path.split("/channel/", 1)[-1]
    if not slug or slug.lower().endswith(".php") or slug.lower() in {"reconnect", "reconnect.php"}:
        return False
    return len(slug) >= 4


def _walk(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk(child)


def _metadata_channels(payload, service):
    channels = []
    seen = set()
    for node in _walk(payload):
        if not isinstance(node, dict):
            continue
        title = str(node.get("title") or node.get("name") or node.get("channel_name") or "").strip()
        href = str(node.get("invite_link") or node.get("invite_url") or node.get("link") or "").strip()
        thread_id = str(node.get("thread_id") or node.get("thread_v2_id") or node.get("thread_igid") or "").strip()
        looks_channel = bool(title and any(k in node for k in ("thread_id", "thread_v2_id", "thread_igid", "invite_link", "number_of_members", "member_count", "subscriber_count")))
        if href and not _real_channel_url(href):
            href = ""
        if not href and not looks_channel:
            continue
        marker = thread_id or href or title.lower()
        if not marker or marker in seen:
            continue
        seen.add(marker)
        score, matches = service._broadcast_score(title or "Broadcast channel")
        member_count = node.get("member_count") or node.get("subscriber_count") or node.get("participant_count") or node.get("number_of_members")
        try:
            member_count = int(member_count) if member_count is not None else None
        except Exception:
            member_count = None
        channels.append({
            "title": (title or "Broadcast channel")[:240],
            "href": href[:1000],
            "thread_id": thread_id[:200],
            "member_count": member_count,
            "intent_score": score,
            "recovery_matches": matches,
            "recovery_signal": bool(matches),
        })
    return channels


def _result(service, username, channels, detection_path):
    all_matches = sorted({m for c in channels for m in c.get("recovery_matches", [])})
    recovery_count = sum(1 for c in channels if c.get("recovery_signal"))
    return {
        "schema": service.SCHEMA,
        "username": username,
        "collector": "instagram_broadcast_channel",
        "status": "recovery_broadcast_channel_found" if recovery_count else "broadcast_channel_found",
        "intent_score": max((int(c.get("intent_score") or 0) for c in channels), default=0),
        "matches": all_matches,
        "channels": channels[:20],
        "channel_count": len(channels),
        "recovery_channel_count": recovery_count,
        "observed_at": service.utcnow(),
        "detection_path": detection_path,
    }


def install(service) -> None:
    original = service.probe_broadcast_channel

    def hardened(page, context, username):
        result = original(page, context, username)
        if result.get("status") != "unknown_no_broadcast_channel_visible":
            return result
        if not service.authenticated(page, context):
            return result

        visible = service.visible_text(page)
        try:
            markup = page.content()
        except Exception:
            markup = ""
        normalized = html_lib.unescape(markup or "").replace("\\u002F", "/").replace("\\/", "/")

        candidates = []
        try:
            candidates = page.locator("a,button,[role='link']").evaluate_all(
                """els => els.map(el => ({
                    href: el.href || el.getAttribute('href') || '',
                    title: (el.innerText || el.getAttribute('aria-label') || el.getAttribute('title') || '').trim()
                })).filter(x => /channel/i.test(x.title) || /instagram\\.com\\/channel\\/|ig\\.me\\/j\\//i.test(x.href))"""
            )
        except Exception:
            candidates = []

        found_links = []
        seen_links = set()
        for match in CHANNEL_URL_RE.findall(normalized):
            href = match if match.startswith("http") else f"https://www.instagram.com{match}"
            if _real_channel_url(href) and href not in seen_links:
                seen_links.add(href)
                found_links.append(href)

        channels = []
        seen = set()
        for item in candidates:
            href = str((item or {}).get("href") or "").strip()
            title = str((item or {}).get("title") or "").strip() or "Broadcast channel"
            if href and not _real_channel_url(href):
                continue
            marker = href or title.lower()
            if not marker or marker in seen:
                continue
            seen.add(marker)
            score, matches = service._broadcast_score(title)
            channels.append({
                "title": title[:240], "href": href[:1000], "intent_score": score,
                "recovery_matches": matches, "recovery_signal": bool(matches),
            })

        visible_score, visible_matches = service._broadcast_score(visible)
        for href in found_links:
            if href in seen:
                continue
            seen.add(href)
            channels.append({
                "title": "Broadcast channel", "href": href[:1000],
                "intent_score": visible_score or 15,
                "recovery_matches": visible_matches,
                "recovery_signal": bool(visible_matches),
            })

        if channels:
            return _result(service, username, channels, "authenticated_dom_hardened")

        # Profile DOM often omits broadcast-channel cards. Ask Instagram's own web
        # profile transport from inside the already-authenticated browser session,
        # so cookies and browser identity stay identical to normal web navigation.
        try:
            payload = page.evaluate(
                """async (username) => {
                    const url = '/api/v1/users/web_profile_info/?username=' + encodeURIComponent(username);
                    const response = await fetch(url, {
                        credentials: 'include',
                        headers: {'x-ig-app-id': '936619743392459', 'accept': 'application/json'}
                    });
                    let body = null;
                    try { body = await response.json(); } catch (_) {}
                    return {status: response.status, body};
                }""",
                username,
            )
            metadata = _metadata_channels((payload or {}).get("body") or {}, service)
            if metadata:
                return _result(service, username, metadata, "authenticated_web_profile_info")
            result["metadata_http_status"] = (payload or {}).get("status")
        except Exception as exc:
            result["metadata_error"] = f"{exc.__class__.__name__}: {exc}"[:500]

        text_lower = (visible or "").lower()
        if "broadcast channel" in text_lower and visible_matches:
            return _result(service, username, [{
                "title": "Broadcast channel", "href": "",
                "intent_score": visible_score,
                "recovery_matches": visible_matches,
                "recovery_signal": True,
            }], "authenticated_visible_text")

        result["page_text_sample"] = visible[:500]
        return result

    service.probe_broadcast_channel = hardened
