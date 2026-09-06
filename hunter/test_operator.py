import pytest

from operator_console import DECISIONS, SCHEMA, apply_decision, build_snapshot


def payloads():
    queue = {
        "schema": "empty-chair-hunter-queue-v1",
        "generated_at": "2026-09-06T15:00:00+00:00",
        "targets": [
            {
                "account_id": "acct-hot",
                "username": "hot.artist",
                "profile_url": "https://www.instagram.com/hot.artist/",
                "score": 95,
                "score_state": "HOT",
                "queue_state": "HOT",
                "eligible": True,
                "priority": 1,
                "signal_ids": ["sig2", "sig1", "sig1"],
                "components": [
                    {"rule": "explicit_cancellation", "points": 35, "evidence": "had a cancellation"},
                    {"rule": "urgent", "points": 20, "evidence": "today"},
                ],
            },
            {
                "account_id": "acct-warm",
                "username": "warm.artist",
                "score": 65,
                "score_state": "WARM",
                "queue_state": "ACTIONED",
                "eligible": False,
                "priority": None,
                "signal_ids": ["sig3"],
                "components": [],
            },
        ],
    }
    attribution = {
        "schema": "empty-chair-hunter-attribution-report-v1",
        "targets": [
            {
                "account_id": "acct-hot",
                "hunter_target_id": "ht_hot",
                "tracked_link": "https://app.tryemptychair.com/signup?hunter_target_id=ht_hot",
                "furthest_stage": "PAID",
                "revenue_cents": 9900,
                "first_touch": {"event_type": "VISIT"},
                "latest_touch": {"event_type": "PAID"},
            },
            {
                "account_id": "acct-warm",
                "hunter_target_id": "ht_warm",
                "furthest_stage": "SIGNUP",
                "revenue_cents": 0,
            },
        ],
    }
    validation = {
        "schema": "empty-chair-hunter-validation-v1",
        "status": "WARN",
        "checks": [
            {"stage": "discovery", "status": "WARN", "code": "empty_discovery"},
            {"stage": "queue", "status": "PASS", "code": "schema_ok"},
        ],
    }
    learning = {
        "schema": "empty-chair-hunter-learning-v1",
        "recommendations": [
            {"rule": "urgent", "current_weight": 20, "recommended_weight": 25, "requires_human_approval": True}
        ],
    }
    return queue, attribution, validation, learning


def test_build_snapshot_ranks_hot_and_joins_outcomes():
    snapshot = build_snapshot(*payloads(), generated_at="2026-09-06T16:00:00+00:00")
    assert snapshot["schema"] == SCHEMA
    assert snapshot["target_count"] == 2
    assert snapshot["hot_count"] == 1
    assert snapshot["warm_count"] == 1
    assert snapshot["actioned_count"] == 1
    assert snapshot["paid_count"] == 1
    assert snapshot["revenue_cents"] == 9900
    assert snapshot["targets"][0]["account_id"] == "acct-hot"
    assert snapshot["targets"][0]["signal_ids"] == ["sig1", "sig2"]
    assert snapshot["targets"][0]["furthest_stage"] == "PAID"
    assert snapshot["targets"][0]["decision"] == "PENDING"


def test_snapshot_surfaces_only_validation_warnings_and_failures():
    snapshot = build_snapshot(*payloads())
    assert len(snapshot["validation_warnings"]) == 1
    assert snapshot["validation_warnings"][0]["code"] == "empty_discovery"
    assert snapshot["learning_recommendations"][0]["rule"] == "urgent"


def test_duplicate_accounts_are_ignored():
    queue, attribution, validation, learning = payloads()
    queue["targets"].append(dict(queue["targets"][0]))
    snapshot = build_snapshot(queue, attribution, validation, learning)
    assert snapshot["target_count"] == 2


def test_bad_schema_fails_closed():
    queue, attribution, validation, learning = payloads()
    queue["schema"] = "wrong"
    with pytest.raises(ValueError):
        build_snapshot(queue, attribution, validation, learning)


def test_apply_decision_only_allows_locked_states():
    target = {"account_id": "acct", "decision": "PENDING"}
    for decision in DECISIONS:
        assert apply_decision(target, decision)["decision"] == decision
    with pytest.raises(ValueError):
        apply_decision(target, "CONTACTED")
