"""Hunter Instagram Story access validation.

This diagnostic intentionally tests only supported/authorized Graph API surfaces:
1) the connected Instagram professional account's own active Stories edge; and
2) Business Discovery for another professional account's profile/media surface.

It does not guess undocumented endpoints, scrape logged-in Instagram pages, reuse
sessions/cookies, or attempt to bypass access controls. The output is a machine-
readable boundary report so Hunter can decide whether Stories can be integrated
through official Meta access.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import httpx

GRAPH_VERSION = os.getenv("HUNTER_META_GRAPH_VERSION", "v26.0")
GRAPH_BASE = f"https://graph.facebook.com/{GRAPH_VERSION}"

OWN_STORY_FIELDS = "id,media_type,permalink,timestamp"
BUSINESS_DISCOVERY_FIELDS = (
    "business_discovery.username({username})"
    "{id,username,name,media.limit(5){id,caption,media_type,permalink,timestamp}}"
)


def _graph_get(client: httpx.Client, path: str, token: str, params: dict | None = None) -> dict:
    response = client.get(
        f"{GRAPH_BASE}/{path.lstrip('/')}",
        params={**(params or {}), "access_token": token},
    )
    response.raise_for_status()
    payload = response.json()
    if "error" in payload:
        error = payload.get("error") or {}
        raise RuntimeError(str(error.get("message") or "Meta Graph API error"))
    return payload


def probe_own_stories(client: httpx.Client, token: str, ig_user_id: str) -> dict:
    """Test the connected/authorized professional account's active Stories edge."""
    try:
        payload = _graph_get(
            client,
            f"{ig_user_id}/stories",
            token,
            {"fields": OWN_STORY_FIELDS, "limit": "25"},
        )
        stories = list(payload.get("data") or [])
        return {
            "surface": "authorized_account_stories",
            "supported": True,
            "story_count": len(stories),
            "stories": stories,
            "error": None,
        }
    except Exception as exc:
        return {
            "surface": "authorized_account_stories",
            "supported": False,
            "story_count": 0,
            "stories": [],
            "error": type(exc).__name__,
            "detail": str(exc)[:500],
        }


def probe_business_discovery(
    client: httpx.Client,
    token: str,
    ig_user_id: str,
    username: str,
) -> dict:
    """Test the Business Discovery profile/media boundary for another account."""
    clean = username.strip().lstrip("@").lower()
    if not clean:
        return {
            "surface": "business_discovery",
            "supported": False,
            "username": None,
            "media_count": 0,
            "error": "missing_username",
        }
    try:
        payload = _graph_get(
            client,
            ig_user_id,
            token,
            {"fields": BUSINESS_DISCOVERY_FIELDS.format(username=clean)},
        )
        discovered = payload.get("business_discovery") or {}
        media = ((discovered.get("media") or {}).get("data") or [])
        return {
            "surface": "business_discovery",
            "supported": bool(discovered),
            "username": discovered.get("username") or clean,
            "account_id": discovered.get("id"),
            "media_count": len(media),
            "media": media,
            "stories_exposed": False,
            "note": (
                "Business Discovery is used only for its profile/media surface. "
                "This probe does not infer Story access from account discovery."
            ),
            "error": None,
        }
    except Exception as exc:
        return {
            "surface": "business_discovery",
            "supported": False,
            "username": clean,
            "media_count": 0,
            "stories_exposed": False,
            "error": type(exc).__name__,
            "detail": str(exc)[:500],
        }


def classify_boundary(own: dict, external: dict | None) -> str:
    if own.get("supported"):
        if external is not None:
            return "AUTHORIZED_STORIES_ONLY_UNLESS_META_DOCUMENTS_MORE"
        return "AUTHORIZED_STORIES_CONFIRMED_EXTERNAL_NOT_TESTED"
    return "STORY_ACCESS_NOT_CONFIRMED"


def run(*, token: str, ig_user_id: str, target_username: str | None = None) -> dict:
    with httpx.Client(timeout=20.0, follow_redirects=True) as client:
        own = probe_own_stories(client, token, ig_user_id)
        external = (
            probe_business_discovery(client, token, ig_user_id, target_username)
            if target_username
            else None
        )
    return {
        "schema": "empty-chair-hunter-story-access-v1",
        "graph_version": GRAPH_VERSION,
        "authorized_account": own,
        "external_professional_account": external,
        "boundary": classify_boundary(own, external),
        "safe_to_integrate_authorized_stories": bool(own.get("supported")),
        "safe_to_assume_arbitrary_public_story_access": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default="hunter-story-access.json")
    parser.add_argument("--target-username", default=os.getenv("HUNTER_STORY_TEST_USERNAME", ""))
    args = parser.parse_args()

    token = os.getenv("HUNTER_META_ACCESS_TOKEN", "").strip()
    ig_user_id = os.getenv("HUNTER_META_IG_USER_ID", "").strip()
    if not token or not ig_user_id:
        print("hunter story probe // skipped // Meta credentials missing")
        return 0

    result = run(
        token=token,
        ig_user_id=ig_user_id,
        target_username=args.target_username.strip() or None,
    )
    Path(args.out).write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(
        "hunter story probe // "
        f"own_supported={result['authorized_account']['supported']} "
        f"own_story_count={result['authorized_account']['story_count']} "
        f"boundary={result['boundary']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
