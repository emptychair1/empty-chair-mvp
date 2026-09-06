from datetime import datetime, timezone

from instagram_hashtag_source import age_hours, intent_matches


def test_age_hours_parses_meta_timestamp():
    now = datetime(2026, 9, 6, 20, 0, tzinfo=timezone.utc)
    assert round(age_hours("2026-09-06T18:00:00+0000", now), 2) == 2.0


def test_intent_matches_detects_opening_language():
    matches = intent_matches("Last minute cancellation — spot available today!")
    assert "cancellation" in matches
    assert "last minute" in matches
    assert "available today" in matches


def test_intent_matches_ignores_generic_tattoo_caption():
    assert intent_matches("Fresh traditional tattoo from this week") == []
