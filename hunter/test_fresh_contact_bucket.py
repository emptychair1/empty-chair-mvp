from datetime import date, datetime, timezone

from fresh_contact_bucket import Source, extract_artists, normalize_handle, source_is_fresh


def test_normalize_handle():
    assert normalize_handle("@Tattoo.Artist") == "tattoo.artist"
    assert normalize_handle("@instagram") is None


def test_source_freshness_expires_old_event():
    src = Source("Old", "https://example.com", date(2026, 8, 1), date(2026, 8, 3), "US")
    assert not source_is_fresh(src, date(2026, 9, 6))


def test_source_freshness_accepts_upcoming_event():
    src = Source("Future", "https://example.com", date(2026, 9, 25), date(2026, 9, 27), "US")
    assert source_is_fresh(src, date(2026, 9, 6))


def test_extracts_linked_artist_and_public_contact():
    src = Source("Expo", "https://expo.example/artists", date(2026, 9, 25), date(2026, 9, 27), "Seattle, WA")
    html = '''
    <article>
      <h3>Jane Doe</h3>
      <a href="https://instagram.com/jane.ink">@jane.ink</a>
      <a href="https://janedoe.com/book">Book Jane</a>
      <span>jane@janedoe.com</span>
    </article>
    '''
    rows = extract_artists(html, src, datetime(2026, 9, 6, tzinfo=timezone.utc))
    assert len(rows) == 1
    assert rows[0]["username"] == "jane.ink"
    assert rows[0]["name"] == "Jane Doe"
    assert rows[0]["contact"]["emails"] == ["jane@janedoe.com"]
    assert rows[0]["contact"]["contactability"] == 100


def test_plain_text_handle_still_becomes_contactable_artist():
    src = Source("Expo", "https://expo.example/artists", date(2026, 9, 25), date(2026, 9, 27), "Seattle, WA")
    html = '<div><h3>John Smith</h3><p>Tattoo Artist @johnsmithtattoo</p></div>'
    rows = extract_artists(html, src, datetime(2026, 9, 6, tzinfo=timezone.utc))
    assert len(rows) == 1
    assert rows[0]["contact"]["best_contact_method"] == "public_instagram_profile"
    assert rows[0]["contact"]["contactability"] == 40
