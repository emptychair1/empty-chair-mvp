"""Sweep fresh social pain for Hunter using official/public Instagram surfaces only.

Sources:
1) resolved <=72h high-intent hashtag posts already collected through Meta + public visual resolution;
2) official Meta Business Discovery recent media for artists in Hunter's fresh bucket.

No login/session automation, private content, challenge bypass, guessed contacts, or outreach.
"""
from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path

import httpx

from artist_media_expander import business_media
from fresh_pain_verifier import age_hours, pain_matches, strongest_score

MAX_AGE_HOURS = 72.0


def _caption_evidence(caption: str, timestamp: str | None, now: datetime) -> dict | None:
    from fresh_pain_verifier import parse_dt
    dt = parse_dt(timestamp)
    age = age_hours(dt, now)
    if age is None or age > MAX_AGE_HOURS:
        return None
    matches = pain_matches(caption or "")
    if not any(matches.values()):
        return None
    return {
        "caption": caption,
        "timestamp": dt.isoformat() if dt else None,
        "age_hours": round(age, 2),
        "matches": matches,
        "pain_fit": strongest_score(matches, age),
    }


def run(*, bucket: dict, hashtag: dict, token: str, ig_user_id: str,
        media_limit: int = 25, max_artists: int = 300,
        now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    leads: dict[str, dict] = {}
    errors: list[dict] = []

    # Direct high-intent posts are already <=72h-gated by instagram_hashtag_source.
    for row in hashtag.get("signals") or []:
        username = str(row.get("username") or "").strip().lstrip("@").lower()
        if not username or row.get("resolution_status") != "resolved":
            continue
        ev = _caption_evidence(str(row.get("caption") or ""), row.get("timestamp"), now)
        if not ev:
            continue
        ev.update({"source": "instagram_meta_hashtag", "permalink": row.get("permalink")})
        leads[username] = {
            "username": username,
            "name": None,
            "contact": {"instagram_profile": f"https://www.instagram.com/{username}/", "contactability": 40},
            "pain_fit": ev["pain_fit"],
            "evidence": [ev],
            "sources": ["instagram_meta_hashtag"],
        }

    artists = list(bucket.get("artists") or [])[:max_artists]
    checked = supported = media_scanned = fresh_media = 0
    with httpx.Client(timeout=20.0, follow_redirects=True) as client:
        for artist in artists:
            username = str(artist.get("username") or "").strip().lstrip("@").lower()
            if not username:
                continue
            checked += 1
            try:
                account, rows = business_media(client, token, ig_user_id, username, media_limit)
            except Exception as exc:
                errors.append({"username": username, "error": type(exc).__name__})
                continue
            if not account:
                continue
            supported += 1
            media_scanned += len(rows)
            evidences: list[dict] = []
            for row in rows:
                ev = _caption_evidence(str(row.get("caption") or ""), row.get("timestamp"), now)
                if not ev:
                    continue
                fresh_media += 1
                ev.update({"source": "instagram_meta_business_discovery", "permalink": row.get("permalink")})
                evidences.append(ev)
            if not evidences:
                continue
            evidences.sort(key=lambda x: (-int(x["pain_fit"]), float(x["age_hours"])))
            existing = leads.get(username)
            if existing:
                existing["evidence"].extend(evidences)
                existing["sources"].append("instagram_meta_business_discovery")
                existing["pain_fit"] = max(existing["pain_fit"], max(e["pain_fit"] for e in evidences))
                if not existing.get("name"):
                    existing["name"] = artist.get("name")
                existing["contact"] = artist.get("contact") or existing["contact"]
            else:
                leads[username] = {
                    "username": username,
                    "name": artist.get("name"),
                    "contact": artist.get("contact") or {"instagram_profile": f"https://www.instagram.com/{username}/", "contactability": 40},
                    "pain_fit": max(e["pain_fit"] for e in evidences),
                    "evidence": evidences,
                    "sources": ["instagram_meta_business_discovery"],
                }

    output = sorted(leads.values(), key=lambda x: (-int(x.get("pain_fit") or 0), x.get("username") or ""))
    direct_contact = [x for x in output if int((x.get("contact") or {}).get("contactability") or 0) >= 85]
    return {
        "schema": "empty-chair-hunter-social-pain-v1",
        "generated_at": now.isoformat(),
        "policy": {"pain_freshness_hours": 72, "social": "official Meta/public resolved surfaces only"},
        "metrics": {
            "bucket_artists_input": len(artists),
            "business_discovery_checked": checked,
            "business_discovery_supported": supported,
            "business_media_scanned": media_scanned,
            "business_fresh_pain_media": fresh_media,
            "resolved_hashtag_candidates": sum(1 for x in hashtag.get("signals") or [] if x.get("username")),
            "verified_fresh_social_pain_leads": len(output),
            "verified_direct_contact_leads": len(direct_contact),
            "target_fresh_leads": 100,
        },
        "errors": errors,
        "leads": output,
    }


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--bucket", default="hunter-fresh-contact-bucket.json")
    p.add_argument("--hashtag", default="hunter-instagram-signals.json")
    p.add_argument("--out", default="hunter-social-pain.json")
    p.add_argument("--media-limit", type=int, default=25)
    p.add_argument("--max-artists", type=int, default=300)
    args = p.parse_args()
    token = os.getenv("HUNTER_META_ACCESS_TOKEN", "").strip()
    ig_user_id = os.getenv("HUNTER_META_IG_USER_ID", "").strip()
    if not token or not ig_user_id:
        raise SystemExit("Meta credentials required for social pain sweep")
    bucket = json.loads(Path(args.bucket).read_text(encoding="utf-8"))
    hashtag = json.loads(Path(args.hashtag).read_text(encoding="utf-8")) if Path(args.hashtag).exists() else {"signals": []}
    result = run(bucket=bucket, hashtag=hashtag, token=token, ig_user_id=ig_user_id,
                 media_limit=args.media_limit, max_artists=args.max_artists)
    Path(args.out).write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    m = result["metrics"]
    print(f"hunter social pain // checked={m['business_discovery_checked']} supported={m['business_discovery_supported']} media={m['business_media_scanned']} verified={m['verified_fresh_social_pain_leads']} target={m['target_fresh_leads']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
