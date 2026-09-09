"""Observe Instagram broadcast channels through the authenticated Direct/private API.

The browser session remains Watchtower's source of authentication. We hand its sessionid
into instagrapi, query Direct channel subtype 29, then read the recent channel thread.
The previous authenticated DOM/profile collector remains as a fallback only.
"""
from __future__ import annotations

import html as html_lib
import re
from urllib.parse import urlparse

from instagrapi import Client

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
        creator = node.get("creator_username") or node.get("creator") or node.get("admin_username")
        if isinstance(creator, dict):
            creator = creator.get("username")
        creator = str(creator or "").strip().lstrip("@")
        looks_channel = bool(
            thread_id
            or href
            or (title and any(k in node for k in (
                "number_of_members", "member_count", "subscriber_count", "thread_subtype", "is_broadcast_channel"
            )))
        )
        if href and not _real_channel_url(href):
            href = ""
        if not looks_channel:
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
            "creator_username": creator[:100],
            "member_count": member_count,
            "intent_score": score,
            "recovery_matches": matches,
            "recovery_signal": bool(matches),
        })
    return channels


def _result(service, username, channels, detection_path, **extra):
    all_matches = sorted({m for c in channels for m in c.get("recovery_matches", [])})
    recovery_count = sum(1 for c in channels if c.get("recovery_signal"))
    payload = {
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
    payload.update(extra)
    return payload


def _sessionid(context) -> str:
    try:
        for cookie in context.cookies("https://www.instagram.com"):
            if cookie.get("name") == "sessionid" and cookie.get("value"):
                return str(cookie["value"])
    except Exception:
        pass
    return ""


def _collect_text(value, out: list[str]) -> None:
    if len(out) >= 80:
        return
    if isinstance(value, dict):
        for key, child in value.items():
            if key in {"text", "message", "title", "link_text", "subtitle"} and isinstance(child, str):
                clean = " ".join(child.split()).strip()
                if clean and clean not in out:
                    out.append(clean[:1000])
            else:
                _collect_text(child, out)
    elif isinstance(value, list):
        for child in value:
            _collect_text(child, out)


def _direct_channel_probe(context, username, service):
    """Read subtype-29 Direct channels using the existing authenticated session."""
    sid = _sessionid(context)
    if not sid:
        return None, "browser sessionid unavailable"
    try:
        client = Client()
        if not client.login_by_sessionid(sid):
            return None, "private API session login returned false"
        target_id = client.user_id_from_username(username)
        raw_channels = client.direct_channels(user_id=int(target_id), thread_subtypes=[29])
        channels = _metadata_channels(raw_channels, service)
        if not channels:
            return {
                "schema": service.SCHEMA,
                "username": username,
                "collector": "instagram_broadcast_channel",
                "status": "unknown_no_broadcast_channel_visible",
                "intent_score": 0,
                "matches": [],
                "channels": [],
                "channel_count": 0,
                "recovery_channel_count": 0,
                "observed_at": service.utcnow(),
                "detection_path": "instagram_private_direct_v2",
                "private_api_authenticated": True,
                "target_user_id": str(target_id),
            }, None

        for channel in channels:
            thread_id = str(channel.get("thread_id") or "").strip()
            if not thread_id:
                continue
            try:
                response = client.private_request(
                    f"direct_v2/threads/{thread_id}/",
                    params={
                        "visual_message_return_type": "unseen",
                        "direction": "older",
                        "limit": "20",
                    },
                )
                thread = response.get("thread") or {}
                items = thread.get("items") or []
                texts: list[str] = []
                _collect_text(items[:20], texts)
                message_blob = "\n".join(texts)
                message_score, message_matches = service._broadcast_score(message_blob)
                combined_matches = sorted(set(channel.get("recovery_matches") or []) | set(message_matches))
                channel["recovery_matches"] = combined_matches
                channel["recovery_signal"] = bool(combined_matches)
                channel["intent_score"] = max(int(channel.get("intent_score") or 0), int(message_score or 0))
                channel["messages_observed"] = len(items[:20])
                channel["recent_text_items"] = len(texts)
                if message_matches:
                    matching = [text for text in texts if any(term in text.lower() for term in message_matches)]
                    channel["evidence"] = matching[:5]
            except Exception as exc:
                channel["thread_read_error"] = f"{exc.__class__.__name__}: {exc}"[:500]

        return _result(
            service,
            username,
            channels,
            "instagram_private_direct_v2",
            private_api_authenticated=True,
            target_user_id=str(target_id),
        ), None
    except Exception as exc:
        return None, f"{exc.__class__.__name__}: {exc}"[:500]


def install(service) -> None:
    original = service.probe_broadcast_channel

    def hardened(page, context, username):
        # Primary path: Direct/private API. This mirrors Instagram's channel surface
        # instead of trying to infer broadcast membership from profile-page markup.
        private_result, private_error = _direct_channel_probe(context, username, service)
        if private_result and private_result.get("status") != "unknown_no_broadcast_channel_visible":
            service.persist_browser_state(context)
            return private_result

        # Keep the proven authenticated browser collector as a fallback for accounts
        # where Instagram rejects a browser session on the mobile/private transport.
        result = original(page, context, username)
        if private_result:
            result["private_api_authenticated"] = private_result.get("private_api_authenticated", False)
            result["private_api_channel_count"] = private_result.get("channel_count", 0)
            result["private_api_target_user_id"] = private_result.get("target_user_id")
        if private_error:
            result["private_api_error"] = private_error
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

        captured = []
        def capture(response):
            if len(captured) >= 30:
                return
            url = (response.url or "").lower()
            if "graphql" not in url and "/api/v1/users/" not in url and "profile" not in url:
                return
            try:
                ctype = (response.headers.get("content-type") or "").lower()
                if "json" not in ctype:
                    return
                captured.append(response.json())
            except Exception:
                return
        try:
            page.on("response", capture)
            page.reload(wait_until="domcontentloaded", timeout=45000)
            page.wait_for_timeout(int(service.SETTLE_SECONDS * 1000))
            for payload in captured:
                metadata = _metadata_channels(payload, service)
                if metadata:
                    return _result(service, username, metadata, "authenticated_profile_network")
            result["captured_profile_payloads"] = len(captured)
        except Exception as exc:
            result["network_capture_error"] = f"{exc.__class__.__name__}: {exc}"[:500]
        finally:
            try:
                page.remove_listener("response", capture)
            except Exception:
                pass

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
