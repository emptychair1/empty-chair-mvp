"""Sprint 9: build a safe operator snapshot for manual Hunter review.

This module joins queue, attribution, validation, learning, and source artifacts into a compact
owner-review payload. It performs no outreach and never changes scoring weights.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

QUEUE_SCHEMA = "empty-chair-hunter-queue-v1"
ATTRIBUTION_REPORT_SCHEMA = "empty-chair-hunter-attribution-report-v1"
VALIDATION_SCHEMA = "empty-chair-hunter-validation-v1"
LEARNING_SCHEMA = "empty-chair-hunter-learning-v1"
SIGNALS_SCHEMA = "empty-chair-hunter-signals-v1"
SCHEMA = "empty-chair-hunter-operator-v1"
DECISIONS = ("PENDING", "APPROVED", "SUPPRESSED", "BAD_FIT")


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _require(payload: dict, schema: str, label: str) -> None:
    if not isinstance(payload, dict) or payload.get("schema") != schema:
        raise ValueError(f"Expected {schema} {label} payload")


def _rules(components: object) -> list[dict]:
    if not isinstance(components, list):
        return []
    output = []
    for item in components:
        if not isinstance(item, dict):
            continue
        rule = item.get("rule")
        if not isinstance(rule, str) or not rule:
            continue
        output.append({
            "rule": rule,
            "points": int(item.get("points") or 0),
            "evidence": item.get("evidence"),
        })
    return output


def _signal_evidence(signal_ids: list[str], by_id: dict[str, dict]) -> list[dict]:
    output = []
    for signal_id in signal_ids:
        item = by_id.get(signal_id)
        if not item:
            continue
        output.append({
            "id": signal_id,
            "source": item.get("source"),
            "query": item.get("query"),
            "source_url": item.get("source_url"),
            "title": item.get("title"),
            "snippet": item.get("snippet"),
            "matched_phrase": item.get("matched_phrase"),
        })
    return output


def build_snapshot(
    queue_payload: dict,
    attribution_payload: dict,
    validation_payload: dict,
    learning_payload: dict,
    signals_payload: dict | None = None,
    *,
    generated_at: str | None = None,
) -> dict:
    _require(queue_payload, QUEUE_SCHEMA, "queue")
    _require(attribution_payload, ATTRIBUTION_REPORT_SCHEMA, "attribution")
    _require(validation_payload, VALIDATION_SCHEMA, "validation")
    _require(learning_payload, LEARNING_SCHEMA, "learning")
    if signals_payload is not None:
        _require(signals_payload, SIGNALS_SCHEMA, "signals")

    attribution_by_account = {
        str(item.get("account_id")): item
        for item in attribution_payload.get("targets", [])
        if isinstance(item, dict) and item.get("account_id")
    }
    signals_by_id = {
        str(item.get("id")): item
        for item in (signals_payload or {}).get("signals", [])
        if isinstance(item, dict) and item.get("id")
    }

    records = []
    seen = set()
    for raw in queue_payload.get("targets", []):
        if not isinstance(raw, dict):
            continue
        account_id = raw.get("account_id")
        if not isinstance(account_id, str) or not account_id or account_id in seen:
            continue
        seen.add(account_id)
        attr = attribution_by_account.get(account_id, {})
        signal_ids = sorted({str(x) for x in raw.get("signal_ids", []) if x})
        records.append({
            "account_id": account_id,
            "hunter_target_id": attr.get("hunter_target_id"),
            "username": raw.get("username"),
            "profile_url": raw.get("profile_url"),
            "location": raw.get("location"),
            "score": int(raw.get("score") or 0),
            "score_state": raw.get("score_state"),
            "queue_state": raw.get("queue_state"),
            "eligible": raw.get("eligible") is True,
            "priority": raw.get("priority"),
            "reason": raw.get("reason"),
            "last_activity_at": raw.get("last_activity_at"),
            "first_seen": raw.get("first_seen"),
            "last_seen": raw.get("last_seen"),
            "last_action_at": raw.get("last_action_at"),
            "action_key": raw.get("action_key"),
            "signal_ids": signal_ids,
            "signals": _signal_evidence(signal_ids, signals_by_id),
            "components": _rules(raw.get("components")),
            "tracked_link": attr.get("tracked_link"),
            "furthest_stage": attr.get("furthest_stage"),
            "revenue_cents": int(attr.get("revenue_cents") or 0),
            "first_touch": attr.get("first_touch"),
            "latest_touch": attr.get("latest_touch"),
            "decision": "PENDING",
        })

    records.sort(key=lambda x: (
        0 if x.get("score_state") == "HOT" else 1,
        -int(x.get("score") or 0),
        int(x.get("priority") or 10**9),
        str(x.get("username") or ""),
    ))

    warnings = [
        item for item in validation_payload.get("checks", [])
        if isinstance(item, dict) and item.get("status") in {"WARN", "FAIL"}
    ]
    recommendations = [
        item for item in learning_payload.get("recommendations", [])
        if isinstance(item, dict)
    ]

    return {
        "schema": SCHEMA,
        "generated_at": generated_at or _iso_now(),
        "source_generated_at": queue_payload.get("generated_at"),
        "target_count": len(records),
        "hot_count": sum(1 for x in records if x.get("score_state") == "HOT"),
        "warm_count": sum(1 for x in records if x.get("score_state") == "WARM"),
        "actioned_count": sum(1 for x in records if x.get("queue_state") == "ACTIONED"),
        "paid_count": sum(1 for x in records if x.get("furthest_stage") == "PAID"),
        "revenue_cents": sum(int(x.get("revenue_cents") or 0) for x in records),
        "validation_status": validation_payload.get("status"),
        "validation_warnings": warnings,
        "learning_recommendations": recommendations,
        "targets": records,
    }


def apply_decision(target: dict, decision: str) -> dict:
    normalized = str(decision or "").upper()
    if normalized not in DECISIONS:
        raise ValueError("invalid decision")
    result = dict(target)
    result["decision"] = normalized
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--queue", default="hunter-queue-after-actions.json")
    parser.add_argument("--attribution", default="hunter-attribution-report.json")
    parser.add_argument("--validation", default="hunter-validation.json")
    parser.add_argument("--learning", default="hunter-learning-report.json")
    parser.add_argument("--signals", default="hunter-signals.json")
    parser.add_argument("--out", default="hunter-operator-snapshot.json")
    args = parser.parse_args()

    def load(path: str) -> dict:
        return json.loads(Path(path).read_text(encoding="utf-8"))

    snapshot = build_snapshot(
        load(args.queue),
        load(args.attribution),
        load(args.validation),
        load(args.learning),
        load(args.signals),
    )
    Path(args.out).write_text(json.dumps(snapshot, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(
        "hunter // operator "
        f"{snapshot['target_count']} targets // "
        f"{snapshot['hot_count']} hot // "
        f"{snapshot['paid_count']} paid"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
