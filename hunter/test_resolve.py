import json
from datetime import datetime, timezone

import httpx
import pytest

from collect import instagram_username
from resolve import (
    Context, Page, PublicFetcher, classify, extract_location, parse_context,
    profile_url, public_url, resolve_signals, timestamp,
)

NOW = datetime(2026, 9, 6, 12, tzinfo=timezone.utc)


def markup(*, title="", bio="", data=None, links=""):
    from html import escape
    script = '<script type="application/ld+json">' + json.dumps(data) + '</script>' if data else ''
    return (f'<html><head><title>{escape(title)}</title>'
            f'<meta name="description" content="{escape(bio, quote=True)}">'
            f'{script}</head><body>{links}</body></html>')


def profile(username="alice", bio="Independent tattoo artist based in Nashville, TN. DM to book.", **kw):
    return markup(title=f"Alice (@{username}) • Instagram", bio=bio, **kw)


def signal(identifier="s1", source_url="https://www.instagram.com/alice/", **kw):
    return {"id": identifier, "source_url": source_url, "username": "untrusted_guess",
            "instagram_url": profile_url("untrusted_guess"), "discovered_at": NOW.isoformat(),
            "source": "bing_html", "query": "tattoo cancellation", **kw}


def run(signals, pages, **fetch_options):
    requests = []

    def respond(request):
        requests.append(str(request.url))
        value = pages.get(str(request.url), 404)
        if isinstance(value, int):
            return httpx.Response(value)
        if isinstance(value, tuple):
            return httpx.Response(value[0], headers=value[1], text=value[2])
        return httpx.Response(200, headers={"content-type": "text/html"}, text=value)

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        fetcher = PublicFetcher(client, url_check=lambda url: True, **fetch_options)
        output = resolve_signals(signals, fetcher, now=NOW)
    return output, requests


@pytest.mark.parametrize("url", [
    "https://instagram.com.evil.test/alice/", "https://evilinstagram.com/alice/",
    "https://instagram.com@evil.test/alice/", "https://alice@instagram.com/alice/",
    "ftp://instagram.com/alice/", "https://instagram.com:8080/alice/",
    "https://instagram.com/p/ABC/", "https://instagram.com/reel/ABC/",
    "https://instagram.com/stories/alice/", "https://instagram.com/accounts/",
    "https://instagram.com/alice/tagged/", "https://instagram.com/a..b/",
    "https://instagram.com/.alice/", "https://instagram.com/alice%2Fbob/",
])
def test_invalid_account_urls(url):
    assert instagram_username(url) == ""


@pytest.mark.parametrize("url", [
    "https://www.instagram.com/ALICE/?igsh=123#bio",
    "https://instagram.com/alice", "https://m.instagram.com/alice/",
])
def test_canonical_username(url):
    assert instagram_username(url) == "alice"


def test_real_profile_resolution_and_location():
    out, requests = run([signal()], {profile_url("alice"): profile()})
    account = out["accounts"][0]
    assert account["username"] == "alice"
    assert account["status"] == "RESOLVED"
    assert account["is_tattoo_artist"] is True
    assert account["account_type"] == "individual"
    assert account["commercial_account"] is True
    assert account["location"]["city"] == "Nashville"
    assert account["location"]["region"] == "TN"
    assert requests == [profile_url("alice")]


def test_discovery_time_is_not_activity_time():
    out, _ = run([signal()], {profile_url("alice"): profile()})
    account = out["accounts"][0]
    assert account["last_activity_at"] is None
    assert account["active_account"] is None
    assert account["active_commercial_account"] is None


def test_post_owner_not_caption_mention():
    url = "https://www.instagram.com/p/ABC/"
    post = markup(title="Alice (@alice) on Instagram", bio="Thanks @bob!", data={
        "@type": "SocialMediaPosting", "datePublished": "2026-09-06T10:00:00Z",
        "author": {"@type": "Person", "url": profile_url("alice")},
    })
    out, _ = run([signal(source_url=url)], {url: post, profile_url("alice"): profile()})
    account = out["accounts"][0]
    assert account["username"] == "alice"
    assert account["active_commercial_account"] is True


def test_caption_only_handle_is_unresolved():
    url = "https://www.instagram.com/p/ABC/"
    out, _ = run([signal(source_url=url)], {url: markup(bio="Tattoo by @bob, opening today")})
    assert out["resolutions"][0]["reason"] == "no_verified_identity"
    assert out["account_count"] == 0


def test_multiple_artist_links_are_not_guessed():
    url = "https://studio.example/artists"
    html = markup(links=f'<a href="{profile_url("alice")}">Alice</a><a href="{profile_url("bob")}">Bob</a>')
    out, requests = run([signal(source_url=url)], {url: html})
    assert out["resolutions"][0]["reason"] == "ambiguous_accounts"
    assert requests == [url]


def test_website_link_followed_by_profile_verification():
    url = "https://alice.example/"
    html = markup(links=f'<a href="{profile_url("alice")}">Instagram</a>')
    out, _ = run([signal(source_url=url)], {url: html, profile_url("alice"): profile()})
    assert out["accounts"][0]["status"] == "RESOLVED"


def test_structured_person_works_when_instagram_unavailable():
    url = "https://alice.example/"
    html = markup(data={"@type": "Person", "name": "Alice",
        "jobTitle": "Tattoo artist", "description": "Email to book",
        "sameAs": profile_url("alice"),
        "address": {"addressLocality": "Athens", "addressRegion": "Georgia", "addressCountry": "US"}})
    out, _ = run([signal(source_url=url)], {url: html, profile_url("alice"): 403})
    account = out["accounts"][0]
    assert account["status"] == "RESOLVED"
    assert account["account_type"] == "individual"
    assert account["location"]["region"] == "GA"


@pytest.mark.parametrize("status", [401, 403, 404, 429, 500])
def test_failures_do_not_promote_search_snippets(status):
    out, _ = run([signal(snippet="I am a tattoo artist, DM to book")], {profile_url("alice"): status})
    assert out["resolutions"][0]["status"] == "UNRESOLVED"
    assert out["account_count"] == 0


def test_login_page_is_not_profile_evidence():
    out, _ = run([signal()], {profile_url("alice"): markup(title="Log in to Instagram")})
    assert out["account_count"] == 0


def test_profile_redirect_to_other_user_is_conflict():
    url = "https://www.instagram.com/p/ABC/"
    out, _ = run([signal(source_url=url)], {
        url: markup(title="Alice (@alice) on Instagram"),
        profile_url("alice"): (302, {"location": profile_url("bob")}, ""),
        profile_url("bob"): profile("bob"),
    })
    assert out["resolutions"][0]["reason"] == "profile_identity_conflict"


def test_one_account_retains_multiple_signals_and_caches_profile():
    first, second = "https://www.instagram.com/p/A/", "https://www.instagram.com/p/B/"
    out, requests = run([signal("one", first), signal("two", second), signal("one", first)], {
        first: markup(title="Alice (@alice) on Instagram"),
        second: markup(title="Alice (@alice) on Instagram"), profile_url("alice"): profile(),
    })
    assert out["account_count"] == 1
    assert out["unique_signal_count"] == 2
    assert len(out["accounts"][0]["signals"]) == 2
    assert requests.count(profile_url("alice")) == 1
    again, _ = run([signal()], {profile_url("alice"): profile()})
    assert out["accounts"][0]["account_id"] == again["accounts"][0]["account_id"]


@pytest.mark.parametrize("bio", ["Tattoo collector", "Tattoo supplies", "Tattoo convention", "Not a tattoo artist"])
def test_nonartist_profiles_rejected(bio):
    out, _ = run([signal()], {profile_url("alice"): profile(bio=bio)})
    assert out["accounts"][0]["status"] == "REJECTED"
    assert out["accounts"][0]["is_tattoo_artist"] is False


def test_studio_not_individual():
    result = classify(Context(text="Tattoo studio. Our artists are accepting appointments."), activity_at=None, now=NOW)
    assert result["account_type"] == "studio"
    assert result["is_tattoo_artist"] is None


def test_resident_artist_not_misclassified_as_employer_studio():
    result = classify(Context(text="Resident tattoo artist at Blue Tattoo Studio. DM to book."), activity_at=None, now=NOW)
    assert result["account_type"] == "individual"


def test_generic_tattoo_word_does_not_prove_artist_or_activity():
    result = classify(Context(text="Tattoo inspiration and art"), activity_at=None, now=NOW)
    assert result["is_tattoo_artist"] is None
    assert result["commercial_account"] is None


@pytest.mark.parametrize("value", [None, "garbage", "2026-09-06", "2026-09-07T00:00:00Z"])
def test_missing_invalid_naive_future_timestamp(value):
    assert timestamp(value, NOW) is None


def test_old_activity_is_not_active():
    result = classify(Context(text="Independent tattoo artist. DM to book."),
                      activity_at=timestamp("2025-01-01T12:00:00Z", NOW), now=NOW)
    assert result["active_commercial_account"] is False


@pytest.mark.parametrize("text,city,region", [
    ("Tattoo artist based in New Orleans, Louisiana", "New Orleans", "LA"),
    ("Alice | Nashville, TN | tattoo artist", "Nashville", "TN"),
    ("Athens, GA", "Athens", "GA"),
])
def test_explicit_us_location(text, city, region):
    result = extract_location(Context(text=text))
    assert (result["city"], result["region"]) == (city, region)


@pytest.mark.parametrize("text", ["Athens", "Guest spot in Nashville, TN", "Tattoo artist", "London", "LA"])
def test_ambiguous_or_travel_location_not_guessed(text):
    assert extract_location(Context(text=text)) is None


def test_international_structured_address_preserved():
    result = extract_location(Context(address={"addressLocality": "London", "addressRegion": "England", "addressCountry": "GB"}))
    assert result["country"] == "GB"


def test_address_without_country_not_assumed_us():
    result = extract_location(Context(address={"addressLocality": "Example", "addressRegion": "CA"}))
    assert result["country"] is None


def test_empty_batch_valid():
    out, requests = run([], {})
    assert out["account_count"] == 0
    assert requests == []


def test_request_budget():
    out, requests = run([signal()], {}, max_requests=0)
    assert out["resolutions"][0]["reason"] == "request_budget_exhausted"
    assert requests == []


@pytest.mark.parametrize("value", [{}, {"id": "s", "source_url": []}, None])
def test_bad_input_rejected(value):
    with pytest.raises(ValueError):
        run([value], {})


def test_non_html_and_oversized_html():
    out, _ = run([signal()], {profile_url("alice"): (200, {"content-type": "application/json"}, "{}")})
    assert out["resolutions"][0]["reason"] == "not_html"
    out, _ = run([signal()], {profile_url("alice"): "x" * 1_000_001})
    assert out["resolutions"][0]["reason"] == "page_too_large"


def test_redirect_destination_validated_before_request():
    requested = []
    def respond(request):
        requested.append(str(request.url))
        return httpx.Response(302, headers={"location": "http://127.0.0.1/secret"})
    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        fetcher = PublicFetcher(client, url_check=lambda url: url == "https://artist.example/")
        assert fetcher.get("https://artist.example/").error == "unsafe_url_or_unresolved_host"
    assert requested == ["https://artist.example/"]


@pytest.mark.parametrize("url", ["file:///etc/passwd", "http://127.0.0.1/", "http://[::1]/", "http://169.254.169.254/", "http://10.0.0.1/", "https://user:pass@example.com/", "https://example.com:8443/"])
def test_private_and_credential_urls_rejected(url):
    assert public_url(url) is False


def test_malformed_jsonld_does_not_crash():
    context = parse_context(Page(profile_url("alice"), html=profile() + '<script type="application/ld+json">{bad}</script>'))
    assert context.identities == {"alice"}


def test_unrelated_body_text_does_not_classify_profile():
    html = markup(title="Alice (@alice) • Instagram", links="Comments: I am a tattoo artist. DM to book.")
    out, _ = run([signal()], {profile_url("alice"): html})
    assert out["accounts"][0]["status"] == "UNRESOLVED"


def test_media_caption_does_not_become_author_bio():
    url = "https://public.example/post"
    html = markup(bio="My tattoo artist is great. DM to book", data={
        "@type": "SocialMediaPosting", "author": {"@type": "Person", "name": "Alice",
        "url": profile_url("alice")}})
    out, _ = run([signal(source_url=url)], {url: html, profile_url("alice"): 403})
    assert out["accounts"][0]["is_tattoo_artist"] is None
    assert out["accounts"][0]["status"] == "UNRESOLVED"


def test_profile_title_conflicts_with_url():
    out, _ = run([signal()], {profile_url("alice"): profile("bob")})
    assert out["account_count"] == 0
    assert out["resolutions"][0]["reason"] == "ambiguous_accounts"


def test_bad_schema_type_is_ignored():
    context = parse_context(Page(profile_url("alice"), html=profile(data={"@type": [{"bad": True}]})))
    assert context.identities == {"alice"}


@pytest.mark.parametrize("bio", ["Tattoo artist. Not currently accepting bookings.", "Retired tattoo artist. DM to book.", "Tattoo artist. My books are closed."])
def test_closed_booking_not_positive_commercial_evidence(bio):
    result = classify(Context(text=bio), activity_at=NOW, now=NOW)
    assert result["commercial_account"] is False
    assert result["active_commercial_account"] is False


def test_cli_writes_valid_json_for_empty_collector_batch(tmp_path):
    import subprocess
    import sys
    from pathlib import Path

    source, output = tmp_path / "signals.json", tmp_path / "artists.json"
    source.write_text(json.dumps({"schema": "empty-chair-hunter-signals-v1", "signals": []}))
    process = subprocess.run([sys.executable, str(Path(__file__).with_name("resolve.py")),
        "--input", str(source), "--out", str(output)], capture_output=True, text=True)
    assert process.returncode == 0, process.stderr
    payload = json.loads(output.read_text())
    assert payload["schema"] == "empty-chair-hunter-artists-v1"
    assert payload["accounts"] == []


def test_cli_rejects_wrong_schema(tmp_path):
    import subprocess
    import sys
    from pathlib import Path

    source = tmp_path / "bad.json"
    source.write_text(json.dumps({"schema": "wrong", "signals": []}))
    process = subprocess.run([sys.executable, str(Path(__file__).with_name("resolve.py")),
        "--input", str(source)], capture_output=True, text=True)
    assert process.returncode != 0
    assert "Expected a Sprint 1" in process.stderr
