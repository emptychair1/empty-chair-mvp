import json
from pathlib import Path

from validate_run import EXPECTED, render_summary, validate


def write_payloads(tmp_path: Path, *, empty_signals=False):
    payloads = {}
    for stage, (filename, schema) in EXPECTED.items():
        payload = {"schema": schema}
        if stage == "signals":
            payload["signals"] = [] if empty_signals else [{"id": "sig1"}]
            payload["signal_count"] = len(payload["signals"])
        elif stage in {"queue", "queue_after_actions"}:
            payload.update({"targets": [], "eligible_count": 0, "next_action_batch": []})
        elif stage == "actions":
            payload.update({"results": [], "result_count": 0})
        elif stage == "attribution":
            payload.update({"targets": [], "target_count": 0})
        elif stage == "attribution_report":
            payload.update({"targets": [], "target_count": 0})
        elif stage == "learning":
            payload.update({"recommendations": []})
        payloads[stage] = payload
        (tmp_path / filename).write_text(json.dumps(payload), encoding="utf-8")
    return payloads


def test_valid_run_passes(tmp_path):
    write_payloads(tmp_path)
    report = validate(tmp_path)
    assert report["status"] == "PASS"
    assert report["failure_count"] == 0


def test_empty_discovery_is_warning_not_failure(tmp_path):
    write_payloads(tmp_path, empty_signals=True)
    report = validate(tmp_path)
    assert report["status"] == "WARN"
    assert report["failure_count"] == 0
    assert any(x["code"] == "empty_discovery" for x in report["checks"])


def test_missing_required_artifact_fails(tmp_path):
    write_payloads(tmp_path)
    (tmp_path / EXPECTED["scores"][0]).unlink()
    report = validate(tmp_path)
    assert report["status"] == "FAIL"
    assert any(x["stage"] == "scores" and x["code"] == "missing" for x in report["checks"])


def test_schema_mismatch_fails(tmp_path):
    write_payloads(tmp_path)
    path = tmp_path / EXPECTED["learning"][0]
    path.write_text(json.dumps({"schema": "wrong"}), encoding="utf-8")
    report = validate(tmp_path)
    assert report["status"] == "FAIL"
    assert any(x["stage"] == "learning" and x["code"] == "schema_mismatch" for x in report["checks"])


def test_queue_eligible_count_mismatch_fails(tmp_path):
    write_payloads(tmp_path)
    path = tmp_path / EXPECTED["queue"][0]
    payload = json.loads(path.read_text())
    payload.update({"targets": [{"eligible": True}], "eligible_count": 0, "next_action_batch": []})
    path.write_text(json.dumps(payload), encoding="utf-8")
    report = validate(tmp_path)
    assert report["status"] == "FAIL"
    assert any(x["code"] == "eligible_count_mismatch" for x in report["checks"])


def test_action_result_count_mismatch_fails(tmp_path):
    write_payloads(tmp_path)
    path = tmp_path / EXPECTED["actions"][0]
    payload = json.loads(path.read_text())
    payload.update({"results": [{"status": "PREVIEW"}], "result_count": 0})
    path.write_text(json.dumps(payload), encoding="utf-8")
    report = validate(tmp_path)
    assert report["status"] == "FAIL"
    assert any(x["code"] == "result_count_mismatch" for x in report["checks"])


def test_attribution_target_count_mismatch_fails(tmp_path):
    write_payloads(tmp_path)
    queue_path = tmp_path / EXPECTED["queue_after_actions"][0]
    queue = json.loads(queue_path.read_text())
    queue["targets"] = [{"account_id": "acct1"}]
    queue_path.write_text(json.dumps(queue), encoding="utf-8")
    report = validate(tmp_path)
    assert report["status"] == "FAIL"
    assert any(x["code"] == "report_target_count_mismatch" or x["code"] == "target_manifest_count_mismatch" for x in report["checks"])


def test_summary_is_human_readable(tmp_path):
    write_payloads(tmp_path, empty_signals=True)
    summary = render_summary(validate(tmp_path))
    assert "Hunter Sprint 8 validation" in summary
    assert "empty_discovery" in summary
