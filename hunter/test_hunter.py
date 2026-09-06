from collect import (
    detect_phrase,
    find_instagram_url,
    instagram_username,
    normalize_result_url,
    relevant_text,
)


def test_detects_real_cancellation_signal():
    assert detect_phrase("Tattoo artist here - just had a cancellation tomorrow") == "had a cancellation"


def test_rejects_irrelevant_cancellation_context():
    assert detect_phrase("Event cancellation notice for convention vendors") == ""


def test_requires_tattoo_context():
    ok, phrase = relevant_text("Tattoo artist had a cancellation tomorrow, flash available")
    assert ok is True
    assert phrase == "had a cancellation"


def test_rejects_non_tattoo_cancellation():
    ok, _ = relevant_text("Restaurant had a cancellation tomorrow")
    assert ok is False


def test_extracts_profile_username():
    assert instagram_username("https://www.instagram.com/blackbirdtattoo/") == "blackbirdtattoo"


def test_does_not_invent_username_from_media_url():
    assert instagram_username("https://www.instagram.com/p/ABC123/") == ""


def test_unwraps_duckduckgo_redirect():
    wrapped = "https://duckduckgo.com/l/?uddg=https%3A%2F%2Fwww.instagram.com%2Ffoo%2F"
    assert normalize_result_url(wrapped) == "https://www.instagram.com/foo/"


def test_resolves_instagram_link_from_public_artist_page():
    html = '<html><a href="https://www.instagram.com/blackbirdtattoo/">Instagram</a></html>'
    assert find_instagram_url(html) == "https://www.instagram.com/blackbirdtattoo/"


def test_resolves_instagram_handle_from_public_text():
    assert find_instagram_url("", "Follow on Instagram @blackbirdtattoo") == "https://www.instagram.com/blackbirdtattoo/"
