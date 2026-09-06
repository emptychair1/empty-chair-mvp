from datetime import datetime, timedelta, timezone

import pytest

from score import ranking_separation, score_account, score_payload

NOW = datetime(2026, 9, 6, 14, 0, tzinfo=timezone.utc)


def account(**overrides):
    base = {
        "status": "RESOLVED",
        "account_id": "acct-1",
        "username": "needle.person",
        "profile_url": "https://www.instagram.com/needle.person/",
        "is_tattoo_artist": True,
        "account_type": "individual",
        "active_commercial_account": True,
        "last_activity_at": None,
        "classification_evidence": {"tattoo_artist": "tattoo artist"},
        "profile_context": "Independent tattoo artist. DM me to book.",
        "location": None,
        "signals": [{"id": "sig-1"}],
    }
    base.update(overrides)
    return base


def signal(**overrides):
    base = {
        "id": "sig-1",
        "title": "Tattoo artist had a cancellation today",
        "snippet": "Last minute cancellation today. Full day $500.",
        "matched_phrase": "had a cancellation",
    }
    base.update(overrides)
    return base


def test_hot_threshold_is_exactly_80_without_guessing_freshness():
    result = score_account(account(), [signal(snippet="last minute cancellation today")], now=NOW)
    assert result["score"] == 80
    assert result["state"] == "HOT"
    assert [item["rule"] for item in result["components"]] == [
        "explicit_cancellation",
        "urgent",
        "individual_artist",
        "active_commercial_account",
    ]


def test_warm_threshold_is_exactly_60():
    result = score_account(
        account(active_commercial_account=None),
        [signal(title="Tattoo artist had a cancellation", snippet="Cancellation available", matched_phrase="had a cancellation")],
        now=NOW,
    )
    assert result["score"] == 50
    assert result["state"] == "IGNORE"

    result = score_account(
        account(active_commercial_account=True),
        [signal(title="Tattoo artist had a cancellation", snippet="Cancellation available", matched_phrase="had a cancellation")],
        now=NOW,
    )
    assert result["score"] == 60
    assert result["state"] == "WARM"


def test_complete_fresh_us_cancellation_caps_at_100_with_explanations():
    result = score_account(
        account(
            last_activity_at=(NOW - timedelta(hours=2)).isoformat(),
            location={"city": "Athens", "region": "GA", "country": "US"},
        ),
        [signal()],
        now=NOW,
    )
    assert result["raw_score"] == 100
    assert result["score"] == 100
    assert result["state"] == "HOT"
    rules = {item["rule"] for item in result["components"]}
    assert rules == {
        "explicit_cancellation",
        "urgent",
        "individual_artist",
        "active_commercial_account",
        "price_signal",
        "us_location",
        "very_recent_post",
    }
    assert all(item["evidence"] is not None for item in result["components"])


def test_stale_timestamp_penalizes_but_discovery_time_does_not():
    stale = score_account(
        account(last_activity_at=(NOW - timedelta(hours=73)).isoformat()),
        [signal()],
        now=NOW,
    )
    assert any(item["rule"] == "stale" and item["points"] == -30 for item in stale["components"])

    unknown = score_account(
        account(last_activity_at=None),
        [signal(discovered_at=NOW.isoformat())],
        now=NOW,
    )
    assert not any(item["rule"] in {"stale", "very_recent_post"} for item in unknown["components"])


def test_future_timestamp_is_unknown_not_fresh():
    result = score_account(
        account(last_activity_at=(NOW + timedelta(hours=1)).isoformat()),
        [signal()],
        now=NOW,
    )
    assert not any(item["rule"] in {"stale", "very_recent_post"} for item in result["components"])


def test_generic_books_open_and_studio_are_penalties():
    result = score_account(
        account(account_type="studio", profile_context="Tattoo studio with our artists"),
        [signal(title="Tattoo shop books are open", snippet="Appointments available", matched_phrase="spot opened up")],
        now=NOW,
    )
    rules = {item["rule"]: item["points"] for item in result["components"]}
    assert rules["generic_books_open"] == -15
    assert rules["studio_account"] == -15
    assert "individual_artist" not in rules


def test_unresolved_account_can_never_be_hot_or_warm():
    result = score_account(
        account(status="UNRESOLVED"),
        [signal()],
        now=NOW,
    )
    assert result["score"] >= 80
    assert result["eligible"] is False
    assert result["state"] == "IGNORE"


def test_non_us_or_unknown_location_gets_no_location_points():
    for location in (
        None,
        {"city": "Toronto", "region": "ON", "country": "CA"},
        {"city": "Portland", "region": "OR", "country": None},
    ):
        result = score_account(account(location=location), [signal()], now=NOW)
        assert not any(item["rule"] == "us_location" for item in result["components"])


def test_score_payload_joins_only_account_signal_ids_and_sorts_descending():
    artists = {
        "schema": "empty-chair-hunter-artists-v1",
        "accounts": [
            account(account_id="low", username="low", active_commercial_account=None, signals=[{"id": "sig-low"}]),
            account(account_id="high", username="high", signals=[{"id": "sig-high"}]),
        ],
    }
    signals = {
        "schema": "empty-chair-hunter-signals-v1",
        "signals": [
            signal(id="sig-low", title="Tattoo artist spot opened up", snippet="Tattoo opening", matched_phrase="spot opened up"),
            signal(id="sig-high"),
            signal(id="unrelated", title="Cancellation today $999", snippet="last minute", matched_phrase="had a cancellation"),
        ],
    }
    result = score_payload(artists, signals, now=NOW)
    assert [target["account_id"] for target in result["targets"]] == ["high", "low"]
    assert result["targets"][0]["signal_ids"] == ["sig-high"]
    assert result["account_count"] == 2


def test_invalid_payload_contracts_are_rejected():
    with pytest.raises(ValueError):
        score_payload({"schema": "wrong", "accounts": []}, {"schema": "empty-chair-hunter-signals-v1", "signals": []}, now=NOW)
    with pytest.raises(ValueError):
        score_payload({"schema": "empty-chair-hunter-artists-v1", "accounts": []}, {"schema": "wrong", "signals": []}, now=NOW)


def test_top_20_are_materially_stronger_than_bottom_20():
    targets = []
    for index in range(20):
        targets.append({"score": 90 - (index % 5)})
    for index in range(20):
        targets.append({"score": 25 - (index % 5)})
    separation = ranking_separation(targets)
    assert separation["cohort_size"] == 20
    assert separation["top_average"] > separation["bottom_average"]
    assert separation["gap"] >= 60
