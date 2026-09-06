from instagram_visual_resolver import candidate_usernames, choose_username, validate_permalink


def test_validate_permalink_accepts_public_post_and_reel():
    assert validate_permalink("https://www.instagram.com/p/ABC123/").endswith("/p/ABC123/")
    assert validate_permalink("https://www.instagram.com/reel/ABC123/").endswith("/reel/ABC123/")


def test_validate_permalink_rejects_non_instagram():
    try:
        validate_permalink("https://example.com/p/ABC123/")
    except ValueError:
        pass
    else:
        raise AssertionError("expected ValueError")


def test_choose_username_prefers_early_standalone_handle():
    text = "dreamcatcher_clothingandart\nFollow\nPhoto by someone\n"
    username, confidence = choose_username(text)
    assert username == "dreamcatcher_clothingandart"
    assert confidence >= 0.9


def test_choose_username_fails_closed_on_ambiguous_text():
    text = "Photo by alpha.art with beta.tattoo\nFollow"
    username, confidence = choose_username(text)
    assert username is None
    assert confidence == 0.0


def test_candidate_usernames_filters_reserved_words():
    values = candidate_usernames("Instagram Follow @real.artist")
    assert "real.artist" in values
    assert "instagram" not in values
    assert "follow" not in values
