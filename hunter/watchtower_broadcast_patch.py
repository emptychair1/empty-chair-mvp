"""High-volume Instagram broadcast-channel collector.

The authenticated Direct/private API is the primary path. Browser navigation is used only
when the private transport itself fails, so accounts with no broadcast channel do not pay
the expensive profile-navigation cost.
"""
from __future__ import annotations

from instagrapi import Client


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
    sid = _sessionid(context)
    if not sid:
        return None, "browser sessionid unavailable"
    try:
        client = Client(request_timeout=2)
        if not client.login_by_sessionid(sid):
            return None, "private API session login returned false"
        target_id = client.user_id_from_username(username)
        raw_channels = client.direct_channels(user_id=int(target_id), thread_subtypes=[29])
        channels = _metadata_channels(raw_channels, service)

        for channel in channels:
            thread_id = str(channel.get("thread_id") or "").strip()
            if not thread_id:
                continue
            try:
                response = client.private_request(
                    f"direct_v2/threads/{thread_id}/",
                    params={"visual_message_return_type": "unseen", "direction": "older", "limit": "20"},
                )
                thread = response.get("thread") or {}
                items = thread.get("items") or []
                texts: list[str] = []
                _collect_text(items[:20], texts)
                message_score, message_matches = service._broadcast_score("\n".join(texts))
                combined = sorted(set(channel.get("recovery_matches") or []) | set(message_matches))
                channel["recovery_matches"] = combined
                channel["recovery_signal"] = bool(combined)
                channel["intent_score"] = max(int(channel.get("intent_score") or 0), int(message_score or 0))
                channel["messages_observed"] = len(items[:20])
                channel["recent_text_items"] = len(texts)
                if message_matches:
                    channel["evidence"] = [
                        text for text in texts if any(term in text.lower() for term in message_matches)
                    ][:5]
            except Exception as exc:
                channel["thread_read_error"] = f"{exc.__class__.__name__}: {exc}"[:500]

        matches = sorted({m for c in channels for m in c.get("recovery_matches", [])})
        recovery_count = sum(1 for c in channels if c.get("recovery_signal"))
        status = (
            "recovery_broadcast_channel_found" if recovery_count
            else "broadcast_channel_found" if channels
            else "unknown_no_broadcast_channel_visible"
        )
        return {
            "schema": service.SCHEMA,
            "username": username,
            "collector": "instagram_broadcast_channel",
            "status": status,
            "intent_score": max((int(c.get("intent_score") or 0) for c in channels), default=0),
            "matches": matches,
            "channels": channels[:20],
            "channel_count": len(channels),
            "recovery_channel_count": recovery_count,
            "observed_at": service.utcnow(),
            "detection_path": "instagram_private_direct_v2",
            "private_api_authenticated": True,
            "target_user_id": str(target_id),
        }, None
    except Exception as exc:
        return None, f"{exc.__class__.__name__}: {exc}"[:500]


def install(service) -> None:
    original = service.probe_broadcast_channel

    def fast_probe(page, context, username):
        # Successful private API results are authoritative even when the target has no
        # channel. This is the key high-volume optimization: no profile navigation for
        # normal negative results.
        private_result, private_error = _direct_channel_probe(context, username, service)
        if private_result is not None:
            service.persist_browser_state(context)
            return private_result

        # Browser navigation is now an exception path, not the default second pass.
        result = original(page, context, username)
        if private_error:
            result["private_api_error"] = private_error
        result["detection_path"] = result.get("detection_path") or "authenticated_browser_fallback"
        return result

    service.probe_broadcast_channel = fast_probe
