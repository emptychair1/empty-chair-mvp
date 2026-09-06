"""Sprint 6: deterministic Hunter attribution from target to revenue.

This module creates stable target IDs and tracked links, ingests first-party lifecycle
 events, deduplicates conversions, preserves first/latest touch, and produces a revenue
 attribution report. It performs no outreach.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode

QUEUE_SCHEMA = "empty-chair-hunter-queue-v1"
SCHEMA = "empty-chair-hunter-attribution-v1"
EVENT_SCHEMA = "empty-chair-hunter-attribution-events-v1"
REPORT_SCHEMA = "empty-chair-hunter-attribution-report-v1"
EVENT_TYPES = ("VISIT", "SIGNUP", "TRIAL", "ARMED", "PAID")
EVENT_RANK = {name: index for index, name in enumerate(EVENT_TYPES)}


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


def iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat()


def target_id(account_id: object) -> str:
    if not isinstance(account_id, str) or not account_id:
        raise ValueError("account_id required")
    return "ht_" + hashlib.sha256(f"hunter:{account_id}".encode()).hexdigest()[:24]


def tracked_link(base_url: str, hunter_target_id: str) -> str:
    if not isinstance(base_url, str) or not base_url.startswith("https://"):
        raise ValueError("base_url must use https")
    base = base_url.rstrip("/") + "/signup"
    return f"{base}?{urlencode({'hunter_target_id': hunter_target_id, 'utm_source': 'hunter', 'utm_medium': 'targeted', 'utm_campaign': 'cancellation_recovery'})}"


def build_manifest(queue_payload: dict, *, base_url: str, now: datetime | None = None) -> dict:
    if queue_payload.get("schema") != QUEUE_SCHEMA or not isinstance(queue_payload.get("targets"), list):
        raise ValueError(f"Expected {QUEUE_SCHEMA} queue payload")
    now = now or datetime.now(timezone.utc)
    records = []
    seen = set()
    for item in queue_payload["targets"]:
        if not isinstance(item, dict):
            continue
        account_id = item.get("account_id")
        if not isinstance(account_id, str) or not account_id or account_id in seen:
            continue
        seen.add(account_id)
        hid = target_id(account_id)
        records.append({
            "hunter_target_id": hid,
            "account_id": account_id,
            "username": item.get("username"),
            "profile_url": item.get("profile_url"),
            "score": int(item.get("score") or 0),
            "score_state": item.get("score_state"),
            "queue_state": item.get("queue_state"),
            "action_key": item.get("action_key"),
            "signal_ids": sorted({str(x) for x in item.get("signal_ids", []) if x}),
            "components": item.get("components", []),
            "location": item.get("location"),
            "first_seen": item.get("first_seen"),
            "last_seen": item.get("last_seen"),
            "tracked_link": tracked_link(base_url, hid),
        })
    records.sort(key=lambda x: (-x["score"], str(x.get("username") or "")))
    return {
        "schema": SCHEMA,
        "generated_at": iso(now),
        "source_generated_at": queue_payload.get("generated_at"),
        "target_count": len(records),
        "targets": records,
    }


def event_key(event: dict) -> str:
    explicit = event.get("event_id")
    if isinstance(explicit, str) and explicit:
        return explicit
    normalized = [
        event.get("hunter_target_id"), event.get("event_type"), event.get("occurred_at"),
        event.get("entity_id"), event.get("amount_cents"), event.get("currency"),
    ]
    raw = json.dumps(normalized, separators=(",", ":"), ensure_ascii=True)
    return "he_" + hashlib.sha256(raw.encode()).hexdigest()[:24]


def normalize_events(payload: dict | None) -> list[dict]:
    if payload is None:
        return []
    if payload.get("schema") != EVENT_SCHEMA or not isinstance(payload.get("events"), list):
        raise ValueError(f"Expected {EVENT_SCHEMA} events payload")
    output = []
    seen = set()
    for raw in payload["events"]:
        if not isinstance(raw, dict):
            continue
        event_type = str(raw.get("event_type") or "").upper()
        if event_type not in EVENT_TYPES:
            continue
        hid = raw.get("hunter_target_id")
        occurred = parse_timestamp(raw.get("occurred_at"))
        if not isinstance(hid, str) or not hid.startswith("ht_") or occurred is None:
            continue
        amount = raw.get("amount_cents")
        if event_type == "PAID":
            if isinstance(amount, bool) or not isinstance(amount, int) or amount < 0:
                continue
        else:
            amount = None
        event = {
            "event_id": raw.get("event_id"),
            "hunter_target_id": hid,
            "event_type": event_type,
            "occurred_at": iso(occurred),
            "entity_id": raw.get("entity_id"),
            "amount_cents": amount,
            "currency": str(raw.get("currency") or "USD").upper() if event_type == "PAID" else None,
            "metadata": raw.get("metadata") if isinstance(raw.get("metadata"), dict) else {},
        }
        key = event_key(event)
        if key in seen:
            continue
        seen.add(key)
        event["event_id"] = key
        output.append(event)
    output.sort(key=lambda x: (x["occurred_at"], EVENT_RANK[x["event_type"]], x["event_id"]))
    return output


def merge_events(*payloads: dict | None, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    merged = []
    seen = set()
    for payload in payloads:
        for event in normalize_events(payload):
            if event["event_id"] in seen:
                continue
            seen.add(event["event_id"])
            merged.append(event)
    merged.sort(key=lambda x: (x["occurred_at"], EVENT_RANK[x["event_type"]], x["event_id"]))
    return {"schema": EVENT_SCHEMA, "generated_at": iso(now), "event_count": len(merged), "events": merged}


def attribution_report(manifest: dict, events_payload: dict | None, *, now: datetime | None = None) -> dict:
    if manifest.get("schema") != SCHEMA or not isinstance(manifest.get("targets"), list):
        raise ValueError(f"Expected {SCHEMA} manifest")
    now = now or datetime.now(timezone.utc)
    events = normalize_events(events_payload)
    by_target = {}
    for event in events:
        by_target.setdefault(event["hunter_target_id"], []).append(event)

    rows = []
    totals = Counter()
    revenue_cents = 0
    for target in manifest["targets"]:
        hid = target.get("hunter_target_id")
        history = by_target.get(hid, [])
        counts = Counter(e["event_type"] for e in history)
        revenue = sum(int(e.get("amount_cents") or 0) for e in history if e["event_type"] == "PAID")
        revenue_cents += revenue
        for event_type in EVENT_TYPES:
            if counts[event_type]:
                totals[event_type] += 1
        first_touch = history[0] if history else None
        latest_touch = history[-1] if history else None
        furthest = max((e["event_type"] for e in history), key=lambda name: EVENT_RANK[name], default=None)
        rows.append({
            **target,
            "first_touch": first_touch,
            "latest_touch": latest_touch,
            "furthest_stage": furthest,
            "event_counts": {k: counts[k] for k in EVENT_TYPES if counts[k]},
            "revenue_cents": revenue,
        })

    rows.sort(key=lambda x: (-x["revenue_cents"], -EVENT_RANK.get(x["furthest_stage"], -1), -int(x.get("score") or 0)))
    paid_targets = totals["PAID"]
    return {
        "schema": REPORT_SCHEMA,
        "generated_at": iso(now),
        "target_count": len(rows),
        "stage_target_counts": {k: totals[k] for k in EVENT_TYPES},
        "paid_target_count": paid_targets,
        "revenue_cents": revenue_cents,
        "revenue_per_target_cents": round(revenue_cents / len(rows)) if rows else 0,
        "paid_conversion_rate": round(paid_targets / len(rows), 4) if rows else 0.0,
        "targets": rows,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--queue", default="hunter-queue-after-actions.json")
    parser.add_argument("--events", default=None)
    parser.add_argument("--base-url", default="https://app.tryemptychair.com")
    parser.add_argument("--manifest-out", default="hunter-attribution.json")
    parser.add_argument("--report-out", default="hunter-attribution-report.json")
    args = parser.parse_args()
    queue_payload = json.loads(Path(args.queue).read_text(encoding="utf-8"))
    manifest = build_manifest(queue_payload, base_url=args.base_url)
    events = None
    if args.events and Path(args.events).exists():
        events = json.loads(Path(args.events).read_text(encoding="utf-8"))
    report = attribution_report(manifest, events)
    Path(args.manifest_out).write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    Path(args.report_out).write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"hunter // attribution {report['paid_target_count']}/{report['target_count']} paid // revenue ${report['revenue_cents']/100:.2f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
