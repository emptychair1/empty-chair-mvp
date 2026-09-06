"""Sprint 8: validate a completed Hunter run without confusing no-data with failure.

The validator checks artifact presence, JSON/schema integrity, cross-stage counts, and
basic state invariants. Empty discovery is a WARN because a healthy run can legitimately
find no cancellation signals. Malformed or missing required artifacts are FAIL.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = "empty-chair-hunter-validation-v1"
EXPECTED = {
    "signals": ("hunter-signals.json", "empty-chair-hunter-signals-v1"),
    "artists": ("hunter-artists.json", "empty-chair-hunter-artists-v1"),
    "scores": ("hunter-scores.json", "empty-chair-hunter-scores-v1"),
    "queue": ("hunter-queue.json", "empty-chair-hunter-queue-v1"),
    "actions": ("hunter-actions.json", "empty-chair-hunter-actions-v1"),
    "queue_after_actions": ("hunter-queue-after-actions.json", "empty-chair-hunter-queue-v1"),
    "attribution": ("hunter-attribution.json", "empty-chair-hunter-attribution-v1"),
    "attribution_report": ("hunter-attribution-report.json", "empty-chair-hunter-attribution-report-v1"),
    "learning": ("hunter-learning-report.json", "empty-chair-hunter-learning-v1"),
}


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load(path: Path) -> tuple[dict | None, str | None]:
    if not path.exists():
        return None, "missing"
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return None, f"invalid_json:{type(exc).__name__}"
    if not isinstance(value, dict):
        return None, "root_not_object"
    return value, None


def validate(directory: Path) -> dict:
    checks: list[dict] = []
    payloads: dict[str, dict] = {}

    for stage, (filename, schema) in EXPECTED.items():
        payload, error = _load(directory / filename)
        if error:
            checks.append({"stage": stage, "status": "FAIL", "code": error, "file": filename})
            continue
        payloads[stage] = payload
        actual = payload.get("schema")
        if actual != schema:
            checks.append({
                "stage": stage,
                "status": "FAIL",
                "code": "schema_mismatch",
                "expected": schema,
                "actual": actual,
                "file": filename,
            })
        else:
            checks.append({"stage": stage, "status": "PASS", "code": "schema_ok", "file": filename})

    signals = payloads.get("signals", {})
    signal_count = signals.get("signal_count")
    if signal_count is None and isinstance(signals.get("signals"), list):
        signal_count = len(signals["signals"])
    if signal_count == 0:
        checks.append({
            "stage": "discovery",
            "status": "WARN",
            "code": "empty_discovery",
            "message": "Collector completed but found zero public cancellation signals.",
        })

    queue = payloads.get("queue", {})
    targets = queue.get("targets") if isinstance(queue.get("targets"), list) else []
    eligible = [x for x in targets if isinstance(x, dict) and x.get("eligible") is True]
    declared_eligible = queue.get("eligible_count")
    if isinstance(declared_eligible, int) and declared_eligible != len(eligible):
        checks.append({
            "stage": "queue",
            "status": "FAIL",
            "code": "eligible_count_mismatch",
            "declared": declared_eligible,
            "actual": len(eligible),
        })

    batch = queue.get("next_action_batch") if isinstance(queue.get("next_action_batch"), list) else []
    if len(batch) > len(eligible):
        checks.append({"stage": "queue", "status": "FAIL", "code": "batch_exceeds_eligible"})

    actions = payloads.get("actions", {})
    results = actions.get("results") if isinstance(actions.get("results"), list) else []
    declared_results = actions.get("result_count")
    if isinstance(declared_results, int) and declared_results != len(results):
        checks.append({
            "stage": "actions",
            "status": "FAIL",
            "code": "result_count_mismatch",
            "declared": declared_results,
            "actual": len(results),
        })

    attribution = payloads.get("attribution", {})
    attribution_targets = attribution.get("targets") if isinstance(attribution.get("targets"), list) else []
    after = payloads.get("queue_after_actions", {})
    after_targets = after.get("targets") if isinstance(after.get("targets"), list) else []
    if attribution_targets and len(attribution_targets) != len(after_targets):
        checks.append({
            "stage": "attribution",
            "status": "FAIL",
            "code": "target_manifest_count_mismatch",
            "manifest": len(attribution_targets),
            "queue": len(after_targets),
        })

    report = payloads.get("attribution_report", {})
    if isinstance(report.get("target_count"), int) and report.get("target_count") != len(attribution_targets):
        checks.append({
            "stage": "attribution_report",
            "status": "FAIL",
            "code": "report_target_count_mismatch",
            "declared": report.get("target_count"),
            "actual": len(attribution_targets),
        })

    failures = sum(1 for item in checks if item["status"] == "FAIL")
    warnings = sum(1 for item in checks if item["status"] == "WARN")
    status = "FAIL" if failures else ("WARN" if warnings else "PASS")
    return {
        "schema": SCHEMA,
        "generated_at": _iso_now(),
        "status": status,
        "failure_count": failures,
        "warning_count": warnings,
        "checks": checks,
    }


def render_summary(report: dict) -> str:
    lines = [
        "## Hunter Sprint 8 validation",
        "",
        f"**Status:** {report['status']}  ",
        f"**Failures:** {report['failure_count']}  ",
        f"**Warnings:** {report['warning_count']}",
        "",
        "| Stage | Status | Diagnostic |",
        "| --- | --- | --- |",
    ]
    for item in report["checks"]:
        lines.append(f"| {item.get('stage','')} | {item.get('status','')} | {item.get('code','')} |")
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dir", default=".")
    parser.add_argument("--out", default="hunter-validation.json")
    parser.add_argument("--summary-out", default=None)
    parser.add_argument("--strict", action="store_true", help="Return nonzero when validation status is FAIL")
    args = parser.parse_args()

    report = validate(Path(args.dir))
    Path(args.out).write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    if args.summary_out:
        Path(args.summary_out).write_text(render_summary(report), encoding="utf-8")
    print(f"hunter // validation {report['status']} // {report['failure_count']} fail // {report['warning_count']} warn")
    return 1 if args.strict and report["status"] == "FAIL" else 0


if __name__ == "__main__":
    raise SystemExit(main())
