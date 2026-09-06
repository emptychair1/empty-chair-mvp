from datetime import datetime, timedelta, timezone

from config import INTENT_PHRASES, SEARCH_QUERIES
from score import score_account, score_payload

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
        "last_activity_at": NOW.isoformat(),
        "classification_evidence": {"tattoo_artist": "tattoo artist"},
        "profile_context": "Independent tattoo artist. DM me to book.",
        "location": None,
        "signals": [{"id": "sig-1"}],
    }
    base.update(overrides)
    return base


def signal(text, phrase, **overrides):
    base = {
        "id": "sig-1",
        "title": f"Tattoo artist {text}",
        "snippet": text,
        "matched_phrase": phrase,
    }
    base.update(overrides)
    return base


def test_discovery_net_includes_real_world_schedule_language():
    expected = {
        "someone canceled",
        "appointment fell through",
        "client rescheduled",
        "had a no show",
        "slot opened up",
        "free spot",
        "available today",
        "same day availability",
        "need to fill this spot",
        "who wants this slot",
        "gap in my schedule",
        "walk-in availability",
    }
    assert expected.issubset(set(INTENT_PHRASES))
    for phrase in expected:
        assert f'site:instagram.com tattoo "{phrase}"' in SEARCH_QUERIES
        assert f'tattoo artist Instagram "{phrase}"' in SEARCH_QUERIES


def test_known_stale_target_can_never_be_actionable_even_with_strong_copy():
    result = score_account(
        account(last_activity_at=(NOW - timedelta(days=365)).isoformat()),
        [signal("had a cancellation today, full day $500", "had a cancellation")],
        now=NOW,
    )
    assert result["freshness"] == "stale"
    assert result["eligible"] is False
    assert result["state"] == "IGNORE"
    assert result["eligibility_reason"] == "stale_intent"


def test_recent_no_show_is_treated_as_strong_schedule_disruption():
    result = score_account(
        account(last_activity_at=(NOW - timedelta(hours=2)).isoformat()),
        [signal("had a no-show today, DM me", "had a no-show")],
        now=NOW,
    )
    rules = {item["rule"] for item in result["components"]}
    assert "schedule_disruption" in rules
    assert "urgent" in rules
    assert "very_recent_post" in rules
    assert result["state"] == "HOT"


def test_recent_available_today_is_actionable_without_claiming_cancellation():
    result = score_account(
        account(last_activity_at=(NOW - timedelta(hours=3)).isoformat()),
        [signal("available today for a tattoo appointment", "available today")],
        now=NOW,
    )
    rules = {item["rule"] for item in result["components"]}
    assert "fill_intent" in rules
    assert "explicit_cancellation" not in rules
    assert result["score"] >= 60
    assert result["state"] in {"WARM", "HOT"}


def test_generic_books_open_without_specific_fill_signal_is_not_actionable():
    result = score_account(
        account(last_activity_at=(NOW - timedelta(hours=2)).isoformat()),
        [{"id": "sig-1", "title": "Tattoo artist books are open", "snippet": "Appointments available", "matched_phrase": ""}],
        now=NOW,
    )
    assert result["eligible"] is False
    assert result["state"] == "IGNORE"
    assert result["eligibility_reason"] == "no_specific_fill_intent"


def test_actionable_targets_sort_before_high_scoring_stale_history():
    artists = {
        "schema": "empty-chair-hunter-artists-v1",
        "accounts": [
            account(account_id="stale", username="stale", last_activity_at=(NOW - timedelta(days=800)).isoformat(), signals=[{"id": "stale-sig"}]),
            account(account_id="recent", username="recent", last_activity_at=(NOW - timedelta(hours=2)).isoformat(), signals=[{"id": "recent-sig"}]),
        ],
    }
    signals = {
        "schema": "empty-chair-hunter-signals-v1",
        "signals": [
            signal("had a cancellation today, full day $900", "had a cancellation", id="stale-sig"),
            signal("available today", "available today", id="recent-sig"),
        ],
    }
    result = score_payload(artists, signals, now=NOW)
    assert result["targets"][0]["account_id"] == "recent"
    assert result["targets"][0]["state"] in {"WARM", "HOT"}
    assert result["targets"][1]["account_id"] == "stale"
    assert result["targets"][1]["state"] == "IGNORE"
    assert result["calibration"]["freshness_counts"]["stale"] == 1
