from datetime import datetime, timezone

from integrate_instagram import integrate


def test_resolved_meta_signal_becomes_standard_signal_and_artist():
    signals = {"schema": "empty-chair-hunter-signals-v1", "generated_at": "x", "count": 0, "signals": []}
    artists = {
        "schema": "empty-chair-hunter-artists-v1",
        "generated_at": "x",
        "input_count": 0,
        "unique_signal_count": 0,
        "account_count": 0,
        "status_counts": {},
        "reason_counts": {},
        "request_count": 0,
        "accounts": [],
        "resolutions": [],
    }
    meta = {
        "schema": "empty-chair-hunter-instagram-meta-v1",
        "generated_at": "2026-09-06T19:30:00+00:00",
        "signals": [{
            "media_id": "123",
            "hashtag": "tattooopenings",
            "caption": "Had a cancellation. Available today for tattoos.",
            "timestamp": "2026-09-06T19:00:00+0000",
            "permalink": "https://www.instagram.com/p/example/",
            "intent_matches": ["cancellation", "available today"],
            "username": "artist_example",
            "resolution_status": "resolved",
            "resolution_method": "ocr",
            "resolution_confidence": 0.91,
        }],
    }
    merged_signals, merged_artists = integrate(
        signals, artists, meta, now=datetime(2026, 9, 6, 19, 31, tzinfo=timezone.utc)
    )
    assert merged_signals["count"] == 1
    assert merged_signals["signals"][0]["source"] == "instagram_meta_hashtag"
    assert merged_signals["signals"][0]["username"] == "artist_example"
    assert merged_artists["account_count"] == 1
    account = merged_artists["accounts"][0]
    assert account["status"] == "RESOLVED"
    assert account["is_tattoo_artist"] is True
    assert account["active_commercial_account"] is True
    assert account["last_activity_at"] == "2026-09-06T19:00:00+0000"


def test_unresolved_or_low_confidence_meta_signal_fails_closed():
    signals = {"schema": "empty-chair-hunter-signals-v1", "signals": []}
    artists = {"schema": "empty-chair-hunter-artists-v1", "accounts": []}
    meta = {
        "schema": "empty-chair-hunter-instagram-meta-v1",
        "signals": [{
            "media_id": "1",
            "permalink": "https://www.instagram.com/p/x/",
            "timestamp": "2026-09-06T19:00:00+0000",
            "intent_matches": ["cancellation"],
            "username": "maybe_artist",
            "resolution_status": "resolved",
            "resolution_confidence": 0.4,
        }],
    }
    merged_signals, merged_artists = integrate(signals, artists, meta)
    assert merged_signals["count"] == 0
    assert merged_artists["account_count"] == 0
