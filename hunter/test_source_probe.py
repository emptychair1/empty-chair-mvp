from datetime import datetime, timezone

from source_probe import HIGH_INTENT, SOURCE_FAMILIES, publication_time, queries

NOW = datetime(2026, 9, 6, 18, 0, tzinfo=timezone.utc)


def test_probe_covers_requested_public_sources():
    assert {"instagram", "tiktok", "facebook", "x", "artist_web", "booking_web", "general_web"} <= set(SOURCE_FAMILIES)


def test_x_probe_checks_x_and_legacy_twitter_domains():
    templates = SOURCE_FAMILIES["x"]
    assert any("site:x.com" in template for template in templates)
    assert any("site:twitter.com" in template for template in templates)


def test_query_matrix_contains_each_family_and_high_intent_phrase():
    matrix = queries()
    families = {family for family, _ in matrix}
    assert families == set(SOURCE_FAMILIES)
    for phrase in HIGH_INTENT:
        assert any(phrase in query for _, query in matrix)


def test_publication_time_understands_relative_freshness():
    assert publication_time("posted 2 hours ago", NOW).isoformat() == "2026-09-06T16:00:00+00:00"
    assert publication_time("yesterday tattoo cancellation", NOW).isoformat() == "2026-09-05T18:00:00+00:00"


def test_publication_time_understands_absolute_dates():
    assert publication_time("Sep 6, 2026 — tattoo artist", NOW).date().isoformat() == "2026-09-06"
    assert publication_time("2026-09-05 tattoo", NOW).date().isoformat() == "2026-09-05"


def test_unknown_date_stays_unknown():
    assert publication_time("tattoo artist had a cancellation", NOW) is None
