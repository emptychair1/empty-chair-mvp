from datetime import datetime, timezone

import httpx

import resolve

NOW = datetime(2026, 9, 6, 17, tzinfo=timezone.utc)


def media_signal(*, identifier="s1", handle="tattedbykovo", title=None, caption=None, date="August 19, 2026"):
    title = title or "KOVO KA$H || ATL TATTOO ARTIST | I had a cancellation"
    caption = caption or "I had a cancellation, so ill do this piece for a discounted price of $200! FIRST COME FIRST SERVE!"
    return {
        "id": identifier,
        "source": "duckduckgo_html",
        "query": 'site:instagram.com tattoo "had a cancellation"',
        "source_url": "https://www.instagram.com/p/DcN5flDiYbZ/",
        "instagram_url": "https://www.instagram.com/p/DcN5flDiYbZ/",
        "username": "",
        "title": title,
        "snippet": f"12 likes, 0 comments - {handle} on {date}: \"{caption}\"",
        "matched_phrase": "had a cancellation",
        "discovered_at": NOW.isoformat(),
    }


def run(signal, *, source_status=200, profile_status=403):
    pages = {
        signal["source_url"]: source_status,
        resolve.profile_url(resolve._search_owner_metadata(signal)["username"]): profile_status,
    }

    def respond(request):
        value = pages.get(str(request.url), 404)
        if isinstance(value, int):
            if value == 200:
                return httpx.Response(200, headers={"content-type": "text/html"}, text="<title>Log in to Instagram</title>")
            return httpx.Response(value)
        return httpx.Response(200, headers={"content-type": "text/html"}, text=value)

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        fetcher = resolve.PublicFetcher(client, url_check=lambda url: True)
        return resolve.resolve_signals([signal], fetcher, now=NOW)


def test_real_world_media_result_resolves_explicit_artist_when_instagram_returns_login_shell():
    output = run(media_signal())
    assert output["account_count"] == 1
    account = output["accounts"][0]
    assert account["username"] == "tattedbykovo"
    assert account["status"] == "RESOLVED"
    assert account["is_tattoo_artist"] is True
    assert account["account_type"] == "individual"
    assert account["classification_source"] == "search_result_artist_heading"
    assert account["identity_evidence"]["kind"] == "search_result_owner_metadata"
    assert account["last_activity_at"].startswith("2026-08-19T12:00:00")
    assert output["reason_counts"]["artist_evidence"] == 1


def test_customer_post_is_not_promoted_even_with_verified_owner_metadata():
    signal = media_signal(
        handle="mfp_josh",
        title="Josh Haldeman | Tattoo artist had a cancellation today and I was able to get in",
        caption="Tattoo artist had a cancellation today and I was able to get in. I've been wanting this tattoo.",
    )
    output = run(signal)
    account = output["accounts"][0]
    assert account["status"] == "UNRESOLVED"
    assert account["is_tattoo_artist"] is None
    assert output["reason_counts"]["search_context_customer_language"] == 1


def test_studio_heading_does_not_become_individual_artist():
    signal = media_signal(
        handle="edenbodyartstudios",
        title="EDEN • Dallas Tattoo Studio | last minute cancellation",
        caption="Our artist didn't let a last minute cancellation slow the day down.",
        date="August 10, 2026",
    )
    output = run(signal)
    account = output["accounts"][0]
    assert account["account_type"] == "studio"
    assert account["status"] == "UNRESOLVED"


def test_generic_search_snippet_without_owner_date_pattern_is_never_promoted():
    signal = media_signal()
    signal["snippet"] = "I am a tattoo artist. DM me to book."

    def respond(request):
        return httpx.Response(403)

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        fetcher = resolve.PublicFetcher(client, url_check=lambda url: True)
        output = resolve.resolve_signals([signal], fetcher, now=NOW)
    assert output["account_count"] == 0
    assert output["resolutions"][0]["status"] == "UNRESOLVED"


def test_prefilled_collector_hint_must_match_independently_extracted_owner():
    signal = media_signal()
    signal["username"] = "someone_else"

    def respond(request):
        return httpx.Response(403)

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        fetcher = resolve.PublicFetcher(client, url_check=lambda url: True)
        output = resolve.resolve_signals([signal], fetcher, now=NOW)
    assert output["account_count"] == 0
    assert output["resolutions"][0]["reason"] == "search_owner_hint_conflict"


def test_owner_authored_creator_language_can_resolve_without_fake_profile_bio():
    signal = media_signal(
        handle="suavecita.gee",
        title="Gᴇᴇ | I had a cancellation today",
        caption="I had a cancellation today but did some script for my client. Clients tell me they love my work. Text or email me for tattoo inquiries.",
        date="September 6, 2026",
    )
    output = run(signal)
    account = output["accounts"][0]
    assert account["status"] == "RESOLVED"
    assert account["classification_source"] == "search_result_creator_post"
    assert account["classification_evidence"]["tattoo_artist"] == "owner-authored tattoo service post"
    assert account["active_commercial_account"] is True
