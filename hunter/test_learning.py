from datetime import datetime, timezone

import pytest

from learning import (
    SCHEMA,
    build_learning_report,
    recommend_weights,
    score_band,
)

NOW = datetime(2026, 9, 6, 15, 0, tzinfo=timezone.utc)


def target(i, *, score=90, stage=None, revenue=0, rules=None, location=None, signals=None):
    rules = rules or ["explicit_cancellation"]
    return {
        "hunter_target_id": f"ht_{i:024d}",
        "account_id": f"acct-{i}",
        "username": f"artist{i}",
        "score": score,
        "score_state": "HOT" if score >= 80 else "WARM",
        "components": [{"rule": rule, "points": 1, "evidence": rule} for rule in rules],
        "location": location or {"city": "Athens", "region": "GA", "country": "US"},
        "signal_ids": signals or [f"sig-{i}"],
        "furthest_stage": stage,
        "revenue_cents": revenue,
    }


def report(*targets):
    return {
        "schema": "empty-chair-hunter-attribution-report-v1",
        "target_count": len(targets),
        "targets": list(targets),
    }


def signals(*items):
    return {
        "schema": "empty-chair-hunter-signals-v1",
        "signals": list(items),
    }


def test_score_bands_are_deterministic():
    assert score_band(100) == "90-100"
    assert score_band(85) == "80-89"
    assert score_band(75) == "70-79"
    assert score_band(65) == "60-69"
    assert score_band(59) == "0-59"


def test_learning_report_tracks_revenue_score_geography_account_type_and_rules():
    payload = report(
        target(1, score=95, stage="PAID", revenue=12000, rules=["explicit_cancellation", "individual_artist"]),
        target(2, score=82, stage="SIGNUP", revenue=0, rules=["explicit_cancellation", "studio_account"]),
    )
    out = build_learning_report(payload, now=NOW)
    assert out["schema"] == SCHEMA
    assert out["target_count"] == 2
    assert out["paid_target_count"] == 1
    assert out["revenue_cents"] == 12000
    assert out["dimensions"]["score_band"][0]["key"] == "90-100"
    assert any(row["key"] == "Athens, GA, US" for row in out["dimensions"]["geography"])
    assert any(row["key"] == "INDIVIDUAL" for row in out["dimensions"]["account_type"])
    assert any(row["key"] == "explicit_cancellation" for row in out["dimensions"]["rule"])


def test_source_and_query_are_joined_from_signal_ids():
    payload = report(target(1, stage="PAID", revenue=5000, signals=["sig-1"]))
    signal_payload = signals({"id": "sig-1", "source": "bing", "query": "tattoo artist cancellation"})
    out = build_learning_report(payload, signal_payload, now=NOW)
    assert out["dimensions"]["source"][0]["key"] == "bing"
    assert out["dimensions"]["query"][0]["key"] == "tattoo artist cancellation"


def test_missing_signal_metadata_falls_back_to_unknown():
    out = build_learning_report(report(target(1)), None, now=NOW)
    assert out["dimensions"]["source"][0]["key"] == "UNKNOWN"
    assert out["dimensions"]["query"][0]["key"] == "UNKNOWN"


def test_hot_nonconverters_are_flagged_as_false_positives():
    out = build_learning_report(
        report(
            target(1, score=95, stage=None),
            target(2, score=90, stage="VISIT"),
            target(3, score=90, stage="SIGNUP"),
        ),
        now=NOW,
    )
    assert out["false_positive_count"] == 2
    assert {x["username"] for x in out["false_positives"]} == {"artist1", "artist2"}


def test_paid_targets_are_high_value_patterns_sorted_by_revenue():
    out = build_learning_report(
        report(
            target(1, stage="PAID", revenue=1000),
            target(2, stage="PAID", revenue=9000),
        ),
        now=NOW,
    )
    assert [x["username"] for x in out["high_value_patterns"]] == ["artist2", "artist1"]


def test_small_samples_never_produce_actionable_weight_changes():
    rows = [{
        "key": "explicit_cancellation",
        "observations": 19,
        "paid_targets": 10,
        "paid_conversion_rate": 0.5,
        "revenue_cents": 0,
        "revenue_per_target_cents": 0,
    }]
    rec = recommend_weights(rows, 0.1)[0]
    assert rec["actionable"] is False
    assert rec["recommended_weight"] == rec["current_weight"]
    assert rec["reason"] == "insufficient_sample"


def test_enough_evidence_can_recommend_bounded_increase_without_applying_it():
    rows = [{
        "key": "explicit_cancellation",
        "observations": 30,
        "paid_targets": 9,
        "paid_conversion_rate": 0.3,
        "revenue_cents": 0,
        "revenue_per_target_cents": 0,
    }]
    rec = recommend_weights(rows, 0.1)[0]
    assert rec["actionable"] is True
    assert rec["delta"] == 5
    assert rec["recommended_weight"] == rec["current_weight"] + 5
    assert rec["requires_human_approval"] is True


def test_enough_evidence_can_recommend_bounded_decrease():
    rows = [{
        "key": "urgent",
        "observations": 40,
        "paid_targets": 3,
        "paid_conversion_rate": 0.075,
        "revenue_cents": 0,
        "revenue_per_target_cents": 0,
    }]
    rec = recommend_weights(rows, 0.2)[0]
    assert rec["actionable"] is True
    assert rec["delta"] == -5


def test_report_never_mutates_weights_and_marks_human_approval_required():
    out = build_learning_report(report(*[target(i) for i in range(1, 25)]), now=NOW)
    assert out["sample_policy"]["automatic_weight_changes"] is False
    assert out["requires_human_approval"] is True
    assert out["current_score_weights"]["explicit_cancellation"] == 35


def test_invalid_attribution_and_signal_schemas_fail_closed():
    with pytest.raises(ValueError):
        build_learning_report({"schema": "wrong", "targets": []}, now=NOW)
    with pytest.raises(ValueError):
        build_learning_report(report(target(1)), {"schema": "wrong", "signals": []}, now=NOW)
