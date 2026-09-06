from datetime import datetime, timezone

from pain_fit_bucket import age_hours, pain_matches, pain_score


def test_seed_age_can_be_measured_independently_from_pain_gate():
    now = datetime(2026, 9, 6, 20, 0, tzinfo=timezone.utc)
    assert age_hours("2026-09-01T20:00:00+00:00", now) == 120.0


def test_recent_cancellation_still_scores_above_bucket_threshold():
    evidence = [{
        "age_hours": 8,
        "matches": pain_matches("Cancellation tomorrow, I need to fill this spot"),
    }]
    assert pain_score(evidence) >= 50
