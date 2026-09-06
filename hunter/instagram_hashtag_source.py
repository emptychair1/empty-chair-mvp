"""Official Meta Instagram hashtag discovery source for Hunter.

The adapter uses Graph API hashtag search + recent_media for fresh captions,
timestamps, and permalinks. Author resolution is delegated to the public visual
resolver because the hashtag edge does not expose username for this app setup.
No Instagram login/session scraping is used.
"""
from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path

import httpx

from instagram_visual_resolver import resolve

GRAPH_VERSION = os.getenv("HUNTER_META_GRAPH_VERSION", "v26.0")
GRAPH_BASE = f"https://graph.facebook.com/{GRAPH_VERSION}"
DEFAULT_TAGS = (
    "tattooopenings",
    "tattoocancellation",
    "tattoocancellations",
    "tattooavailability",
    "lastminutetattoo",
    "walkintattoo",
    "booksopen",
    "tattooflash",
)
HIGH_INTENT = (
    "cancellation",
    "cancelled",
    "canceled",
    "rescheduled",
    "no show",
    "no-show",
    "opening today",
    "opening tomorrow",
    "available today",
    "available tomorrow",
    "last minute",
    "last-minute",
    "spot opened",
    "spot available",
    "walk in",
    "walk-in",
)


def _graph_get(client: httpx.Client, path: str, token: str, params: dict) -> dict:
    response = client.get(f"{GRAPH_BASE}/{path.lstrip('/')}", params={**params, "access_token": token})
    response.raise_for_status()
    payload = response.json()
    if "error" in payload:
        raise RuntimeError(payload["error"].get("message", "Meta Graph API error"))
    return payload


def hashtag_id(client: httpx.Client, token: str, ig_user_id: str, tag: str) -> str | None:
    payload = _graph_get(client, "ig_hashtag_search", token, {"user_id": ig_user_id, "q": tag.lstrip("#")})
    data = payload.get("data") or []
    return str(data[0]["id"]) if data else None


def recent_media(client: httpx.Client, token: str, ig_user_id: str, tag_id: str, limit: int) -> list[dict]:
    payload = _graph_get(
        client,
        f"{tag_id}/recent_media",
        token,
        {
            "user_id": ig_user_id,
            "fields": "id,caption,permalink,timestamp",
            "limit": str(limit),
        },
    )
    return list(payload.get("data") or [])


def age_hours(timestamp: str, now: datetime) -> float | None:
    try:
        parsed = datetime.strptime(timestamp, "%Y-%m-%dT%H:%M:%S%z").astimezone(timezone.utc)
    except (TypeError, ValueError):
        return None
    return max(0.0, (now - parsed).total_seconds() / 3600)


def intent_matches(caption: str) -> list[str]:
    lower = (caption or "").lower()
    return [phrase for phrase in HIGH_INTENT if phrase in lower]


def run(*, token: str, ig_user_id: str, tags: tuple[str, ...] = DEFAULT_TAGS, limit: int = 25,
        max_age_hours: float = 72.0, resolve_authors: bool = True, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    signals: list[dict] = []
    errors: list[dict] = []
    seen: set[str] = set()
    with httpx.Client(timeout=20.0, follow_redirects=True) as client:
        for tag in tags:
            try:
                tag_id = hashtag_id(client, token, ig_user_id, tag)
                if not tag_id:
                    continue
                rows = recent_media(client, token, ig_user_id, tag_id, limit)
            except Exception as exc:
                errors.append({"tag": tag, "error": type(exc).__name__})
                continue

            for row in rows:
                media_id = str(row.get("id") or "")
                if not media_id or media_id in seen:
                    continue
                seen.add(media_id)
                age = age_hours(str(row.get("timestamp") or ""), now)
                if age is None or age > max_age_hours:
                    continue
                caption = str(row.get("caption") or "")
                matches = intent_matches(caption)
                if not matches:
                    continue
                permalink = str(row.get("permalink") or "")
                author = None
                resolution = None
                if resolve_authors and permalink:
                    resolution = resolve(permalink)
                    author = resolution.username if resolution.status == "resolved" else None
                signals.append({
                    "source": "instagram_meta_hashtag",
                    "platform": "instagram",
                    "media_id": media_id,
                    "hashtag": tag,
                    "caption": caption,
                    "timestamp": row.get("timestamp"),
                    "age_hours": round(age, 2),
                    "permalink": permalink,
                    "intent_matches": matches,
                    "username": author,
                    "resolution_status": resolution.status if resolution else "not_attempted",
                    "resolution_method": resolution.method if resolution else None,
                    "resolution_confidence": resolution.confidence if resolution else 0.0,
                    "resolution_reason": resolution.reason if resolution else None,
                })

    return {
        "schema": "empty-chair-hunter-instagram-meta-v1",
        "generated_at": now.isoformat(),
        "freshness_hours": max_age_hours,
        "tags": list(tags),
        "signal_count": len(signals),
        "resolved_count": sum(1 for s in signals if s["username"]),
        "errors": errors,
        "signals": sorted(signals, key=lambda s: s["age_hours"]),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default="hunter-instagram-signals.json")
    parser.add_argument("--tag", action="append", dest="tags")
    parser.add_argument("--limit", type=int, default=25)
    parser.add_argument("--no-resolve", action="store_true")
    args = parser.parse_args()
    token = os.getenv("HUNTER_META_ACCESS_TOKEN", "").strip()
    ig_user_id = os.getenv("HUNTER_META_IG_USER_ID", "").strip()
    if not token or not ig_user_id:
        print("hunter instagram source // skipped // HUNTER_META_ACCESS_TOKEN or HUNTER_META_IG_USER_ID missing")
        return 0
    result = run(
        token=token,
        ig_user_id=ig_user_id,
        tags=tuple(args.tags) if args.tags else DEFAULT_TAGS,
        limit=args.limit,
        resolve_authors=not args.no_resolve,
    )
    Path(args.out).write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"hunter instagram source // signals={result['signal_count']} resolved={result['resolved_count']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
