"""Build a high-volume bucket of tattoo artists with measurable empty-chair pain.

This stays on the official Meta hashtag surfaces for discovery. Broad hashtag
inventory identifies artist candidates; visible public post headers resolve authors;
Meta Business Discovery is then attempted for recent professional-account media.
Only pain evidence <=72h can put an artist in the pain-fit bucket.
"""
from __future__ import annotations

import argparse
import json
import os
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

import httpx

from instagram_visual_resolver import resolve

GRAPH_VERSION = os.getenv("HUNTER_META_GRAPH_VERSION", "v26.0")
GRAPH_BASE = f"https://graph.facebook.com/{GRAPH_VERSION}"

# Reuse the same bounded 28-tag pool as the direct-intent collector so Hunter
# does not churn through Meta's rolling unique-hashtag allowance.
DEFAULT_TAGS = (
    "tattooopenings", "tattoocancellation", "tattoocancellations", "tattooavailability",
    "lastminutetattoo", "walkintattoo", "booksopen", "tattooflash",
    "tattoo", "tattoos", "tattooartist", "tattooartists", "tattooing", "tattooshop",
    "tattoostudio", "traditionaltattoo", "blackworktattoo", "finelinetattoo",
    "atlantatattoo", "nashvilletattoo", "austintattoo", "denvertattoo", "chicagotattoo",
    "nyctattoo", "losangelestattoo", "sandiegotattoo", "portlandtattoo", "seattletattoo",
)

DISRUPTION_PATTERNS = (
    r"\bcancell?ation\b", r"\bcancel(?:led|ed)\b", r"\bno[- ]show\b",
    r"\breschedul(?:e|ed|ing)\b", r"\bappointment fell through\b",
)
URGENT_CAPACITY_PATTERNS = (
    r"\bavailable (?:today|tomorrow|tonight)\b", r"\bopening (?:today|tomorrow|tonight)\b",
    r"\bfree (?:today|tomorrow|tonight)\b", r"\blast[- ]minute (?:spot|slot|appointment|opening)\b",
    r"\bspot (?:just )?opened(?: up)?\b", r"\bslot (?:just )?opened(?: up)?\b",
    r"\bappointment (?:just )?opened(?: up)?\b", r"\bwalk[- ]ins? (?:today|tomorrow|welcome|available)\b",
    r"\bgap in (?:my|the) schedule\b", r"\bneed to fill (?:this|a|the) (?:spot|slot|appointment)\b",
)
CAPACITY_PATTERNS = (
    r"\bopening this week\b", r"\bavailability this week\b",
    r"\bappointments? available this week\b", r"\bwalk[- ]in availability\b",
    r"\bspot available\b", r"\bslot available\b",
)


def graph_get(client: httpx.Client, path: str, token: str, params: dict) -> dict:
    response = client.get(f"{GRAPH_BASE}/{path.lstrip('/')}", params={**params, "access_token": token})
    try:
        payload = response.json()
    except ValueError:
        response.raise_for_status()
        raise RuntimeError("Meta Graph API returned non-JSON response")
    if "error" in payload:
        error = payload.get("error") or {}
        code = error.get("code")
        message = str(error.get("message") or "Meta Graph API error")
        raise RuntimeError(f"Meta error {code}: {message}" if code else message)
    response.raise_for_status()
    return payload


def age_hours(timestamp: str, now: datetime) -> float | None:
    try:
        parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00")).astimezone(timezone.utc)
    except (TypeError, ValueError):
        return None
    if parsed > now:
        return None
    return (now - parsed).total_seconds() / 3600


def pain_matches(caption: str) -> dict:
    text = caption or ""
    disruption = [m.group(0) for p in DISRUPTION_PATTERNS if (m := re.search(p, text, re.I))]
    urgent = [m.group(0) for p in URGENT_CAPACITY_PATTERNS if (m := re.search(p, text, re.I))]
    capacity = [m.group(0) for p in CAPACITY_PATTERNS if (m := re.search(p, text, re.I))]
    return {"disruption": disruption, "urgent_capacity": urgent, "capacity": capacity}


def pain_score(evidence: list[dict]) -> int:
    if not evidence:
        return 0
    strongest = 0
    for item in evidence:
        kinds = item.get("matches") or {}
        if kinds.get("disruption"):
            strongest = max(strongest, 70)
        if kinds.get("urgent_capacity"):
            strongest = max(strongest, 60)
        if kinds.get("capacity"):
            strongest = max(strongest, 50)
    if strongest == 0:
        return 0
    newest = min(float(item.get("age_hours") or 999999) for item in evidence)
    recency_bonus = 15 if newest <= 24 else 5 if newest <= 72 else 0
    repeat_bonus = min(20, max(0, len(evidence) - 1) * 10)
    return min(100, strongest + recency_bonus + repeat_bonus)


def hashtag_media(
    client: httpx.Client,
    token: str,
    ig_user_id: str,
    tag: str,
    *,
    edge: str,
    page_limit: int,
    max_pages: int,
) -> list[dict]:
    lookup = graph_get(client, "ig_hashtag_search", token, {"user_id": ig_user_id, "q": tag})
    data = lookup.get("data") or []
    if not data:
        return []
    tag_id = str(data[0]["id"])
    rows: list[dict] = []
    after: str | None = None
    seen_cursors: set[str] = set()
    for _ in range(max_pages):
        params = {
            "user_id": ig_user_id,
            "fields": "id,caption,permalink,timestamp",
            "limit": str(page_limit),
        }
        if after:
            params["after"] = after
        payload = graph_get(client, f"{tag_id}/{edge}", token, params)
        page = list(payload.get("data") or [])
        rows.extend(page)
        cursor = str((((payload.get("paging") or {}).get("cursors") or {}).get("after")) or "")
        if not page or not cursor or cursor in seen_cursors:
            break
        seen_cursors.add(cursor)
        after = cursor
    return rows


def business_media(client: httpx.Client, token: str, ig_user_id: str, username: str, limit: int) -> tuple[dict, list[dict]]:
    clean = username.strip().lstrip("@").lower()
    fields = (
        f"business_discovery.username({clean})"
        "{id,username,name,media.limit(" + str(limit) + ")"
        "{id,caption,media_type,permalink,timestamp}}"
    )
    payload = graph_get(client, ig_user_id, token, {"fields": fields})
    account = payload.get("business_discovery") or {}
    rows = ((account.get("media") or {}).get("data") or [])
    return account, list(rows)


def _resolve_posts(posts: list[dict], workers: int) -> list[tuple[dict, object]]:
    def one(row: dict) -> tuple[dict, object]:
        return row, resolve(row["permalink"], timeout_ms=9000)

    if workers <= 1:
        return [one(row) for row in posts]
    with ThreadPoolExecutor(max_workers=workers) as pool:
        return list(pool.map(one, posts))


def _known_seeds(path: str | None) -> dict[str, dict]:
    if not path or not Path(path).exists():
        return {}
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return {}
    seeds: dict[str, dict] = {}
    for row in payload.get("signals") or []:
        if row.get("resolution_status") != "resolved" or not row.get("username"):
            continue
        username = str(row["username"]).strip().lstrip("@").lower()
        seeds[username] = {
            "username": username,
            "seed_permalink": row.get("permalink"),
            "seed_timestamp": row.get("timestamp"),
            "resolution_method": row.get("resolution_method") or "direct_intent_collector",
            "resolution_confidence": float(row.get("resolution_confidence") or 1.0),
        }
    return seeds


def run(
    *,
    token: str,
    ig_user_id: str,
    tags: tuple[str, ...] = DEFAULT_TAGS,
    per_tag_limit: int = 50,
    max_pages: int = 4,
    target_unique_posts: int = 600,
    max_seed_resolutions: int = 120,
    target_artist_seeds: int = 100,
    resolver_workers: int = 4,
    media_per_artist: int = 25,
    seed_max_age_hours: float = 336.0,
    max_age_hours: float = 72.0,
    min_pain_fit: int = 50,
    known_seed_path: str | None = None,
    now: datetime | None = None,
) -> dict:
    now = now or datetime.now(timezone.utc)
    media_by_id: dict[str, dict] = {}
    errors: list[dict] = []
    raw_recent = 0
    raw_top = 0

    with httpx.Client(timeout=20.0, follow_redirects=True) as client:
        for tag in tags:
            for edge in ("recent_media", "top_media"):
                if len(media_by_id) >= target_unique_posts:
                    break
                try:
                    rows = hashtag_media(
                        client, token, ig_user_id, tag,
                        edge=edge, page_limit=per_tag_limit, max_pages=max_pages,
                    )
                except Exception as exc:
                    errors.append({"stage": edge, "tag": tag, "error": str(exc)[:500]})
                    continue
                if edge == "recent_media":
                    raw_recent += len(rows)
                else:
                    raw_top += len(rows)
                for row in rows:
                    media_id = str(row.get("id") or "")
                    permalink = str(row.get("permalink") or "")
                    age = age_hours(str(row.get("timestamp") or ""), now)
                    if not media_id or not permalink or age is None or age > seed_max_age_hours:
                        continue
                    current = media_by_id.get(media_id)
                    if current:
                        if tag not in current["hashtags"]:
                            current["hashtags"].append(tag)
                        if edge == "recent_media":
                            current["edge"] = "recent_media"
                        continue
                    media_by_id[media_id] = {
                        "media_id": media_id,
                        "caption": str(row.get("caption") or ""),
                        "permalink": permalink,
                        "timestamp": row.get("timestamp"),
                        "age_hours": round(age, 2),
                        "hashtags": [tag],
                        "edge": edge,
                    }
            if len(media_by_id) >= target_unique_posts:
                break

        seeds = _known_seeds(known_seed_path)
        seed_posts = sorted(
            media_by_id.values(),
            key=lambda row: (0 if row.get("edge") == "recent_media" else 1, row["age_hours"]),
        )
        known_permalinks = {str(seed.get("seed_permalink") or "") for seed in seeds.values()}
        to_resolve = [row for row in seed_posts if row["permalink"] not in known_permalinks][:max_seed_resolutions]
        resolved_rows = _resolve_posts(to_resolve, resolver_workers)
        for row, result in resolved_rows:
            if len(seeds) >= target_artist_seeds:
                break
            if result.status != "resolved" or not result.username or result.confidence < 0.70:
                continue
            username = result.username.strip().lstrip("@").lower()
            seeds.setdefault(username, {
                "username": username,
                "seed_permalink": row["permalink"],
                "seed_timestamp": row["timestamp"],
                "resolution_method": result.method,
                "resolution_confidence": result.confidence,
            })

        bucket: list[dict] = []
        artist_media_scanned = 0
        professional_accounts = 0
        business_discovery_failures = 0
        for username, seed in list(seeds.items())[:target_artist_seeds]:
            try:
                account, rows = business_media(client, token, ig_user_id, username, media_per_artist)
            except Exception as exc:
                business_discovery_failures += 1
                errors.append({"stage": "business_discovery", "username": username, "error": str(exc)[:500]})
                continue
            if not account:
                continue
            professional_accounts += 1
            canonical = str(account.get("username") or username).lower()
            evidence: list[dict] = []
            artist_media_scanned += len(rows)
            for row in rows:
                age = age_hours(str(row.get("timestamp") or ""), now)
                if age is None or age > max_age_hours:
                    continue
                caption = str(row.get("caption") or "")
                matches = pain_matches(caption)
                if not any(matches.values()):
                    continue
                evidence.append({
                    "media_id": str(row.get("id") or ""),
                    "permalink": str(row.get("permalink") or ""),
                    "timestamp": row.get("timestamp"),
                    "age_hours": round(age, 2),
                    "caption": caption,
                    "matches": matches,
                })
            score = pain_score(evidence)
            if score < min_pain_fit:
                continue
            evidence.sort(key=lambda item: item["age_hours"])
            bucket.append({
                "username": canonical,
                "profile_url": f"https://www.instagram.com/{canonical}/",
                "meta_account_id": account.get("id"),
                "name": account.get("name"),
                "pain_fit": score,
                "pain_signal_count": len(evidence),
                "latest_pain_age_hours": evidence[0]["age_hours"] if evidence else None,
                "evidence": evidence,
                "seed": seed,
            })

    bucket.sort(key=lambda artist: (-artist["pain_fit"], artist["latest_pain_age_hours"] or 999999, artist["username"]))
    return {
        "schema": "empty-chair-hunter-pain-fit-bucket-v2",
        "generated_at": now.isoformat(),
        "seed_freshness_hours": seed_max_age_hours,
        "pain_freshness_hours": max_age_hours,
        "minimum_pain_fit": min_pain_fit,
        "metrics": {
            "hashtags": len(tags),
            "raw_recent_posts_scanned": raw_recent,
            "raw_top_posts_scanned": raw_top,
            "raw_posts_scanned": raw_recent + raw_top,
            "unique_seed_posts": len(media_by_id),
            "unique_fresh_posts": len(media_by_id),
            "author_resolution_attempts": len(to_resolve),
            "unique_artist_seeds": len(seeds),
            "target_artist_seeds": target_artist_seeds,
            "professional_accounts_checked": professional_accounts,
            "business_discovery_failures": business_discovery_failures,
            "artist_recent_media_scanned": artist_media_scanned,
            "pain_fit_artists": len(bucket),
        },
        "errors": errors,
        "artists": bucket,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default="hunter-pain-fit-bucket.json")
    parser.add_argument("--per-tag-limit", type=int, default=50)
    parser.add_argument("--max-pages", type=int, default=4)
    parser.add_argument("--target-unique-posts", type=int, default=600)
    parser.add_argument("--max-seed-resolutions", type=int, default=120)
    parser.add_argument("--target-artist-seeds", type=int, default=100)
    parser.add_argument("--resolver-workers", type=int, default=4)
    parser.add_argument("--media-per-artist", type=int, default=25)
    parser.add_argument("--seed-max-age-hours", type=float, default=336.0)
    parser.add_argument("--min-pain-fit", type=int, default=50)
    parser.add_argument("--known-seeds", default=None)
    args = parser.parse_args()
    token = os.getenv("HUNTER_META_ACCESS_TOKEN", "").strip()
    ig_user_id = os.getenv("HUNTER_META_IG_USER_ID", "").strip()
    if not token or not ig_user_id:
        print("hunter pain-fit bucket // skipped // Meta credentials missing")
        return 0
    result = run(
        token=token,
        ig_user_id=ig_user_id,
        per_tag_limit=args.per_tag_limit,
        max_pages=args.max_pages,
        target_unique_posts=args.target_unique_posts,
        max_seed_resolutions=args.max_seed_resolutions,
        target_artist_seeds=args.target_artist_seeds,
        resolver_workers=args.resolver_workers,
        media_per_artist=args.media_per_artist,
        seed_max_age_hours=args.seed_max_age_hours,
        min_pain_fit=args.min_pain_fit,
        known_seed_path=args.known_seeds,
    )
    Path(args.out).write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    m = result["metrics"]
    print(
        "hunter pain-fit bucket // "
        f"posts={m['unique_seed_posts']} seeds={m['unique_artist_seeds']} "
        f"business_ok={m['professional_accounts_checked']} business_fail={m['business_discovery_failures']} "
        f"artist_media={m['artist_recent_media_scanned']} bucket={m['pain_fit_artists']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
