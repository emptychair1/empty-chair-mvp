from collect import detect_phrase, instagram_username, normalize_result_url, relevant


def test_detects_real_cancellation_signal():
    assert detect_phrase("Tattoo artist here - just had a cancellation tomorrow") == "had a cancellation"


def test_rejects_irrelevant_cancellation_context():
    assert detect_phrase("Event cancellation notice for convention vendors") == ""


def test_requires_tattoo_and_instagram_context():
    ok, phrase = relevant(
        "Tattoo artist had a cancellation tomorrow, flash available",
        "https://www.instagram.com/example/",
    )
    assert ok is True
    assert phrase == "had a cancellation"


def test_rejects_non_instagram_result():
    ok, _ = relevant(
        "Tattoo artist had a cancellation tomorrow",
        "https://example.com/post",
    )
    assert ok is False


def test_extracts_profile_username():
    assert instagram_username("https://www.instagram.com/blackbirdtattoo/") == "blackbirdtattoo"


def test_does_not_invent_username_from_media_url():
    assert instagram_username("https://www.instagram.com/p/ABC123/") == ""


def test_unwraps_duckduckgo_redirect():
    wrapped = "https://duckduckgo.com/l/?uddg=https%3A%2F%2Fwww.instagram.com%2Ffoo%2F"
    assert normalize_result_url(wrapped) == "https://www.instagram.com/foo/"
