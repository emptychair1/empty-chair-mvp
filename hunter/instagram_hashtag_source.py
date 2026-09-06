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

# Meta hashtag discovery is intentionally bounded. The default pool stays under
# the rolling unique-hashtag ceiling while combining sparse high-intent tags,
# broad tattoo inventory, and major-market discovery. Intent still comes from
# the caption, not from the hashtag itself.
HIGH_INTENT_TAGS = (
    "tattooopenings",
    "tattoocancellation",
    "tattoocancellations",
    "tattooavailability",
    "lastminutetattoo",
    "walkintattoo",
    "booksopen",
    "tattooflash",
)
BROAD_INVENTORY_TAGS = (
    "tattoo",
    "tattoos",
    "tattooartist",
    "tattooartists",
    "tattooing",
    "tattooshop",
    "tattoostudio",
    "traditionaltattoo",
    "blackworktattoo",
    "finelinetattoo",
)
MARKET_TAGS = (
    "atlantatattoo",
    "nashvilletattoo",
    "austintattoo",
    "denvertattoo",
    "chicagotattoo",
    "nyctattoo",
    "losangelestattoo",
    "sandiegotattoo",
    "portlandtattoo",
    "seattletattoo",
)
DEFAULT_TAGS = HIGH_INTENT_TAGS + BROAD_INVENTORY_TAGS + MARKET_TAGS

HIGH_INTENT = (
    "cancellation",
    "cancelation",
    "cancelled",
    "canceled",
    "rescheduled",
    "reschedule",
    "no show",
    "no-show",
    "opening today",
    "opening tomorrow",
    "opening tonight",
    "available today",
    "available tomorrow",
    "available tonight",
    "last minute",
    "last-minute",
    "spot opened",
    "spot opened up",
    "spot available",
    "appointment opened",
    "appointment opened up",
    "appointment available",
    "gap in my schedule",
    "gap in the schedule",
    "free today",
    "free tomorrow",
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


def run(
    *,
    token: str,
    ig_user_id: str,
    tags: tuple[str, ...] = DEFAULT_TAGS,
    limit: int = 50,
    max_age_hours: float = 72.0,
    resolve_authors: bool = True,
    max_resolutions: int = 75,
    now: datetime | None = None,
) -> dict:
    now = now or datetime.now(timezone.utc)
    errors: list[dict] = []
    media_by_id: dict[str, dict] = {}
    media_scanned = 0
    fresh_media = 0
    duplicate_hits = 0

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

            media_scanned += len(rows)
            for row in rows:
                media_id = str(row.get("id") or "")
                if not media_id:
                    continue
                age = age_hours(str(row.get("timestamp") or ""), now)
                if age is None or age > max_age_hours:
                    continue
                fresh_media += 1
                caption = str(row.get("caption") or "")
                matches = intent_matches(caption)
                if not matches:
                    continue

                existing = media_by_id.get(media_id)
                if existing:
                    duplicate_hits += 1
                    if tag not in existing["hashtags"]:
                        existing["hashtags"].append(tag)
                    existing["intent_matches"] = sorted(set(existing["intent_matches"]) | set(matches))
                    continue

                media_by_id[media_id] = {
                    "source": "instagram_meta_hashtag",
                    "platform": "instagram",
                    "media_id": media_id,
                    "hashtag": tag,
                    "hashtags": [tag],
                    "caption": caption,
                    "timestamp": row.get("timestamp"),
                    "age_hours": round(age, 2),
                    "permalink": str(row.get("permalink") or ""),
                    "intent_matches": matches,
                    "username": None,
                    "resolution_status": "not_attempted",
                    "resolution_method": None,
                    "resolution_confidence": 0.0,
                    "resolution_reason": None,
                }

    candidates = sorted(media_by_id.values(), key=lambda s: s["age_hours"])
    resolutions_attempted = 0
    for signal in candidates:
        permalink = signal["permalink"]
        if not resolve_authors or not permalink:
            continue
        if resolutions_attempted >= max_resolutions:
            signal["resolution_status"] = "deferred_limit"
            signal["resolution_reason"] = "max_resolutions_reached"
            continue
        resolutions_attempted += 1
        resolution = resolve(permalink)
        signal["username"] = resolution.username if resolution.status == "resolved" else None
        signal["resolution_status"] = resolution.status
        signal["resolution_method"] = resolution.method
        signal["resolution_confidence"] = resolution.confidence
        signal["resolution_reason"] = resolution.reason

    resolved_count = sum(1 for s in candidates if s["username"])
    return {
        "schema": "empty-chair-hunter-instagram-meta-v1",
        "generated_at": now.isoformat(),
        "freshness_hours": max_age_hours,
        "tags": list(tags),
        "tag_count": len(tags),
        "per_tag_limit": limit,
        "metrics": {
            "media_scanned": media_scanned,
            "fresh_media": fresh_media,
            "intent_matches": len(candidates) + duplicate_hits,
            "unique_candidate_posts": len(candidates),
            "duplicate_hits": duplicate_hits,
            "resolutions_attempted": resolutions_attempted,
            "resolved_count": resolved_count,
            "unresolved_count": len(candidates) - resolved_count,
        },
        "signal_count": len(candidates),
        "resolved_count": resolved_count,
        "errors": errors,
        "signals": candidates,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default="hunter-instagram-signals.json")
    parser.add_argument("--tag", action="append", dest="tags")
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument("--max-resolutions", type=int, default=75)
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
        max_resolutions=args.max_resolutions,
        resolve_authors=not args.no_resolve,
    )
    Path(args.out).write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    metrics = result["metrics"]
    print(
        "hunter instagram source // "
        f"scanned={metrics['media_scanned']} fresh={metrics['fresh_media']} "
        f"candidates={metrics['unique_candidate_posts']} resolved={metrics['resolved_count']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
