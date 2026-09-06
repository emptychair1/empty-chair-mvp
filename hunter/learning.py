"""Sprint 7: learn from Hunter attribution outcomes without auto-changing scoring.

This stage analyzes target, signal, score-band, geography, account-type, and rule performance.
It emits evidence-backed recommendations only. It never modifies SCORE_WEIGHTS.
"""
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from config import SCORE_WEIGHTS

ATTRIBUTION_REPORT_SCHEMA = "empty-chair-hunter-attribution-report-v1"
SIGNALS_SCHEMA = "empty-chair-hunter-signals-v1"
SCHEMA = "empty-chair-hunter-learning-v1"
MODEL_VERSION = "hunter-score-v1"
MIN_OBSERVATIONS = 20
MIN_PAID = 3
MAX_WEIGHT_STEP = 5


def iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat()


def safe_rate(numerator: int, denominator: int) -> float:
    return round(numerator / denominator, 4) if denominator else 0.0


def score_band(score: int) -> str:
    if score >= 90:
        return "90-100"
    if score >= 80:
        return "80-89"
    if score >= 70:
        return "70-79"
    if score >= 60:
        return "60-69"
    return "0-59"


def location_key(location: object) -> str:
    if not isinstance(location, dict):
        return "UNKNOWN"
    city = str(location.get("city") or "").strip()
    region = str(location.get("region") or "").strip()
    country = str(location.get("country") or "").strip()
    return ", ".join(x for x in (city, region, country) if x) or "UNKNOWN"


def account_type(target: dict) -> str:
    rules = {str(c.get("rule")) for c in target.get("components", []) if isinstance(c, dict)}
    if "studio_account" in rules:
        return "STUDIO"
    if "individual_artist" in rules:
        return "INDIVIDUAL"
    return "UNKNOWN"


def signal_lookup(signals_payload: dict | None) -> dict[str, dict]:
    if signals_payload is None:
        return {}
    if signals_payload.get("schema") != SIGNALS_SCHEMA or not isinstance(signals_payload.get("signals"), list):
        raise ValueError(f"Expected {SIGNALS_SCHEMA} signals payload")
    out = {}
    for item in signals_payload["signals"]:
        if isinstance(item, dict) and isinstance(item.get("id"), str) and item["id"]:
            out[item["id"]] = item
    return out


def new_bucket() -> dict:
    return {"targets": set(), "paid_targets": set(), "revenue_cents": 0}


def add_bucket(bucket: dict, target: dict) -> None:
    hid = str(target.get("hunter_target_id") or target.get("account_id") or "")
    if not hid:
        return
    bucket["targets"].add(hid)
    revenue = int(target.get("revenue_cents") or 0)
    bucket["revenue_cents"] += revenue
    if revenue > 0 or target.get("furthest_stage") == "PAID":
        bucket["paid_targets"].add(hid)


def finalize_bucket(name: str, bucket: dict) -> dict:
    observations = len(bucket["targets"])
    paid = len(bucket["paid_targets"])
    revenue = int(bucket["revenue_cents"])
    return {
        "key": name,
        "observations": observations,
        "paid_targets": paid,
        "paid_conversion_rate": safe_rate(paid, observations),
        "revenue_cents": revenue,
        "revenue_per_target_cents": round(revenue / observations) if observations else 0,
    }


def ranked(bucket_map: dict[str, dict]) -> list[dict]:
    rows = [finalize_bucket(name, bucket) for name, bucket in bucket_map.items()]
    return sorted(rows, key=lambda r: (-r["revenue_per_target_cents"], -r["paid_conversion_rate"], -r["observations"], r["key"]))


def recommend_weights(rule_rows: list[dict], baseline_rate: float) -> list[dict]:
    recommendations = []
    for row in rule_rows:
        rule = row["key"]
        current = SCORE_WEIGHTS.get(rule)
        if current is None:
            continue
        observations = row["observations"]
        paid = row["paid_targets"]
        rate = row["paid_conversion_rate"]
        enough = observations >= MIN_OBSERVATIONS and paid >= MIN_PAID
        direction = "HOLD"
        delta = 0
        reason = "insufficient_sample"
        if enough:
            if baseline_rate > 0 and rate >= baseline_rate * 1.5:
                direction, delta, reason = "INCREASE", MAX_WEIGHT_STEP, "conversion_materially_above_baseline"
            elif baseline_rate > 0 and rate <= baseline_rate * 0.5:
                direction, delta, reason = "DECREASE", -MAX_WEIGHT_STEP, "conversion_materially_below_baseline"
            else:
                reason = "performance_near_baseline"
        recommendations.append({
            "rule": rule,
            "current_weight": current,
            "recommended_weight": current + delta,
            "delta": delta,
            "direction": direction,
            "reason": reason,
            "observations": observations,
            "paid_targets": paid,
            "paid_conversion_rate": rate,
            "baseline_paid_conversion_rate": baseline_rate,
            "actionable": bool(enough and delta != 0),
            "requires_human_approval": True,
        })
    return sorted(recommendations, key=lambda r: (not r["actionable"], -abs(r["delta"]), r["rule"]))


def build_learning_report(
    attribution_report: dict,
    signals_payload: dict | None = None,
    *,
    now: datetime | None = None,
) -> dict:
    if attribution_report.get("schema") != ATTRIBUTION_REPORT_SCHEMA or not isinstance(attribution_report.get("targets"), list):
        raise ValueError(f"Expected {ATTRIBUTION_REPORT_SCHEMA} attribution report")
    now = now or datetime.now(timezone.utc)
    lookup = signal_lookup(signals_payload)
    targets = [t for t in attribution_report["targets"] if isinstance(t, dict)]

    dimensions: dict[str, dict[str, dict]] = {
        "score_band": defaultdict(new_bucket),
        "rule": defaultdict(new_bucket),
        "geography": defaultdict(new_bucket),
        "account_type": defaultdict(new_bucket),
        "source": defaultdict(new_bucket),
        "query": defaultdict(new_bucket),
    }

    false_positives = []
    high_value = []
    total_paid = 0
    total_revenue = 0

    for target in targets:
        score = int(target.get("score") or 0)
        revenue = int(target.get("revenue_cents") or 0)
        paid = revenue > 0 or target.get("furthest_stage") == "PAID"
        total_paid += 1 if paid else 0
        total_revenue += revenue

        add_bucket(dimensions["score_band"][score_band(score)], target)
        add_bucket(dimensions["geography"][location_key(target.get("location"))], target)
        add_bucket(dimensions["account_type"][account_type(target)], target)

        rules = {str(c.get("rule")) for c in target.get("components", []) if isinstance(c, dict) and c.get("rule")}
        for rule in rules:
            add_bucket(dimensions["rule"][rule], target)

        sources = set()
        queries = set()
        for signal_id in target.get("signal_ids", []):
            signal = lookup.get(str(signal_id))
            if not signal:
                continue
            if signal.get("source"):
                sources.add(str(signal["source"]))
            if signal.get("query"):
                queries.add(str(signal["query"]))
        for source in sources or {"UNKNOWN"}:
            add_bucket(dimensions["source"][source], target)
        for query in queries or {"UNKNOWN"}:
            add_bucket(dimensions["query"][query], target)

        compact = {
            "hunter_target_id": target.get("hunter_target_id"),
            "username": target.get("username"),
            "score": score,
            "score_state": target.get("score_state"),
            "furthest_stage": target.get("furthest_stage"),
            "revenue_cents": revenue,
            "signal_ids": target.get("signal_ids", []),
        }
        if score >= 80 and target.get("furthest_stage") in {None, "VISIT"} and revenue == 0:
            false_positives.append(compact)
        if paid:
            high_value.append(compact)

    baseline_rate = safe_rate(total_paid, len(targets))
    rule_rows = ranked(dimensions["rule"])
    recommendations = recommend_weights(rule_rows, baseline_rate)
    actionable = sum(1 for item in recommendations if item["actionable"])

    return {
        "schema": SCHEMA,
        "generated_at": iso(now),
        "model_version": MODEL_VERSION,
        "current_score_weights": dict(SCORE_WEIGHTS),
        "sample_policy": {
            "min_observations_per_rule": MIN_OBSERVATIONS,
            "min_paid_targets_per_rule": MIN_PAID,
            "max_weight_step": MAX_WEIGHT_STEP,
            "automatic_weight_changes": False,
        },
        "target_count": len(targets),
        "paid_target_count": total_paid,
        "paid_conversion_rate": baseline_rate,
        "revenue_cents": total_revenue,
        "dimensions": {name: ranked(buckets) for name, buckets in dimensions.items()},
        "false_positive_count": len(false_positives),
        "false_positives": sorted(false_positives, key=lambda x: -x["score"]),
        "high_value_patterns": sorted(high_value, key=lambda x: (-x["revenue_cents"], -x["score"])),
        "weight_recommendations": recommendations,
        "actionable_recommendation_count": actionable,
        "requires_human_approval": True,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--attribution", default="hunter-attribution-report.json")
    parser.add_argument("--signals", default=None)
    parser.add_argument("--out", default="hunter-learning-report.json")
    args = parser.parse_args()
    attribution = json.loads(Path(args.attribution).read_text(encoding="utf-8"))
    signals = None
    if args.signals and Path(args.signals).exists():
        signals = json.loads(Path(args.signals).read_text(encoding="utf-8"))
    result = build_learning_report(attribution, signals)
    Path(args.out).write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(
        f"hunter // learning {result['paid_target_count']}/{result['target_count']} paid // "
        f"{result['actionable_recommendation_count']} actionable recommendations"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
