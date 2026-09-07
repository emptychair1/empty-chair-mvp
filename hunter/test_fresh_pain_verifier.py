from datetime import datetime, timezone

from bs4 import BeautifulSoup

from fresh_pain_verifier import MAX_AGE_HOURS, age_hours, page_timestamps, pain_matches, strongest_score


def test_cancellation_scores_as_pain():
    matches = pain_matches("Cancellation tomorrow - one last-minute spot available")
    assert matches["disruption"]
    assert matches["urgent_capacity"]
    assert strongest_score(matches, 6.0) >= 85


def test_stale_timestamp_is_not_fresh():
    now = datetime(2026, 9, 7, tzinfo=timezone.utc)
    old = datetime(2026, 9, 3, tzinfo=timezone.utc)
    assert age_hours(old, now) > MAX_AGE_HOURS


def test_html_time_is_detected():
    soup = BeautifulSoup('<html><time datetime="2026-09-06T20:00:00Z">now</time></html>', "lxml")
    rows = page_timestamps(soup, {})
    assert rows
    assert rows[0][1] == "html_time"


def test_generic_books_open_without_this_week_does_not_match_capacity():
    matches = pain_matches("My books are open. Thanks everyone!")
    assert not matches["capacity"]
    assert not matches["urgent_capacity"]
    assert not matches["disruption"]
