"""Harden the authenticated browser broadcast-channel collector without changing Watchtower's public API."""
from __future__ import annotations

import html as html_lib
import re

CHANNEL_URL_RE = re.compile(
    r"(?:https?://(?:www\.)?instagram\.com/channel/[^\s\"'<>\\]+|https?://ig\.me/j/[^\s\"'<>\\]+|/channel/[A-Za-z0-9._?=&%/-]+)",
    re.I,
)


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
            if href not in seen_links:
                seen_links.add(href)
                found_links.append(href)

        channels = []
        seen = set()
        for item in candidates:
            href = str((item or {}).get("href") or "").strip()
            title = str((item or {}).get("title") or "").strip() or "Broadcast channel"
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

        text_lower = (visible or "").lower()
        if not channels and "channel" in text_lower and visible_matches:
            channels.append({
                "title": "Broadcast channel", "href": "",
                "intent_score": visible_score,
                "recovery_matches": visible_matches,
                "recovery_signal": True,
            })

        if not channels:
            result["page_text_sample"] = visible[:500]
            return result

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
            "detection_path": "authenticated_dom_hardened",
        }

    service.probe_broadcast_channel = hardened
