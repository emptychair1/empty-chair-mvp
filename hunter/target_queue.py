"""Sprint 4: turn Hunter intent scores into a safe next-action target queue.

This stage does not contact anyone. It decides who is eligible to be actioned next,
preserves queue history, enforces stale/cooldown rules, and creates a stable action key
so Sprint 5 cannot accidentally replay the same evidence.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

from config import STALE_HOURS, TARGET_COOLDOWN_HOURS, TARGET_STATES

SCHEMA = "empty-chair-hunter-queue-v1"
SCORE_SCHEMA = "empty-chair-hunter-scores-v1"
ELIGIBLE_SCORE_STATES = {"HOT", "WARM"}
PROGRESSION_STATES = {"CLICKED", "TRIAL", "ARMED", "PAID"}
TERMINAL_STATES = PROGRESSION_STATES | {"SUPPRESSED"}


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


def iso(value: datetime | None) -> str | None:
    return value.astimezone(timezone.utc).isoformat() if value else None


def action_key(target: dict) -> str:
    """Stable identity for one account + exact discovered evidence set."""
    account_id = str(target.get("account_id") or "")
    signal_ids = sorted({str(item) for item in target.get("signal_ids", []) if item})
    raw = json.dumps([account_id, signal_ids], separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


def dedupe_scores(targets: list[dict]) -> list[dict]:
    """One account per queue; retain strongest record and union its evidence IDs."""
    by_account: dict[str, dict] = {}
    for raw in targets:
        if not isinstance(raw, dict):
            continue
        account_id = raw.get("account_id")
        if not isinstance(account_id, str) or not account_id:
            continue
        current = by_account.get(account_id)
        if current is None or int(raw.get("score") or 0) > int(current.get("score") or 0):
            chosen = dict(raw)
            if current:
                chosen["signal_ids"] = sorted({
                    *[str(item) for item in current.get("signal_ids", []) if item],
                    *[str(item) for item in raw.get("signal_ids", []) if item],
                })
            by_account[account_id] = chosen
        elif current is not None:
            current["signal_ids"] = sorted({
                *[str(item) for item in current.get("signal_ids", []) if item],
                *[str(item) for item in raw.get("signal_ids", []) if item],
            })
    return list(by_account.values())


def history_by_account(history: dict | None) -> dict[str, dict]:
    if history is None:
        return {}
    if history.get("schema") != SCHEMA or not isinstance(history.get("targets"), list):
        raise ValueError(f"Expected {SCHEMA} history payload")
    output = {}
    for item in history["targets"]:
        if isinstance(item, dict) and isinstance(item.get("account_id"), str) and item["account_id"]:
            output[item["account_id"]] = item
    return output


def queue_one(target: dict, previous: dict | None, *, now: datetime) -> dict:
    account_id = target["account_id"]
    previous = previous or {}
    score_state = str(target.get("state") or "IGNORE")
    score = int(target.get("score") or 0)
    current_key = action_key(target)

    first_seen = parse_timestamp(previous.get("first_seen")) or now
    last_action_at = parse_timestamp(previous.get("last_action_at"))
    previous_state = str(previous.get("queue_state") or "")
    previous_action_key = str(previous.get("last_action_key") or previous.get("action_key") or "")

    queue_state = score_state if score_state in ELIGIBLE_SCORE_STATES else "SUPPRESSED"
    eligible = bool(target.get("eligible") is True and score_state in ELIGIBLE_SCORE_STATES)
    reason = "eligible_hot_target" if score_state == "HOT" else "eligible_warm_target"
    next_eligible_at = None

    activity_at = parse_timestamp(target.get("last_activity_at"))
    stale = activity_at is not None and activity_at < now - timedelta(hours=STALE_HOURS)

    if previous_state in TERMINAL_STATES:
        queue_state = previous_state
        eligible = False
        reason = f"progression_state_{previous_state.lower()}"
    elif not bool(target.get("eligible") is True) or score_state not in ELIGIBLE_SCORE_STATES:
        queue_state = "STALE" if stale else "SUPPRESSED"
        eligible = False
        reason = "stale_signal" if stale else "not_hot_or_warm"
    elif stale:
        queue_state = "STALE"
        eligible = False
        reason = "stale_signal"
    elif last_action_at and previous_action_key == current_key:
        queue_state = "ACTIONED"
        eligible = False
        reason = "evidence_already_actioned"
    elif last_action_at and last_action_at + timedelta(hours=TARGET_COOLDOWN_HOURS) > now:
        queue_state = "ACTIONED"
        eligible = False
        reason = "target_cooldown"
        next_eligible_at = last_action_at + timedelta(hours=TARGET_COOLDOWN_HOURS)

    record = {
        "account_id": account_id,
        "username": target.get("username"),
        "profile_url": target.get("profile_url"),
        "score": score,
        "score_state": score_state,
        "queue_state": queue_state,
        "eligible": eligible,
        "priority": None,
        "reason": reason,
        "first_seen": iso(first_seen),
        "last_seen": iso(now),
        "last_action_at": iso(last_action_at),
        "next_eligible_at": iso(next_eligible_at),
        "action_key": current_key,
        "last_action_key": previous.get("last_action_key"),
        "signal_ids": sorted({str(item) for item in target.get("signal_ids", []) if item}),
        "components": target.get("components", []),
        "last_activity_at": target.get("last_activity_at"),
        "location": target.get("location"),
    }
    return record


def unseen_history_record(previous: dict) -> dict:
    record = dict(previous)
    if record.get("queue_state") not in TERMINAL_STATES:
        record["queue_state"] = "STALE"
        record["reason"] = "not_seen_in_current_score_run"
    else:
        record["reason"] = f"progression_state_{str(record.get('queue_state')).lower()}"
    record["eligible"] = False
    record["priority"] = None
    record["next_eligible_at"] = None
    return record


def target_sort_key(item: dict) -> tuple:
    activity = parse_timestamp(item.get("last_activity_at"))
    activity_rank = activity.timestamp() if activity else 0
    return (-int(item.get("score") or 0), -activity_rank, str(item.get("username") or ""))


def build_queue(
    scores_payload: dict,
    history: dict | None = None,
    *,
    now: datetime | None = None,
    batch_size: int = 50,
) -> dict:
    if scores_payload.get("schema") != SCORE_SCHEMA or not isinstance(scores_payload.get("targets"), list):
        raise ValueError(f"Expected {SCORE_SCHEMA} score payload")
    if batch_size < 0:
        raise ValueError("batch_size must be nonnegative")

    now = now or datetime.now(timezone.utc)
    previous = history_by_account(history)
    current_targets = dedupe_scores(scores_payload["targets"])
    records = []
    seen = set()

    for target in current_targets:
        account_id = target["account_id"]
        seen.add(account_id)
        records.append(queue_one(target, previous.get(account_id), now=now))

    for account_id, old in previous.items():
        if account_id not in seen:
            records.append(unseen_history_record(old))

    eligible = sorted((item for item in records if item["eligible"]), key=target_sort_key)
    for priority, item in enumerate(eligible, start=1):
        item["priority"] = priority

    records.sort(key=lambda item: (
        0 if item["eligible"] else 1,
        item["priority"] if item["priority"] is not None else 10**9,
        -int(item.get("score") or 0),
        str(item.get("username") or ""),
    ))
    next_batch = [dict(item) for item in eligible[:batch_size]]
    counts = Counter(str(item.get("queue_state")) for item in records)

    unknown_states = set(counts) - set(TARGET_STATES)
    if unknown_states:
        raise ValueError(f"Unknown target states: {sorted(unknown_states)}")

    return {
        "schema": SCHEMA,
        "generated_at": iso(now),
        "source_generated_at": scores_payload.get("generated_at"),
        "target_count": len(records),
        "eligible_count": len(eligible),
        "batch_size": batch_size,
        "state_counts": dict(counts),
        "next_action_batch": next_batch,
        "targets": records,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scores", default="hunter-scores.json")
    parser.add_argument("--history", default=None)
    parser.add_argument("--out", default="hunter-queue.json")
    parser.add_argument("--batch-size", type=int, default=50)
    args = parser.parse_args()

    scores = json.loads(Path(args.scores).read_text(encoding="utf-8"))
    history = None
    if args.history:
        path = Path(args.history)
        if path.exists():
            history = json.loads(path.read_text(encoding="utf-8"))

    result = build_queue(scores, history, batch_size=args.batch_size)
    output = Path(args.out)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(
        f"hunter // queue {result['eligible_count']}/{result['target_count']} eligible // "
        f"batch {len(result['next_action_batch'])} // {result['state_counts']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
