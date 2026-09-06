"""Sprint 3: score resolved Hunter accounts by immediate cancellation intent.

The scorer is deterministic and evidence-backed. Unknown information earns zero points.
Discovery timestamps are never treated as post timestamps. The output is a ranked queue
candidate file for Sprint 4; this module performs no outreach or production-app writes.
"""
from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from config import (
    HOT_THRESHOLD,
    PRICE_TERMS,
    SCORE_WEIGHTS,
    STALE_HOURS,
    URGENCY_TERMS,
    VERY_RECENT_HOURS,
    WARM_THRESHOLD,
)

SCHEMA = "empty-chair-hunter-scores-v1"
SIGNAL_SCHEMA = "empty-chair-hunter-signals-v1"
ARTIST_SCHEMA = "empty-chair-hunter-artists-v1"

GENERIC_BOOKING_PATTERNS = (
    r"\bbooks? (?:are )?open\b",
    r"\bbooking(?:s)? (?:are )?open\b",
    r"\bappointments? available\b",
    r"\baccepting (?:bookings|appointments)\b",
)


def parse_timestamp(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def age_hours(value: object, now: datetime) -> float | None:
    parsed = parse_timestamp(value)
    if parsed is None or parsed > now:
        return None
    return (now - parsed).total_seconds() / 3600


def contains_any(text: str, terms: tuple[str, ...]) -> str | None:
    lower = text.lower()
    for term in terms:
        if term.lower() in lower:
            return term
    return None


def explicit_cancellation(signal: dict) -> str | None:
    phrase = str(signal.get("matched_phrase") or "").lower()
    if "cancellation" in phrase or "cancelled" in phrase or "canceled" in phrase:
        return str(signal.get("matched_phrase"))
    text = f"{signal.get('title', '')} {signal.get('snippet', '')}".lower()
    match = re.search(r"\b(?:had a |last[- ]minute )?cancell?ation\b|\bcancelled appointment\b|\bcanceled appointment\b", text)
    return match.group(0) if match else None


def signal_text(signal: dict) -> str:
    return " ".join(
        str(signal.get(key) or "")
        for key in ("matched_phrase", "title", "snippet")
    ).strip()


def generic_books_open(signals: list[dict]) -> str | None:
    for signal in signals:
        text = signal_text(signal)
        for pattern in GENERIC_BOOKING_PATTERNS:
            match = re.search(pattern, text, re.I)
            if match:
                return match.group(0)
    return None


def score_account(account: dict, signals: list[dict], *, now: datetime) -> dict:
    """Return one explainable score. Missing facts add no positive or negative weight."""
    components: list[dict] = []

    def add(rule: str, evidence: object) -> None:
        points = SCORE_WEIGHTS[rule]
        components.append({"rule": rule, "points": points, "evidence": evidence})

    cancellation_evidence = next((explicit_cancellation(s) for s in signals if explicit_cancellation(s)), None)
    if cancellation_evidence:
        add("explicit_cancellation", cancellation_evidence)

    combined = " | ".join(signal_text(s) for s in signals)
    urgency_evidence = contains_any(combined, URGENCY_TERMS)
    if urgency_evidence:
        add("urgent", urgency_evidence)

    if account.get("is_tattoo_artist") is True and account.get("account_type") == "individual":
        add("individual_artist", account.get("classification_evidence", {}).get("tattoo_artist") or "individual tattoo artist")

    if account.get("active_commercial_account") is True:
        add("active_commercial_account", account.get("last_activity_at") or "verified active commercial account")

    price_evidence = contains_any(combined, PRICE_TERMS)
    if price_evidence:
        add("price_signal", price_evidence)

    location = account.get("location")
    if isinstance(location, dict) and str(location.get("country") or "").upper() == "US":
        add("us_location", {
            "city": location.get("city"),
            "region": location.get("region"),
            "country": "US",
        })

    hours = age_hours(account.get("last_activity_at"), now)
    if hours is not None and hours <= VERY_RECENT_HOURS:
        add("very_recent_post", account.get("last_activity_at"))
    elif hours is not None and hours > STALE_HOURS:
        add("stale", account.get("last_activity_at"))

    generic_evidence = generic_books_open(signals)
    if generic_evidence:
        add("generic_books_open", generic_evidence)

    if account.get("account_type") == "studio":
        add("studio_account", account.get("profile_context") or "studio account")

    raw_score = sum(component["points"] for component in components)
    score = max(0, min(100, raw_score))
    eligible = account.get("status") == "RESOLVED" and account.get("is_tattoo_artist") is True
    state = "HOT" if eligible and score >= HOT_THRESHOLD else (
        "WARM" if eligible and score >= WARM_THRESHOLD else "IGNORE"
    )
    return {
        "account_id": account.get("account_id"),
        "username": account.get("username"),
        "profile_url": account.get("profile_url"),
        "score": score,
        "raw_score": raw_score,
        "state": state,
        "eligible": eligible,
        "components": components,
        "signal_ids": [s.get("id") for s in signals if s.get("id")],
        "signal_count": len(signals),
        "last_activity_at": account.get("last_activity_at"),
        "location": location,
    }


def score_payload(artists_payload: dict, signals_payload: dict, *, now: datetime | None = None) -> dict:
    if artists_payload.get("schema") != ARTIST_SCHEMA or not isinstance(artists_payload.get("accounts"), list):
        raise ValueError(f"Expected {ARTIST_SCHEMA} artist payload")
    if signals_payload.get("schema") != SIGNAL_SCHEMA or not isinstance(signals_payload.get("signals"), list):
        raise ValueError(f"Expected {SIGNAL_SCHEMA} signal payload")

    now = now or datetime.now(timezone.utc)
    by_id = {
        signal.get("id"): signal
        for signal in signals_payload["signals"]
        if isinstance(signal, dict) and isinstance(signal.get("id"), str)
    }
    scored = []
    for account in artists_payload["accounts"]:
        if not isinstance(account, dict):
            continue
        ids = [
            item.get("id")
            for item in account.get("signals", [])
            if isinstance(item, dict) and isinstance(item.get("id"), str)
        ]
        evidence = [by_id[signal_id] for signal_id in ids if signal_id in by_id]
        scored.append(score_account(account, evidence, now=now))

    scored.sort(key=lambda item: (-item["score"], str(item.get("username") or "")))
    counts = Counter(item["state"] for item in scored)
    return {
        "schema": SCHEMA,
        "generated_at": now.isoformat(),
        "account_count": len(scored),
        "state_counts": dict(counts),
        "targets": scored,
    }


def ranking_separation(targets: list[dict], size: int = 20) -> dict:
    """Diagnostic for Sprint 3 acceptance: compare top and bottom cohorts."""
    if not targets:
        return {"cohort_size": 0, "top_average": None, "bottom_average": None, "gap": None}
    cohort = min(size, max(1, len(targets) // 2))
    top = targets[:cohort]
    bottom = targets[-cohort:]
    top_average = sum(item["score"] for item in top) / cohort
    bottom_average = sum(item["score"] for item in bottom) / cohort
    return {
        "cohort_size": cohort,
        "top_average": round(top_average, 2),
        "bottom_average": round(bottom_average, 2),
        "gap": round(top_average - bottom_average, 2),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artists", default="hunter-artists.json")
    parser.add_argument("--signals", default="hunter-signals.json")
    parser.add_argument("--out", default="hunter-scores.json")
    args = parser.parse_args()

    artists_payload = json.loads(Path(args.artists).read_text(encoding="utf-8"))
    signals_payload = json.loads(Path(args.signals).read_text(encoding="utf-8"))
    result = score_payload(artists_payload, signals_payload)
    result["ranking_separation"] = ranking_separation(result["targets"])

    output = Path(args.out)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(
        f"hunter // scored {result['account_count']} accounts // "
        f"{result['state_counts']} // separation {result['ranking_separation']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
