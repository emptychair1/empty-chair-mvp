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


def test_unwraps_bing_encoded_result():
    import base64
    target = "https://www.instagram.com/p/ABC123/"
    encoded = base64.urlsafe_b64encode(target.encode()).decode().rstrip("=")
    assert normalize_result_url(f"https://www.bing.com/ck/a?u=a1{encoded}&ntb=1") == target


def test_like_count_after_instagram_title_is_not_username():
    assert find_instagram_url("", "Josh | tattoo - Instagram 28 likes, 1 comments") == ""


def test_arbitrary_mention_is_not_page_owner():
    assert find_instagram_url("", "Tattoo inspiration thanks to @someoneelse") == ""


def test_direct_instagram_text_link_remains_supported():
    assert find_instagram_url("", "Visit instagram.com/blackbirdtattoo/") == "https://www.instagram.com/blackbirdtattoo/"


def test_malformed_bing_redirect_does_not_crash():
    url = "https://www.bing.com/ck/a?u=a1!"
    assert normalize_result_url(url) == url
