"""Detect Instagram broadcast-channel metadata for Hunter qualification.

Primary path uses the maintained third-party instagrapi public-profile transport
with browser TLS impersonation. Existing direct public JSON/HTML parsing remains
as a fallback. All failures are treated as unknown, never as proof that an artist
has no channel.
"""
from __future__ import annotations

import argparse
import html as html_lib
import json
import re
from dataclasses import asdict, dataclass
from typing import Any, Iterable

import httpx
from bs4 import BeautifulSoup

WEB_PROFILE_URL = "https://www.instagram.com/api/v1/users/web_profile_info/"
PROFILE_URL = "https://www.instagram.com/{username}/"
IG_APP_ID = "936619743392459"

RECOVERY_TERMS = (
    "cancellation", "cancellations", "cancelled", "canceled",
    "last minute", "last-minute", "opening", "openings",
    "availability", "available", "waitlist", "wait list",
    "open spot", "open spots", "appointment", "appointments",
    "same day", "same-day",
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
    for key in ("pinned_channels_info", "broadcast_channel", "broadcast_channels"):
        if key in user and user[key]:
            return user[key]
    return None


def _candidate_channel_dicts(container: Any) -> list[dict]:
    found: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for node in _walk(container):
        title = str(node.get("title") or node.get("name") or node.get("channel_name") or "").strip()
        invite = str(node.get("invite_link") or node.get("invite_url") or node.get("link") or "").strip()
        thread_id = str(node.get("thread_id") or node.get("id") or node.get("thread_v2_id") or node.get("thread_igid") or "").strip()
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
    thread_id = str(node.get("thread_id") or node.get("id") or node.get("thread_v2_id") or node.get("thread_igid") or "").strip() or None
    creator = str(node.get("creator_username") or node.get("username") or (node.get("creator") or {}).get("username") or fallback_creator).strip() or None
    member_count = _int_or_none(node.get("member_count") or node.get("subscriber_count") or node.get("participant_count") or node.get("members_count") or node.get("number_of_members"))
    haystack = " ".join(str(x or "") for x in (title, node.get("description"), node.get("subtitle"))).lower()
    matches = sorted({term for term in RECOVERY_TERMS if term in haystack})
    recovery = bool(matches)
    score = 15
    if recovery:
        score = 50
        if any(term in matches for term in ("cancellation", "cancellations", "cancelled", "canceled")):
            score = 60
        elif any(term in matches for term in ("last minute", "last-minute", "opening", "openings", "open spot", "open spots")):
            score = 55
    return Channel(title=title or "Broadcast channel", invite_link=invite, thread_id=thread_id,
                   member_count=member_count, creator_username=creator, recovery_matches=matches,
                   recovery_signal=recovery, intent_score=score)


def _result(username: str, channels: list[Channel], status: str = "channels_found") -> ProbeResult:
    recovery_count = sum(1 for c in channels if c.recovery_signal)
    return ProbeResult(username=username, ok=True, status=status if channels else "no_channels",
                       channels=channels, channel_count=len(channels),
                       recovery_channel_count=recovery_count,
                       best_intent_score=max((c.intent_score for c in channels), default=0))


def parse_profile_payload(username: str, payload: dict) -> ProbeResult:
    username = _clean_username(username)
    user = (((payload or {}).get("data") or {}).get("user") or {})
    if not isinstance(user, dict) or not user:
        return ProbeResult(username, False, "no_profile_data", [], error="Instagram returned no profile user object")
    container = _channel_container(user)
    if not container:
        return ProbeResult(username, True, "no_channels", [])
    channels = [_classify(node, username) for node in _candidate_channel_dicts(container)]
    return _result(username, channels)


def parse_profile_html(username: str, text: str) -> ProbeResult:
    username = _clean_username(username)
    decoded = html_lib.unescape(text or "")
    soup = BeautifulSoup(decoded, "html.parser")
    nodes: list[dict] = []
    for script in soup.find_all("script"):
        raw = (script.string or script.get_text() or "").strip()
        if not raw or ("channel" not in raw.lower() and "pinned_channels" not in raw.lower()):
            continue
        try:
            obj = json.loads(raw)
        except Exception:
            continue
        for item in _walk(obj):
            for key in ("pinned_channels_info", "broadcast_channel", "broadcast_channels"):
                if item.get(key):
                    nodes.extend(_candidate_channel_dicts(item[key]))
    if not nodes:
        title_pat = re.compile(r'\\?"(?:title|channel_name)\\?"\s*:\s*\\?"([^"\\]+)')
        invite_pat = re.compile(r'https:\\?/\\?/(?:www\\?\.)?instagram\\?\.com\\?/channel\\?/[^"\\\\< ]+', re.I)
        titles = [m.group(1).replace("\\u0026", "&") for m in title_pat.finditer(decoded)]
        links = [m.group(0).replace("\\/", "/") for m in invite_pat.finditer(decoded)]
        for i, title in enumerate(titles):
            nodes.append({"title": title, "invite_link": links[i] if i < len(links) else None})
        if not titles:
            for link in links:
                nodes.append({"title": "Broadcast channel", "invite_link": link})
    channels = [_classify(node, username) for node in _candidate_channel_dicts(nodes)]
    return _result(username, channels, status="channels_found_html")


def parse_instagrapi_user(username: str, user: Any) -> ProbeResult:
    """Normalize instagrapi's User.broadcast_channel objects into Hunter signals."""
    username = _clean_username(username)
    raw_channels = getattr(user, "broadcast_channel", None) or []
    nodes: list[dict] = []
    for channel in raw_channels:
        if hasattr(channel, "model_dump"):
            node = channel.model_dump()
        elif hasattr(channel, "dict"):
            node = channel.dict()
        elif isinstance(channel, dict):
            node = channel
        else:
            node = {k: getattr(channel, k, None) for k in (
                "title", "thread_igid", "subtitle", "invite_link",
                "number_of_members", "creator_username"
            )}
        nodes.append(node)
    channels = [_classify(node, username) for node in _candidate_channel_dicts(nodes)]
    return _result(username, channels, status="channels_found_instagrapi")


def probe_instagrapi(username: str) -> ProbeResult:
    """Use instagrapi's maintained public transport before raw HTTP fallbacks."""
    username = _clean_username(username)
    try:
        from instagrapi import Client
        cl = Client(
            public_transport="curl",
            public_transport_impersonate="chrome136",
            public_request_retries_count=1,
        )
        user = cl.user_info_by_username_gql(username)
        return parse_instagrapi_user(username, user)
    except Exception as exc:
        return ProbeResult(username, False, "instagrapi_unavailable", [],
                           error=f"{type(exc).__name__}: {exc}")


def _headers(username: str) -> dict[str, str]:
    return {
        "x-ig-app-id": IG_APP_ID,
        "user-agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/126 Safari/537.36",
        "accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
        "accept-language": "en-US,en;q=0.9",
        "referer": f"https://www.instagram.com/{username}/",
    }


def probe(username: str, *, timeout: float = 8.0, client: httpx.Client | None = None) -> ProbeResult:
    username = _clean_username(username)

    # Production/default path: use the maintained third-party architecture first.
    # Tests can inject an httpx client and bypass this network adapter.
    third_party_error: str | None = None
    if client is None:
        third = probe_instagrapi(username)
        if third.ok and third.channel_count:
            return third
        if third.ok and third.status == "no_channels":
            # Do not trust an opportunistic no-channel response as definitive; fall through.
            third_party_error = "instagrapi returned no channel metadata"
        else:
            third_party_error = third.error

    own_client = client is None
    client = client or httpx.Client(timeout=timeout, follow_redirects=True)
    headers = _headers(username)
    try:
        response = client.get(WEB_PROFILE_URL, params={"username": username}, headers=headers)
        if response.status_code == 200:
            try:
                parsed = parse_profile_payload(username, response.json())
                if parsed.ok and parsed.channel_count:
                    return parsed
            except (ValueError, json.JSONDecodeError):
                pass
        elif response.status_code == 404:
            return ProbeResult(username, False, "not_found", [], error="profile not found")

        page = client.get(PROFILE_URL.format(username=username), params={"hl": "en"}, headers=headers)
        if page.status_code == 200:
            parsed_html = parse_profile_html(username, page.text)
            if parsed_html.channel_count:
                return parsed_html
            return ProbeResult(username, False, "unknown_no_channel_metadata", [],
                               error=third_party_error or "No channel metadata exposed by available transports")

        codes = {response.status_code, page.status_code}
        if 429 in codes:
            return ProbeResult(username, False, "rate_limited", [], error=third_party_error or f"Instagram returned HTTP {response.status_code}/{page.status_code}")
        if codes & {401, 403}:
            return ProbeResult(username, False, "blocked", [], error=third_party_error or f"Instagram returned HTTP {response.status_code}/{page.status_code}")
        return ProbeResult(username, False, "no_profile_data", [], error=third_party_error or "Instagram returned no usable channel metadata")
    except (httpx.HTTPError, ValueError, json.JSONDecodeError) as exc:
        return ProbeResult(username, False, "error", [], error=f"{type(exc).__name__}: {exc}")
    finally:
        if own_client:
            client.close()


def result_dict(result: ProbeResult) -> dict:
    return asdict(result)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("usernames", nargs="+", help="Instagram usernames, with or without @")
    parser.add_argument("--timeout", type=float, default=8.0)
    parser.add_argument("--out")
    args = parser.parse_args()
    results = [result_dict(probe(name, timeout=args.timeout)) for name in args.usernames]
    payload = {"schema": "empty-chair-hunter-broadcast-probe-v2", "count": len(results),
               "recovery_signal_count": sum(1 for r in results if r.get("recovery_channel_count", 0) > 0),
               "results": results}
    text = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
    if args.out:
        from pathlib import Path
        Path(args.out).write_text(text, encoding="utf-8")
    print(text, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
