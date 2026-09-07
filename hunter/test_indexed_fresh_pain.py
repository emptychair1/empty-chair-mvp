from datetime import datetime, timezone

from indexed_fresh_pain import age_hours, identity_matches, pain_matches, parse_dt, parse_rss, score


def test_pain_matches_and_score():
    m = pain_matches("Cancellation — appointment just opened up tomorrow")
    assert m["disruption"]
    assert m["urgent_capacity"]
    assert score(m, 3) >= 85


def test_identity_match_by_username_or_name():
    artist = {"username": "inkbyjane", "name": "Jane Doe"}
    assert identity_matches("Fresh opening from @inkbyjane", artist)
    assert identity_matches("Jane Doe tattoo opening", artist)
    assert not identity_matches("Other Artist tattoo opening", artist)


def test_rss_parsing_and_freshness():
    xml = """<rss><channel><item><title>@inkbyjane opening tomorrow</title><link>https://example.com/a</link><description>last-minute spot available</description><pubDate>Sun, 06 Sep 2026 23:00:00 GMT</pubDate></item></channel></rss>"""
    rows = parse_rss(xml)
    assert len(rows) == 1
    dt = parse_dt(rows[0]["published"])
    now = datetime(2026, 9, 7, 1, 0, tzinfo=timezone.utc)
    assert age_hours(dt, now) == 2
