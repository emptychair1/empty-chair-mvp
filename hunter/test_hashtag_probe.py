from datetime import datetime, timezone

from hashtag_probe import HASHTAGS, PLATFORMS, publication_time, queries

NOW = datetime(2026, 9, 6, 18, 0, tzinfo=timezone.utc)


def test_hashtag_probe_covers_instagram_and_tiktok():
    assert {"instagram_hashtag", "tiktok_hashtag"} <= set(PLATFORMS)


def test_tattooopenings_is_primary_benchmark_tag():
    assert "tattooopenings" in HASHTAGS


def test_query_matrix_contains_each_tag_and_platform():
    matrix = queries()
    platforms = {platform for platform, _, _ in matrix}
    assert platforms == set(PLATFORMS)
    for tag in HASHTAGS:
        assert any(row_tag == tag for _, row_tag, _ in matrix)


def test_hashtag_queries_use_site_scoped_public_surfaces():
    matrix = queries()
    assert any("site:instagram.com" in query and "#tattooopenings" in query for _, _, query in matrix)
    assert any("site:tiktok.com" in query and "#tattooopenings" in query for _, _, query in matrix)


def test_publication_time_handles_relative_age():
    assert publication_time("2 hours ago", NOW).isoformat() == "2026-09-06T16:00:00+00:00"
