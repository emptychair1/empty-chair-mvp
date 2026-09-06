"""Merge official Meta Instagram discoveries into Hunter's standard signal/artist payloads."""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

SIGNAL_SCHEMA = "empty-chair-hunter-signals-v1"
ARTIST_SCHEMA = "empty-chair-hunter-artists-v1"
META_SCHEMA = "empty-chair-hunter-instagram-meta-v1"


def _account_id(username: str) -> str:
    return hashlib.sha256(f"instagram:{username.lower()}".encode()).hexdigest()[:32]


def _signal_id(media_id: str, username: str) -> str:
    return hashlib.sha256(f"instagram-meta:{media_id}:{username.lower()}".encode()).hexdigest()[:32]


def _profile(username: str) -> str:
    return f"https://www.instagram.com/{username.lower()}/"


def _matched_phrase(meta: dict) -> str:
    matches = meta.get("intent_matches") or []
    return str(matches[0]) if matches else ""


def integrate(signals_payload: dict, artists_payload: dict, meta_payload: dict, *, now: datetime | None = None) -> tuple[dict, dict]:
    if signals_payload.get("schema") != SIGNAL_SCHEMA or not isinstance(signals_payload.get("signals"), list):
        raise ValueError(f"Expected {SIGNAL_SCHEMA}")
    if artists_payload.get("schema") != ARTIST_SCHEMA or not isinstance(artists_payload.get("accounts"), list):
        raise ValueError(f"Expected {ARTIST_SCHEMA}")
    if meta_payload.get("schema") != META_SCHEMA or not isinstance(meta_payload.get("signals"), list):
        raise ValueError(f"Expected {META_SCHEMA}")

    now = now or datetime.now(timezone.utc)
    signals = list(signals_payload["signals"])
    accounts = {str(a.get("account_id")): dict(a) for a in artists_payload["accounts"] if a.get("account_id")}
    existing_signal_ids = {str(s.get("id")) for s in signals if s.get("id")}
    added = 0

    for meta in meta_payload["signals"]:
        username = str(meta.get("username") or "").strip().lower()
        media_id = str(meta.get("media_id") or "").strip()
        permalink = str(meta.get("permalink") or "").strip()
        caption = str(meta.get("caption") or "").strip()
        timestamp = str(meta.get("timestamp") or "").strip()
        if not username or not media_id or not permalink or not timestamp:
            continue
        if meta.get("resolution_status") != "resolved":
            continue
        if float(meta.get("resolution_confidence") or 0.0) < 0.70:
            continue
        if not meta.get("intent_matches"):
            continue

        sid = _signal_id(media_id, username)
        if sid not in existing_signal_ids:
            signals.append({
                "id": sid,
                "source": "instagram_meta_hashtag",
                "query": f"#{meta.get('hashtag') or ''}",
                "source_url": permalink,
                "instagram_url": _profile(username),
                "username": username,
                "title": f"Instagram @{username}",
                "snippet": caption,
                "matched_phrase": _matched_phrase(meta),
                "discovered_at": meta_payload.get("generated_at") or now.isoformat(),
            })
            existing_signal_ids.add(sid)
            added += 1

        aid = _account_id(username)
        signal_ref = {
            "id": sid,
            "source_url": permalink,
            "source": "instagram_meta_hashtag",
            "query": f"#{meta.get('hashtag') or ''}",
            "matched_phrase": _matched_phrase(meta),
            "discovered_at": meta_payload.get("generated_at") or now.isoformat(),
        }
        current = accounts.get(aid)
        if current:
            refs = list(current.get("signals") or [])
            if not any(r.get("id") == sid for r in refs):
                refs.append(signal_ref)
            current["signals"] = refs
            # Official Meta timestamp is stronger freshness evidence than discovery time.
            prior = str(current.get("last_activity_at") or "")
            if not prior or timestamp > prior:
                current["last_activity_at"] = timestamp
                current["active_account"] = True
                current["active_commercial_account"] = True
            if current.get("status") != "RESOLVED" or current.get("is_tattoo_artist") is not True:
                current.update({
                    "status": "RESOLVED",
                    "reason": "official_meta_visual_owner_intent_evidence",
                    "username": username,
                    "profile_url": _profile(username),
                    "is_tattoo_artist": True,
                    "account_type": "individual",
                    "commercial_account": True,
                    "active_account": True,
                    "active_commercial_account": True,
                    "classification_evidence": {
                        "tattoo_artist": "official Meta tattoo hashtag post with resolved public author",
                        "exclusion": None,
                        "commercial": "fresh cancellation/opening availability intent",
                        "closed": None,
                    },
                })
            accounts[aid] = current
        else:
            accounts[aid] = {
                "status": "RESOLVED",
                "reason": "official_meta_visual_owner_intent_evidence",
                "account_id": aid,
                "username": username,
                "profile_url": _profile(username),
                "identity_evidence": {
                    "kind": "official_meta_permalink_visual_author",
                    "source_url": permalink,
                    "resolution_method": meta.get("resolution_method"),
                    "resolution_confidence": meta.get("resolution_confidence"),
                },
                "profile_context": caption[:8000],
                "is_tattoo_artist": True,
                "account_type": "individual",
                "commercial_account": True,
                "active_account": True,
                "active_commercial_account": True,
                "last_activity_at": timestamp,
                "classification_evidence": {
                    "tattoo_artist": "official Meta tattoo hashtag post with resolved public author",
                    "exclusion": None,
                    "commercial": "fresh cancellation/opening availability intent",
                    "closed": None,
                },
                "location": None,
                "signals": [signal_ref],
            }

    merged_signals = {
        **signals_payload,
        "generated_at": now.isoformat(),
        "count": len(signals),
        "instagram_meta_added": added,
        "signals": signals,
    }
    merged_artists = {
        **artists_payload,
        "generated_at": now.isoformat(),
        "account_count": len(accounts),
        "instagram_meta_added": added,
        "accounts": sorted(accounts.values(), key=lambda a: str(a.get("username") or "")),
    }
    return merged_signals, merged_artists


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--signals", required=True)
    parser.add_argument("--artists", required=True)
    parser.add_argument("--instagram", required=True)
    parser.add_argument("--signals-out", required=True)
    parser.add_argument("--artists-out", required=True)
    args = parser.parse_args()
    signals = json.loads(Path(args.signals).read_text(encoding="utf-8"))
    artists = json.loads(Path(args.artists).read_text(encoding="utf-8"))
    meta = json.loads(Path(args.instagram).read_text(encoding="utf-8"))
    merged_signals, merged_artists = integrate(signals, artists, meta)
    Path(args.signals_out).write_text(json.dumps(merged_signals, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    Path(args.artists_out).write_text(json.dumps(merged_artists, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"hunter instagram integrate // added={merged_signals['instagram_meta_added']} accounts={merged_artists['account_count']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
