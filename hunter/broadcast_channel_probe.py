"""Detect public Instagram broadcast-channel metadata for Hunter qualification.

This module intentionally treats Instagram's public web-profile payload as an
opportunistic signal, not a guaranteed API contract. Failures are returned as
structured results so Hunter can degrade safely when Instagram rate-limits or
changes the response shape.
"""
from __future__ import annotations

import argparse
import json
import re
from dataclasses import asdict, dataclass
from typing import Any, Iterable

import httpx

WEB_PROFILE_URL = "https://www.instagram.com/api/v1/users/web_profile_info/"
IG_APP_ID = "936619743392459"

RECOVERY_TERMS = (
    "cancellation",
    "cancellations",
    "cancelled",
    "canceled",
    "last minute",
    "last-minute",
    "opening",
    "openings",
    "availability",
    "available",
    "waitlist",
    "wait list",
    "open spot",
    "open spots",
    "appointment",
    "appointments",
    "same day",
    "same-day",
)


@dataclass
class Channel:
    title: str
    invite_link: str | None = None
    thread_id: str | None = None
    member_count: int | None = None
    creator_username: str | None = None
    recovery_matches: list[str] | None = None
    recovery_signal: bool = False
    intent_score: int = 0


@dataclass
class ProbeResult:
    username: str
    ok: bool
    status: str
    channels: list[Channel]
    channel_count: int = 0
    recovery_channel_count: int = 0
    best_intent_score: int = 0
    error: str | None = None


def _clean_username(value: str) -> str:
    value = value.strip().lstrip("@").lower()
    if not re.fullmatch(r"[a-z0-9._]{1,30}", value):
        raise ValueError(f"invalid Instagram username: {value!r}")
    return value


def _walk(value: Any) -> Iterable[dict]:
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk(child)


def _channel_container(user: dict) -> Any:
    # Instagram has used more than one wrapper shape for pinned channel data.
    for key in ("pinned_channels_info", "broadcast_channel", "broadcast_channels"):
        if key in user and user[key]:
            return user[key]
    return None


def _candidate_channel_dicts(container: Any) -> list[dict]:
    found: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for node in _walk(container):
        title = str(
            node.get("title")
            or node.get("name")
            or node.get("channel_name")
            or ""
        ).strip()
        invite = str(
            node.get("invite_link")
            or node.get("invite_url")
            or node.get("link")
            or ""
        ).strip()
        thread_id = str(
            node.get("thread_id")
            or node.get("id")
            or node.get("thread_v2_id")
            or ""
        ).strip()
        if not title and not invite:
            continue
        marker = (thread_id, title.lower())
        if marker in seen:
            continue
        seen.add(marker)
        found.append(node)
    return found


def _int_or_none(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _classify(node: dict, fallback_creator: str) -> Channel:
    title = str(node.get("title") or node.get("name") or node.get("channel_name") or "").strip()
    invite = str(node.get("invite_link") or node.get("invite_url") or node.get("link") or "").strip() or None
    thread_id = str(node.get("thread_id") or node.get("id") or node.get("thread_v2_id") or "").strip() or None
    creator = str(
        node.get("creator_username")
        or node.get("username")
        or (node.get("creator") or {}).get("username")
        or fallback_creator
    ).strip() or None
    member_count = _int_or_none(
        node.get("member_count")
        or node.get("subscriber_count")
        or node.get("participant_count")
        or node.get("members_count")
    )
    haystack = " ".join(
        str(x or "")
        for x in (
            title,
            node.get("description"),
            node.get("subtitle"),
        )
    ).lower()
    matches = sorted({term for term in RECOVERY_TERMS if term in haystack})
    recovery = bool(matches)
    # Channel existence itself is useful; explicit cancellation/openings language
    # makes it a top-priority Hunter qualification signal.
    score = 15
    if recovery:
        score = 50
        if any(term in matches for term in ("cancellation", "cancellations", "cancelled", "canceled")):
            score = 60
        elif any(term in matches for term in ("last minute", "last-minute", "opening", "openings", "open spot", "open spots")):
            score = 55
    return Channel(
        title=title or "Broadcast channel",
        invite_link=invite,
        thread_id=thread_id,
        member_count=member_count,
        creator_username=creator,
        recovery_matches=matches,
        recovery_signal=recovery,
        intent_score=score,
    )


def parse_profile_payload(username: str, payload: dict) -> ProbeResult:
    username = _clean_username(username)
    user = (((payload or {}).get("data") or {}).get("user") or {})
    if not isinstance(user, dict) or not user:
        return ProbeResult(username, False, "no_profile_data", [], error="Instagram returned no profile user object")
    container = _channel_container(user)
    if not container:
        return ProbeResult(username, True, "no_channels", [])
    channels = [_classify(node, username) for node in _candidate_channel_dicts(container)]
    recovery_count = sum(1 for c in channels if c.recovery_signal)
    best = max((c.intent_score for c in channels), default=0)
    return ProbeResult(
        username=username,
        ok=True,
        status="channels_found" if channels else "no_channels",
        channels=channels,
        channel_count=len(channels),
        recovery_channel_count=recovery_count,
        best_intent_score=best,
    )


def probe(username: str, *, timeout: float = 8.0, client: httpx.Client | None = None) -> ProbeResult:
    username = _clean_username(username)
    headers = {
        "x-ig-app-id": IG_APP_ID,
        "user-agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/126 Safari/537.36",
        "accept": "*/*",
        "referer": f"https://www.instagram.com/{username}/",
    }
    own_client = client is None
    client = client or httpx.Client(timeout=timeout, follow_redirects=True)
    try:
        response = client.get(WEB_PROFILE_URL, params={"username": username}, headers=headers)
        if response.status_code == 429:
            return ProbeResult(username, False, "rate_limited", [], error="Instagram returned HTTP 429")
        if response.status_code in (401, 403):
            return ProbeResult(username, False, "blocked", [], error=f"Instagram returned HTTP {response.status_code}")
        if response.status_code == 404:
            return ProbeResult(username, False, "not_found", [], error="profile not found")
        response.raise_for_status()
        return parse_profile_payload(username, response.json())
    except (httpx.HTTPError, ValueError, json.JSONDecodeError) as exc:
        return ProbeResult(username, False, "error", [], error=f"{type(exc).__name__}: {exc}")
    finally:
        if own_client:
            client.close()


def result_dict(result: ProbeResult) -> dict:
    data = asdict(result)
    return data


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("usernames", nargs="+", help="Instagram usernames, with or without @")
    parser.add_argument("--timeout", type=float, default=8.0)
    parser.add_argument("--out")
    args = parser.parse_args()

    results = [result_dict(probe(name, timeout=args.timeout)) for name in args.usernames]
    payload = {
        "schema": "empty-chair-hunter-broadcast-probe-v1",
        "count": len(results),
        "recovery_signal_count": sum(1 for r in results if r.get("recovery_channel_count", 0) > 0),
        "results": results,
    }
    text = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
    if args.out:
        from pathlib import Path
        Path(args.out).write_text(text, encoding="utf-8")
    print(text, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
