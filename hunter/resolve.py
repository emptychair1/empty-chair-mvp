"""Hunter artist resolver with calibrated public-search owner metadata fallback.

The original Sprint 2 resolver remains in ``resolve_core.py``. This wrapper keeps all
of its safety properties while handling a real-world case the first version missed:
search engines often return an Instagram post/reel with the owner handle and
publication date in the result snippet, while Instagram serves only a login shell to
an unauthenticated fetcher.

Search snippets are *not* generally trusted. The fallback is available only for an
Instagram media URL whose public result contains the narrow ``<handle> on <date>``
author pattern. Artist classification still requires independent artist/service
evidence from the result heading/body, and contradictory identity evidence fails
closed.
"""
from __future__ import annotations

import re
from collections import Counter
from datetime import datetime, timezone
from urllib.parse import urlparse

import resolve_core as core
from resolve_core import *  # noqa: F401,F403 - preserve the Sprint 2 public API/tests

_MONTHS = (
    "January|February|March|April|May|June|July|August|September|October|November|December"
)
_OWNER_DATE_RE = re.compile(
    rf"(?:^|[-–—]\s)(@?[A-Za-z0-9._]{{1,30}})\s+on\s+({_MONTHS})\s+(\d{{1,2}}),\s+(\d{{4}})(?=[:\s])",
    re.I,
)
_MEDIA_KINDS = {"p", "reel", "reels", "tv"}
_STUDIO_RE = re.compile(
    r"\b(?:tattoo|body art)\s+(?:studio|shop|parlou?r)|\btattoo and body piercing\b|\bstudios?\b",
    re.I,
)
_ARTIST_RE = re.compile(r"\b(?:tattoo artist|tattooer|tattooist)\b", re.I)
_CUSTOMER_RE = re.compile(
    r"\btattoo artist had (?:a )?(?:last[- ]minute )?cancellation\b.*\bi was able to get in\b|"
    r"\bmy tattoo artist\b|\bhe got it done\b|\bshe got it done\b",
    re.I,
)
_CREATOR_RE = re.compile(
    r"\b(?:my clients?|my work|done by me|tattooed by me|"
    r"i(?:'ll| will) do this (?:piece|tattoo)|come get a tattoo|visit me in person|"
    r"(?:text|email|message|dm)(?: or (?:text|email|message|dm))? me)\b",
    re.I,
)
_COMMERCIAL_RE = re.compile(
    r"\b(?:first come first serve|discount(?:ed)? price|\$\s*\d+|"
    r"come get a tattoo|visit me in person|(?:text|email|message|dm)(?: or (?:text|email|message|dm))? me)\b",
    re.I,
)


def _instagram_media_url(url: object) -> bool:
    try:
        parsed = urlparse(str(url or ""))
        if parsed.scheme not in {"http", "https"} or parsed.hostname not in core.INSTAGRAM_HOSTS:
            return False
        parts = [part for part in parsed.path.split("/") if part]
        return len(parts) >= 2 and parts[0].lower() in _MEDIA_KINDS
    except (TypeError, ValueError):
        return False


def _search_owner_metadata(signal: dict) -> dict | None:
    """Return narrow, independently re-derived owner metadata for Instagram media hits."""
    if not _instagram_media_url(signal.get("source_url")):
        return None
    snippet = str(signal.get("snippet") or "").strip()
    match = _OWNER_DATE_RE.search(snippet)
    if not match:
        return None
    username = match.group(1).lstrip("@").lower()
    if not core.instagram_username(core.profile_url(username)):
        return None

    # Collector fields are hints only. If populated, they must agree with the owner
    # independently extracted above; otherwise fail closed instead of guessing.
    hinted = str(signal.get("username") or "").strip().lower()
    if hinted and hinted != username:
        return {"conflict": True, "reason": "search_owner_hint_conflict"}
    hinted_url = core.instagram_username(str(signal.get("instagram_url") or ""))
    if hinted_url and hinted_url != username:
        return {"conflict": True, "reason": "search_owner_url_conflict"}

    try:
        published = datetime.strptime(
            f"{match.group(2)} {match.group(3)} {match.group(4)}", "%B %d %Y"
        ).replace(hour=12, tzinfo=timezone.utc)
    except ValueError:
        published = None
    return {
        "conflict": False,
        "username": username,
        "published_at": published,
        "evidence": match.group(0).strip(" -–—"),
    }


def _search_classification_context(signal: dict) -> tuple[core.Context | None, str]:
    """Conservatively decide whether search-result text can classify the verified owner."""
    title = core.clean_text(str(signal.get("title") or ""))
    snippet = core.clean_text(str(signal.get("snippet") or ""))
    text = core.clean_text(f"{title} | {snippet}")
    if not text:
        return None, "search_context_empty"

    if _CUSTOMER_RE.search(text):
        return None, "search_context_customer_language"

    studio = bool(_STUDIO_RE.search(title))
    explicit_artist = bool(_ARTIST_RE.search(title)) and not studio
    creator = bool(_CREATOR_RE.search(text)) and "tattoo" in text.lower() and not studio

    if studio:
        return core.Context(text=text, entity_type="studio"), "search_result_studio_heading"
    if explicit_artist:
        return core.Context(text=text, entity_type="individual"), "search_result_artist_heading"
    if creator:
        return core.Context(text=text, entity_type="individual"), "search_result_creator_post"
    return None, "search_context_insufficient_artist_evidence"


def _apply_search_creator_evidence(data: dict, *, kind: str, text: str, activity_at: datetime | None, now: datetime) -> None:
    """Promote only strong owner-authored service evidence; never generic tattoo text."""
    if kind != "search_result_creator_post" or data.get("is_tattoo_artist") is not None:
        return
    data["is_tattoo_artist"] = True
    data["account_type"] = "individual"
    data.setdefault("classification_evidence", {})["tattoo_artist"] = "owner-authored tattoo service post"
    if _COMMERCIAL_RE.search(text):
        data["commercial_account"] = True
        active = activity_at >= now - core.timedelta(days=core.ACTIVE_DAYS) if activity_at else None
        data["active_account"] = active
        data["active_commercial_account"] = active
        data["classification_evidence"]["commercial"] = "owner-authored booking/price call-to-action"


def resolve_signal(signal: dict, fetcher: core.PublicFetcher, now: datetime) -> dict:
    source = fetcher.get(signal["source_url"])
    context = core.parse_context(source)
    owner = _search_owner_metadata(signal)
    result = {
        "signal_id": signal["id"],
        "status": "UNRESOLVED",
        "account_id": None,
        "reason": source.error or "no_verified_identity",
    }

    if owner and owner.get("conflict"):
        result["reason"] = owner["reason"]
        return result

    identities = set(context.identities)
    if len(identities) > 1:
        result["reason"] = "ambiguous_accounts"
        return result

    if identities:
        username = next(iter(identities))
        if owner and username != owner.get("username"):
            result["reason"] = "search_owner_page_conflict"
            return result
        identity_source = context.identity_source
    elif owner:
        username = str(owner["username"])
        identity_source = "search_result_owner_metadata"
    else:
        return result

    profile = source if core.instagram_username(source.url) == username else fetcher.get(core.profile_url(username))
    profile_context = core.parse_context(profile)
    if profile_context.identities and profile_context.identities != {username}:
        result["reason"] = "profile_identity_conflict"
        return result

    classification_kind = "profile"
    if profile_context.text and profile_context.identities == {username}:
        classification_context = profile_context
    elif context.identity_source == "structured_subject" and context.entity_type:
        classification_context = core.Context(
            text=context.subject_text, entity_type=context.entity_type, address=context.address
        )
        classification_kind = "structured_subject"
    elif owner:
        classification_context, classification_kind = _search_classification_context(signal)
        if classification_context is None:
            account_id = core.hashlib.sha256(f"instagram:{username}".encode()).hexdigest()[:32]
            return {
                **result,
                "status": "UNRESOLVED",
                "reason": classification_kind,
                "account_id": account_id,
                "username": username,
                "profile_url": core.profile_url(username),
                "identity_evidence": {
                    "kind": identity_source,
                    "source_url": source.url,
                    "search_owner": owner.get("evidence"),
                },
                "profile_context": core.clean_text(
                    f"{signal.get('title', '')} | {signal.get('snippet', '')}"
                )[:8000],
                "is_tattoo_artist": None,
                "account_type": "unknown",
                "commercial_account": None,
                "active_account": None,
                "active_commercial_account": None,
                "last_activity_at": owner["published_at"].isoformat() if owner.get("published_at") else None,
                "classification_evidence": {
                    "tattoo_artist": None, "exclusion": None, "commercial": None, "closed": None,
                },
                "location": None,
            }
    else:
        result["reason"] = profile.error or "profile_context_unavailable"
        return result

    page_activity = core.timestamp(context.published_at, now)
    search_activity = owner.get("published_at") if owner else None
    activity_at = page_activity or (search_activity if isinstance(search_activity, datetime) and search_activity <= now else None)
    data = core.classify(classification_context, activity_at=activity_at, now=now)
    _apply_search_creator_evidence(
        data,
        kind=classification_kind,
        text=classification_context.text,
        activity_at=activity_at,
        now=now,
    )

    status = "REJECTED" if data["is_tattoo_artist"] is False else (
        "RESOLVED" if data["is_tattoo_artist"] is True else "UNRESOLVED"
    )
    account_id = core.hashlib.sha256(f"instagram:{username}".encode()).hexdigest()[:32]
    identity_evidence = {"kind": identity_source, "source_url": source.url}
    if owner:
        identity_evidence["search_owner"] = owner.get("evidence")
        identity_evidence["publication_time_precision"] = "date"
    return {
        **result,
        "status": status,
        "reason": "artist_evidence" if status == "RESOLVED" else (
            "non_artist_evidence" if status == "REJECTED" else "insufficient_artist_evidence"
        ),
        "account_id": account_id,
        "username": username,
        "profile_url": core.profile_url(username),
        "identity_evidence": identity_evidence,
        "classification_source": classification_kind,
        "profile_context": classification_context.text[:8000],
        **data,
    }


def resolve_signals(signals: list[dict], fetcher: core.PublicFetcher, *, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    resolutions: list[dict] = []
    accounts: dict[str, dict] = {}
    seen: set[str] = set()
    for signal in signals:
        if not isinstance(signal, dict) or not all(
            isinstance(signal.get(key), str) and signal[key] for key in ("id", "source_url")
        ):
            raise ValueError("Every signal requires a nonempty string id and source_url")
        if signal["id"] in seen:
            continue
        seen.add(signal["id"])
        result = resolve_signal(signal, fetcher, now)
        resolutions.append(result)
        if not result.get("account_id"):
            continue
        key = result["account_id"]
        if key not in accounts:
            accounts[key] = {k: v for k, v in result.items() if k != "signal_id"}
            accounts[key]["signals"] = []
        account = accounts[key]
        account["signals"].append({k: signal.get(k) for k in (
            "id", "source_url", "source", "query", "matched_phrase", "discovered_at"
        )})
        previous = core.timestamp(account.get("last_activity_at"), now)
        current = core.timestamp(result.get("last_activity_at"), now)
        if current and (previous is None or current > previous):
            for field_name in ("last_activity_at", "active_account", "active_commercial_account"):
                account[field_name] = result.get(field_name)
        if (
            account.get("is_tattoo_artist") != result.get("is_tattoo_artist")
            or account.get("account_type") != result.get("account_type")
        ):
            account.update(status="UNRESOLVED", reason="conflicting_profile_evidence")

    status_counts = Counter(result["status"] for result in resolutions)
    reason_counts = Counter(result["reason"] for result in resolutions)
    return {
        "schema": core.SCHEMA,
        "generated_at": now.isoformat(),
        "input_count": len(signals),
        "unique_signal_count": len(resolutions),
        "account_count": len(accounts),
        "status_counts": dict(status_counts),
        "reason_counts": dict(reason_counts),
        "request_count": fetcher.requests,
        "accounts": sorted(accounts.values(), key=lambda account: account["username"]),
        "resolutions": resolutions,
    }


def main() -> int:
    parser = core.argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", default="hunter-signals.json")
    parser.add_argument("--out", default="hunter-artists.json")
    parser.add_argument("--max-requests", type=int, default=core.MAX_REQUESTS)
    args = parser.parse_args()
    if args.max_requests < 0:
        parser.error("--max-requests must be nonnegative")
    payload = core.json.loads(core.Path(args.input).read_text(encoding="utf-8"))
    if (
        not isinstance(payload, dict)
        or payload.get("schema") != "empty-chair-hunter-signals-v1"
        or not isinstance(payload.get("signals"), list)
    ):
        parser.error("Expected a Sprint 1 empty-chair-hunter-signals-v1 signals file")
    with core.httpx.Client(timeout=10, follow_redirects=False) as client:
        result = resolve_signals(
            payload["signals"], core.PublicFetcher(client, max_requests=args.max_requests)
        )
    output = core.Path(args.out)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(core.json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(
        f"hunter // {result['account_count']} unique accounts // {result['status_counts']} "
        f"// reasons {result['reason_counts']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
