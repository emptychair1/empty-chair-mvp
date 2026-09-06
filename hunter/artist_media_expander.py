"""Expand Hunter Instagram artist seeds through Meta Business Discovery.

Broad hashtag posts are used to discover active tattoo-artist usernames. For each
resolved seed, this module asks the official Meta Business Discovery surface for
recent public media, then applies Hunter's existing freshness and intent rules.
No login scraping, private content access, or undocumented endpoints are used.
"""
from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path

import httpx

from instagram_hashtag_source import GRAPH_BASE, HIGH_INTENT, age_hours, intent_matches


def _graph_get(client: httpx.Client, path: str, token: str, params: dict) -> dict:
    response = client.get(
        f"{GRAPH_BASE}/{path.lstrip('/')}",
        params={**params, "access_token": token},
    )
    response.raise_for_status()
    payload = response.json()
    if "error" in payload:
        error = payload.get("error") or {}
        raise RuntimeError(str(error.get("message") or "Meta Graph API error"))
    return payload


def business_media(
    client: httpx.Client,
    token: str,
    ig_user_id: str,
    username: str,
    limit: int,
) -> tuple[dict, list[dict]]:
    clean = username.strip().lstrip("@").lower()
    fields = (
        f"business_discovery.username({clean})"
        "{id,username,name,media.limit(" + str(limit) + ")"
        "{id,caption,media_type,permalink,timestamp}}"
    )
    payload = _graph_get(client, ig_user_id, token, {"fields": fields})
    discovered = payload.get("business_discovery") or {}
    media = ((discovered.get("media") or {}).get("data") or [])
    return discovered, list(media)


def seed_usernames(source: dict) -> list[str]:
    usernames: list[str] = []
    seen: set[str] = set()
    rows = list(source.get("artist_seeds") or []) + list(source.get("signals") or [])
    for row in rows:
        username = str(row.get("username") or "").strip().lstrip("@").lower()
        if not username or username in seen:
            continue
        seen.add(username)
        usernames.append(username)
    return usernames


def run(
    *,
    source: dict,
    token: str,
    ig_user_id: str,
    media_limit: int = 25,
    max_artists: int = 40,
    max_age_hours: float = 72.0,
    now: datetime | None = None,
) -> dict:
    now = now or datetime.now(timezone.utc)
    usernames = seed_usernames(source)[:max_artists]
    original_signals = list(source.get("signals") or [])
    original_ids = {str(s.get("media_id") or "") for s in original_signals}
    expanded_by_id: dict[str, dict] = {}
    artists_checked = 0
    artists_supported = 0
    media_scanned = 0
    fresh_media = 0
    intent_hits = 0
    errors: list[dict] = []

    with httpx.Client(timeout=20.0, follow_redirects=True) as client:
        for username in usernames:
            artists_checked += 1
            try:
                discovered, rows = business_media(
                    client, token, ig_user_id, username, media_limit
                )
                if not discovered:
                    errors.append({"username": username, "error": "not_discovered"})
                    continue
                artists_supported += 1
            except Exception as exc:
                errors.append({"username": username, "error": type(exc).__name__})
                continue

            canonical = str(discovered.get("username") or username).strip().lower()
            account_id = discovered.get("id")
            media_scanned += len(rows)
            for row in rows:
                media_id = str(row.get("id") or "")
                if not media_id or media_id in original_ids or media_id in expanded_by_id:
                    continue
                age = age_hours(str(row.get("timestamp") or ""), now)
                if age is None or age > max_age_hours:
                    continue
                fresh_media += 1
                caption = str(row.get("caption") or "")
                matches = intent_matches(caption)
                if not matches:
                    continue
                intent_hits += 1
                expanded_by_id[media_id] = {
                    "source": "instagram_meta_business_discovery",
                    "platform": "instagram",
                    "media_id": media_id,
                    "hashtag": None,
                    "hashtags": [],
                    "caption": caption,
                    "timestamp": row.get("timestamp"),
                    "age_hours": round(age, 2),
                    "permalink": str(row.get("permalink") or ""),
                    "intent_matches": matches,
                    "username": canonical,
                    "account_id": account_id,
                    "resolution_status": "resolved",
                    "resolution_method": "business_discovery",
                    "resolution_confidence": 1.0,
                    "resolution_reason": "official_meta_business_discovery",
                }

    expanded = sorted(expanded_by_id.values(), key=lambda s: s["age_hours"])
    combined = original_signals + expanded
    combined.sort(key=lambda s: float(s.get("age_hours") or 999999))
    metrics = dict(source.get("metrics") or {})
    metrics.update(
        {
            "artist_seeds_available": len(seed_usernames(source)),
            "artists_checked": artists_checked,
            "artists_business_discovery_supported": artists_supported,
            "artist_media_scanned": media_scanned,
            "artist_media_fresh": fresh_media,
            "artist_media_intent_hits": intent_hits,
            "artist_media_new_signals": len(expanded),
            "combined_signal_count": len(combined),
        }
    )

    result = dict(source)
    result["schema"] = "empty-chair-hunter-instagram-expanded-v1"
    result["expanded_at"] = now.isoformat()
    result["business_discovery_media_limit"] = media_limit
    result["business_discovery_max_artists"] = max_artists
    result["metrics"] = metrics
    result["expansion_errors"] = errors
    result["expanded_signals"] = expanded
    result["signals"] = combined
    result["signal_count"] = len(combined)
    result["resolved_count"] = sum(1 for s in combined if s.get("username"))
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", default="hunter-instagram-signals.json")
    parser.add_argument("--out", default="hunter-instagram-expanded-signals.json")
    parser.add_argument("--media-limit", type=int, default=25)
    parser.add_argument("--max-artists", type=int, default=40)
    args = parser.parse_args()

    token = os.getenv("HUNTER_META_ACCESS_TOKEN", "").strip()
    ig_user_id = os.getenv("HUNTER_META_IG_USER_ID", "").strip()
    if not token or not ig_user_id:
        print("hunter artist media expander // skipped // Meta credentials missing")
        return 0

    source = json.loads(Path(args.input).read_text(encoding="utf-8"))
    result = run(
        source=source,
        token=token,
        ig_user_id=ig_user_id,
        media_limit=args.media_limit,
        max_artists=args.max_artists,
    )
    Path(args.out).write_text(
        json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    m = result["metrics"]
    print(
        "hunter artist media expander // "
        f"artists={m['artists_checked']} media={m['artist_media_scanned']} "
        f"fresh={m['artist_media_fresh']} new_signals={m['artist_media_new_signals']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
