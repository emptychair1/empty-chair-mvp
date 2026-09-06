"""Sprint 5: execute permitted Hunter acquisition actions safely and audibly.

The first live adapter is an explicitly configured HTTPS webhook owned/approved by the
operator. This module never automates Instagram, scrapes private data, or invents a
successful contact. If no approved adapter is configured, targets are BLOCKED rather
than marked ACTIONED.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import time
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable
from urllib.parse import urlparse

import httpx

from config import TARGET_COOLDOWN_HOURS
from target_queue import SCHEMA as QUEUE_SCHEMA, parse_timestamp

SCHEMA = "empty-chair-hunter-actions-v1"
ACTION_TYPE = "approved_webhook"
TRANSIENT_HTTP = {408, 425, 429, 500, 502, 503, 504}
SUCCESS_STATES = {"SUCCEEDED"}
MAX_ATTEMPTS = 3


def iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat()


def target_id(target: dict) -> str:
    raw = f"{target.get('account_id', '')}:{target.get('action_key', '')}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:24]


def valid_webhook_url(value: str | None) -> bool:
    if not isinstance(value, str) or not value:
        return False
    try:
        parsed = urlparse(value)
        return bool(parsed.scheme == "https" and parsed.hostname and not parsed.username and not parsed.password)
    except ValueError:
        return False


def validate_queue(payload: dict) -> None:
    if payload.get("schema") != QUEUE_SCHEMA or not isinstance(payload.get("next_action_batch"), list):
        raise ValueError(f"Expected {QUEUE_SCHEMA} queue payload")


def already_actioned(target: dict, history: dict | None) -> bool:
    if not history:
        return False
    if history.get("schema") != SCHEMA or not isinstance(history.get("results"), list):
        raise ValueError(f"Expected {SCHEMA} action history")
    action_key = str(target.get("action_key") or "")
    account_id = str(target.get("account_id") or "")
    return any(
        isinstance(item, dict)
        and item.get("status") in SUCCESS_STATES
        and item.get("account_id") == account_id
        and item.get("action_key") == action_key
        for item in history["results"]
    )


def eligibility(target: dict, history: dict | None, *, now: datetime) -> tuple[bool, str]:
    if target.get("eligible") is not True or target.get("queue_state") not in {"HOT", "WARM"}:
        return False, "queue_not_eligible"
    if not isinstance(target.get("account_id"), str) or not target.get("account_id"):
        return False, "missing_account_id"
    if not isinstance(target.get("action_key"), str) or not target.get("action_key"):
        return False, "missing_action_key"
    if already_actioned(target, history):
        return False, "duplicate_successful_action"
    last_action_at = parse_timestamp(target.get("last_action_at"))
    if last_action_at and last_action_at + timedelta(hours=TARGET_COOLDOWN_HOURS) > now:
        return False, "target_cooldown"
    return True, "eligible"


def action_payload(target: dict, *, now: datetime) -> dict:
    return {
        "schema": "empty-chair-hunter-action-request-v1",
        "target_id": target_id(target),
        "action_type": ACTION_TYPE,
        "requested_at": iso(now),
        "account_id": target.get("account_id"),
        "username": target.get("username"),
        "profile_url": target.get("profile_url"),
        "score": target.get("score"),
        "score_state": target.get("score_state"),
        "priority": target.get("priority"),
        "action_key": target.get("action_key"),
        "signal_ids": list(target.get("signal_ids") or []),
        "components": list(target.get("components") or []),
        "location": target.get("location"),
    }


def append_journal(path: Path | None, record: dict) -> None:
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, separators=(",", ":"), ensure_ascii=False) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def send_webhook(
    client: httpx.Client,
    url: str,
    payload: dict,
    *,
    token: str | None = None,
    max_attempts: int = MAX_ATTEMPTS,
    sleep: Callable[[float], None] = time.sleep,
) -> tuple[bool, int, int | None, str]:
    """Return success, attempts, final HTTP status, and a safe result reason."""
    headers = {"Content-Type": "application/json", "Idempotency-Key": payload["action_key"]}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    final_status = None
    for attempt in range(1, max_attempts + 1):
        try:
            response = client.post(url, json=payload, headers=headers)
            final_status = response.status_code
            if 200 <= response.status_code < 300:
                return True, attempt, response.status_code, "delivered"
            if response.status_code not in TRANSIENT_HTTP:
                return False, attempt, response.status_code, "non_retryable_http"
        except httpx.TransportError:
            final_status = None
        if attempt < max_attempts:
            sleep(0.5 * (2 ** (attempt - 1)))
    return False, max_attempts, final_status, "transient_failure_exhausted"


def execute_one(
    target: dict,
    history: dict | None,
    *,
    now: datetime,
    mode: str,
    webhook_url: str | None,
    webhook_token: str | None,
    client: httpx.Client,
    journal: Path | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> dict:
    allowed, reason = eligibility(target, history, now=now)
    base = {
        "target_id": target_id(target),
        "account_id": target.get("account_id"),
        "username": target.get("username"),
        "action_key": target.get("action_key"),
        "action_type": ACTION_TYPE,
        "started_at": iso(now),
        "completed_at": iso(now),
        "attempts": 0,
        "http_status": None,
    }
    if not allowed:
        return {**base, "status": "SKIPPED", "reason": reason}

    payload = action_payload(target, now=now)
    if mode == "preview":
        return {**base, "status": "PREVIEW", "reason": "preview_only", "request": payload}
    if not valid_webhook_url(webhook_url):
        return {**base, "status": "BLOCKED", "reason": "approved_webhook_not_configured"}

    append_journal(journal, {**base, "phase": "ATTEMPT_STARTED", "request": payload})
    success, attempts, http_status, result_reason = send_webhook(
        client,
        webhook_url,
        payload,
        token=webhook_token,
        sleep=sleep,
    )
    completed_at = datetime.now(timezone.utc)
    result = {
        **base,
        "status": "SUCCEEDED" if success else "FAILED",
        "reason": result_reason,
        "attempts": attempts,
        "http_status": http_status,
        "completed_at": iso(completed_at),
    }
    append_journal(journal, {**result, "phase": "ATTEMPT_FINISHED"})
    return result


def update_queue_after_actions(queue_payload: dict, results: list[dict], *, now: datetime) -> dict:
    by_account = {
        item.get("account_id"): item
        for item in results
        if isinstance(item, dict) and item.get("status") == "SUCCEEDED" and item.get("account_id")
    }
    updated = json.loads(json.dumps(queue_payload))
    for item in updated.get("targets", []):
        result = by_account.get(item.get("account_id"))
        if not result or result.get("action_key") != item.get("action_key"):
            continue
        item["queue_state"] = "ACTIONED"
        item["eligible"] = False
        item["priority"] = None
        item["reason"] = "action_succeeded"
        item["last_action_at"] = result.get("completed_at") or iso(now)
        item["last_action_key"] = item.get("action_key")
    updated["next_action_batch"] = [
        item for item in updated.get("targets", []) if item.get("eligible") is True
    ][: int(updated.get("batch_size") or 50)]
    updated["eligible_count"] = sum(1 for item in updated.get("targets", []) if item.get("eligible") is True)
    updated["generated_at"] = iso(now)
    return updated


def run_actions(
    queue_payload: dict,
    history: dict | None = None,
    *,
    now: datetime | None = None,
    mode: str = "preview",
    webhook_url: str | None = None,
    webhook_token: str | None = None,
    client: httpx.Client | None = None,
    journal: Path | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> tuple[dict, dict]:
    validate_queue(queue_payload)
    if mode not in {"preview", "execute"}:
        raise ValueError("mode must be preview or execute")
    now = now or datetime.now(timezone.utc)
    own_client = client is None
    client = client or httpx.Client(timeout=10, follow_redirects=False)
    try:
        results = [
            execute_one(
                target,
                history,
                now=now,
                mode=mode,
                webhook_url=webhook_url,
                webhook_token=webhook_token,
                client=client,
                journal=journal,
                sleep=sleep,
            )
            for target in queue_payload["next_action_batch"]
            if isinstance(target, dict)
        ]
    finally:
        if own_client:
            client.close()
    counts = Counter(str(item.get("status")) for item in results)
    payload = {
        "schema": SCHEMA,
        "generated_at": iso(now),
        "mode": mode,
        "action_type": ACTION_TYPE,
        "result_count": len(results),
        "status_counts": dict(counts),
        "results": results,
    }
    return payload, update_queue_after_actions(queue_payload, results, now=now)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--queue", default="hunter-queue.json")
    parser.add_argument("--history", default=None)
    parser.add_argument("--out", default="hunter-actions.json")
    parser.add_argument("--queue-out", default="hunter-queue-after-actions.json")
    parser.add_argument("--journal", default="hunter-action-journal.jsonl")
    parser.add_argument("--mode", choices=("preview", "execute"), default="preview")
    args = parser.parse_args()

    queue_payload = json.loads(Path(args.queue).read_text(encoding="utf-8"))
    history = None
    if args.history and Path(args.history).exists():
        history = json.loads(Path(args.history).read_text(encoding="utf-8"))
    actions, updated_queue = run_actions(
        queue_payload,
        history,
        mode=args.mode,
        webhook_url=os.getenv("HUNTER_ACTION_WEBHOOK_URL"),
        webhook_token=os.getenv("HUNTER_ACTION_WEBHOOK_TOKEN"),
        journal=Path(args.journal) if args.mode == "execute" else None,
    )
    Path(args.out).write_text(json.dumps(actions, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    Path(args.queue_out).write_text(json.dumps(updated_queue, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"hunter // actions {actions['status_counts']} // mode {actions['mode']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
