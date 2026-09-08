"""Read-only Instagram Story collector for Hunter recovery-intent signals.

Uses an authenticated instagrapi session supplied by the operator. It does not
login with credentials, post, message, follow, like, or attempt to bypass
Instagram challenges. Missing/blocked data is UNKNOWN, never a negative signal.
"""
from __future__ import annotations

import argparse
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCHEMA = "empty-chair-hunter-story-watch-v1"

RECOVERY_PATTERNS: tuple[tuple[str, int], ...] = (
    (r"\bcancell?ations?\b", 70),
    (r"\bcancelled\b|\bcanceled\b", 70),
    (r"\blast[ -]?minute\b", 65),
    (r"\bopen(?:ing|ings)?\b|\bopen spot(?:s)?\b", 55),
    (r"\bavailab(?:le|ility)\b", 50),
    (r"\bwait[ -]?list\b", 45),
    (r"\bdm (?:me )?to (?:book|claim)\b|\bclaim (?:it|this|the spot)\b", 45),
    (r"\bsame[ -]?day\b", 40),
)


def _text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def story_text(story: Any) -> str:
    """Collect textual metadata exposed on a Story object without downloading media."""
    parts: list[str] = []
    for attr in ("caption_text", "accessibility_caption", "title"):
        value = getattr(story, attr, None)
        if value:
            parts.append(_text(value))

    caption = getattr(story, "caption", None)
    if caption:
        parts.append(_text(getattr(caption, "text", caption)))

    for attr in ("mentions", "hashtags", "links", "story_cta"):
        value = getattr(story, attr, None)
        if value:
            parts.append(_text(value))

    # instagrapi models may retain raw-ish dict content in model_extra.
    extra = getattr(story, "model_extra", None)
    if isinstance(extra, dict):
        for key in ("caption", "text", "accessibility_caption"):
            if extra.get(key):
                parts.append(_text(extra[key]))

    return "\n".join(p for p in parts if p)


def classify_recovery(text: str) -> dict:
    lowered = text.lower()
    matches: list[str] = []
    score = 0
    for pattern, weight in RECOVERY_PATTERNS:
        found = re.search(pattern, lowered, flags=re.IGNORECASE)
        if found:
            matches.append(found.group(0))
            score = max(score, weight)
    if len(matches) >= 2:
        score = min(100, score + 10)
    return {
        "recovery": bool(matches),
        "matches": matches,
        "intent_score": score,
    }


def _story_timestamp(story: Any) -> str | None:
    taken_at = getattr(story, "taken_at", None)
    if taken_at is None:
        return None
    if hasattr(taken_at, "astimezone"):
        try:
            return taken_at.astimezone(timezone.utc).isoformat()
        except Exception:
            return _text(taken_at)
    return _text(taken_at) or None


def analyze_stories(username: str, stories: list[Any]) -> dict:
    observations: list[dict] = []
    for story in stories:
        text = story_text(story)
        classification = classify_recovery(text)
        if not classification["recovery"]:
            continue
        observations.append({
            "story_pk": _text(getattr(story, "pk", "")) or None,
            "taken_at": _story_timestamp(story),
            "text": text[:4000],
            **classification,
        })

    return {
        "username": username.lower().lstrip("@"),
        "ok": True,
        "status": "recovery_story_found" if observations else "stories_checked_no_recovery_text",
        "story_count": len(stories),
        "recovery_story_count": len(observations),
        "best_intent_score": max((x["intent_score"] for x in observations), default=0),
        "observations": observations,
        "error": None,
    }


def _load_client(session_path: str):
    from instagrapi import Client

    client = Client()
    client.load_settings(session_path)
    if not client.user_id:
        # load_settings may restore identifiers without actively validating them.
        client.user_id = str(client.get_settings().get("user_id") or "") or None
    return client


def probe_username(username: str, *, session_path: str) -> dict:
    clean = username.strip().lower().lstrip("@")
    try:
        client = _load_client(session_path)
        user_id = str(client.user_id_from_username(clean))
        stories = client.user_stories_v1(user_id)
        return analyze_stories(clean, stories)
    except Exception as exc:
        name = exc.__class__.__name__
        return {
            "username": clean,
            "ok": False,
            "status": "unknown_auth_or_access_failure",
            "story_count": 0,
            "recovery_story_count": 0,
            "best_intent_score": 0,
            "observations": [],
            "error": f"{name}: {exc}",
        }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("usernames", nargs="+")
    parser.add_argument("--session", default=os.getenv("HUNTER_IG_SESSION_FILE", ""))
    parser.add_argument("--out")
    args = parser.parse_args()

    if not args.session:
        raise SystemExit("Provide --session or HUNTER_IG_SESSION_FILE")
    if not Path(args.session).exists():
        raise SystemExit(f"Instagram session file not found: {args.session}")

    results = [probe_username(name, session_path=args.session) for name in args.usernames]
    payload = {
        "schema": SCHEMA,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "count": len(results),
        "recovery_signal_count": sum(1 for r in results if r["recovery_story_count"] > 0),
        "results": results,
    }
    rendered = json.dumps(payload, indent=2, ensure_ascii=False)
    print(rendered)
    if args.out:
        Path(args.out).write_text(rendered + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
