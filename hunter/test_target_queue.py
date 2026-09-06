from datetime import datetime, timedelta, timezone

import pytest

from target_queue import SCHEMA, action_key, build_queue

NOW = datetime(2026, 9, 6, 14, 0, tzinfo=timezone.utc)


def scored(**overrides):
    base = {
        "account_id": "acct-1",
        "username": "needle.person",
        "profile_url": "https://www.instagram.com/needle.person/",
        "score": 90,
        "state": "HOT",
        "eligible": True,
        "components": [{"rule": "explicit_cancellation", "points": 35, "evidence": "had a cancellation"}],
        "signal_ids": ["sig-1"],
        "last_activity_at": (NOW - timedelta(hours=2)).isoformat(),
        "location": {"city": "Athens", "region": "GA", "country": "US"},
    }
    base.update(overrides)
    return base


def scores(*targets):
    return {
        "schema": "empty-chair-hunter-scores-v1",
        "generated_at": NOW.isoformat(),
        "targets": list(targets),
    }


def history(*targets):
    return {"schema": SCHEMA, "targets": list(targets)}


def old_record(**overrides):
    target = scored()
    base = {
        "account_id": target["account_id"],
        "username": target["username"],
        "profile_url": target["profile_url"],
        "score": target["score"],
        "score_state": "HOT",
        "queue_state": "HOT",
        "eligible": True,
        "priority": 1,
        "reason": "eligible_hot_target",
        "first_seen": (NOW - timedelta(days=2)).isoformat(),
        "last_seen": (NOW - timedelta(hours=12)).isoformat(),
        "last_action_at": None,
        "next_eligible_at": None,
        "action_key": action_key(target),
        "last_action_key": None,
        "signal_ids": ["sig-1"],
        "components": [],
        "last_activity_at": target["last_activity_at"],
        "location": target["location"],
    }
    base.update(overrides)
    return base


def test_accepts_only_hot_and_warm_and_orders_score_descending():
    result = build_queue(scores(
        scored(account_id="warm", username="warm", score=65, state="WARM"),
        scored(account_id="hot-low", username="hot.low", score=82),
        scored(account_id="hot-high", username="hot.high", score=99),
        scored(account_id="ignore", username="ignore", score=55, state="IGNORE"),
    ), now=NOW)

    assert [item["account_id"] for item in result["next_action_batch"]] == ["hot-high", "hot-low", "warm"]
    assert [item["priority"] for item in result["next_action_batch"]] == [1, 2, 3]
    ignored = next(item for item in result["targets"] if item["account_id"] == "ignore")
    assert ignored["eligible"] is False
    assert ignored["queue_state"] == "SUPPRESSED"


def test_stale_hot_target_is_not_actionable_even_if_score_stays_hot():
    result = build_queue(scores(scored(
        score=90,
        state="HOT",
        last_activity_at=(NOW - timedelta(hours=73)).isoformat(),
    )), now=NOW)
    item = result["targets"][0]
    assert item["queue_state"] == "STALE"
    assert item["eligible"] is False
    assert item["reason"] == "stale_signal"


def test_unknown_activity_is_not_guessed_stale():
    result = build_queue(scores(scored(last_activity_at=None)), now=NOW)
    item = result["targets"][0]
    assert item["queue_state"] == "HOT"
    assert item["eligible"] is True


def test_unresolved_or_rejected_scoring_contract_is_suppressed():
    result = build_queue(scores(scored(state="HOT", eligible=False)), now=NOW)
    item = result["targets"][0]
    assert item["queue_state"] == "SUPPRESSED"
    assert item["eligible"] is False


def test_target_cooldown_blocks_until_72_hours():
    previous = old_record(
        queue_state="ACTIONED",
        eligible=False,
        last_action_at=(NOW - timedelta(hours=20)).isoformat(),
        last_action_key="different-evidence",
    )
    result = build_queue(scores(scored(signal_ids=["sig-new"])), history(previous), now=NOW)
    item = result["targets"][0]
    assert item["queue_state"] == "ACTIONED"
    assert item["eligible"] is False
    assert item["reason"] == "target_cooldown"
    assert item["next_eligible_at"] == (NOW + timedelta(hours=52)).isoformat()


def test_after_cooldown_new_evidence_becomes_eligible_again():
    previous = old_record(
        queue_state="ACTIONED",
        eligible=False,
        last_action_at=(NOW - timedelta(hours=73)).isoformat(),
        last_action_key="old-evidence",
    )
    result = build_queue(scores(scored(signal_ids=["sig-new"])), history(previous), now=NOW)
    item = result["targets"][0]
    assert item["queue_state"] == "HOT"
    assert item["eligible"] is True


def test_same_evidence_cannot_be_replayed_even_after_cooldown():
    target = scored(signal_ids=["sig-1", "sig-2"])
    previous = old_record(
        queue_state="ACTIONED",
        eligible=False,
        last_action_at=(NOW - timedelta(days=7)).isoformat(),
        last_action_key=action_key(target),
        action_key=action_key(target),
        signal_ids=["sig-1", "sig-2"],
    )
    result = build_queue(scores(target), history(previous), now=NOW)
    item = result["targets"][0]
    assert item["queue_state"] == "ACTIONED"
    assert item["eligible"] is False
    assert item["reason"] == "evidence_already_actioned"


def test_progression_states_are_preserved_and_never_retargeted():
    for state in ("CLICKED", "TRIAL", "ARMED", "PAID", "SUPPRESSED"):
        result = build_queue(scores(scored()), history(old_record(queue_state=state)), now=NOW)
        item = result["targets"][0]
        assert item["queue_state"] == state
        assert item["eligible"] is False


def test_first_seen_persists_and_last_seen_advances():
    first_seen = (NOW - timedelta(days=4)).isoformat()
    result = build_queue(scores(scored()), history(old_record(first_seen=first_seen)), now=NOW)
    item = result["targets"][0]
    assert item["first_seen"] == first_seen
    assert item["last_seen"] == NOW.isoformat()


def test_unseen_history_is_carried_forward_as_stale():
    previous = old_record(account_id="old", username="old.artist")
    result = build_queue(scores(), history(previous), now=NOW)
    item = result["targets"][0]
    assert item["account_id"] == "old"
    assert item["queue_state"] == "STALE"
    assert item["eligible"] is False
    assert item["reason"] == "not_seen_in_current_score_run"


def test_duplicate_account_scores_collapse_and_union_signal_ids():
    result = build_queue(scores(
        scored(account_id="same", username="same", score=70, state="WARM", signal_ids=["sig-a"]),
        scored(account_id="same", username="same", score=95, state="HOT", signal_ids=["sig-b"]),
    ), now=NOW)
    assert result["target_count"] == 1
    item = result["targets"][0]
    assert item["score"] == 95
    assert item["signal_ids"] == ["sig-a", "sig-b"]


def test_action_key_is_stable_across_signal_order():
    one = scored(signal_ids=["b", "a", "a"])
    two = scored(signal_ids=["a", "b"])
    assert action_key(one) == action_key(two)


def test_batch_size_caps_next_actions_without_dropping_queue_targets():
    payload = scores(*[
        scored(account_id=f"acct-{index}", username=f"artist{index}", score=100 - index)
        for index in range(5)
    ])
    result = build_queue(payload, now=NOW, batch_size=2)
    assert result["target_count"] == 5
    assert result["eligible_count"] == 5
    assert len(result["next_action_batch"]) == 2


def test_bad_contracts_and_negative_batch_size_fail_closed():
    with pytest.raises(ValueError):
        build_queue({"schema": "wrong", "targets": []}, now=NOW)
    with pytest.raises(ValueError):
        build_queue(scores(), {"schema": "wrong", "targets": []}, now=NOW)
    with pytest.raises(ValueError):
        build_queue(scores(), now=NOW, batch_size=-1)
