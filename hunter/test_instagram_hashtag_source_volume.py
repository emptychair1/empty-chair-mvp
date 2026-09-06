from datetime import datetime, timezone
from types import SimpleNamespace

import instagram_hashtag_source as source


def test_default_tag_pool_is_broad_but_bounded():
    assert len(source.DEFAULT_TAGS) <= 30
    assert "tattoo" in source.DEFAULT_TAGS
    assert "tattooartist" in source.DEFAULT_TAGS
    assert "atlantatattoo" in source.DEFAULT_TAGS
    assert "tattoocancellation" in source.DEFAULT_TAGS


def test_caption_intent_expands_beyond_cancellation_keyword():
    matches = source.intent_matches("A gap in my schedule opened up — available tomorrow for a tattoo.")
    assert "gap in my schedule" in matches
    assert "available tomorrow" in matches


def test_run_filters_before_resolution_and_dedupes_across_tags(monkeypatch):
    now = datetime(2026, 9, 6, 20, 0, tzinfo=timezone.utc)
    rows_by_tag = {
        "tattoo": [
            {
                "id": "m1",
                "caption": "Cancellation today — last minute tattoo spot available",
                "permalink": "https://www.instagram.com/p/m1/",
                "timestamp": "2026-09-06T19:00:00+0000",
            },
            {
                "id": "noise",
                "caption": "Finished this tattoo yesterday",
                "permalink": "https://www.instagram.com/p/noise/",
                "timestamp": "2026-09-06T18:00:00+0000",
            },
        ],
        "atlantatattoo": [
            {
                "id": "m1",
                "caption": "Cancellation today — last minute tattoo spot available",
                "permalink": "https://www.instagram.com/p/m1/",
                "timestamp": "2026-09-06T19:00:00+0000",
            },
            {
                "id": "old",
                "caption": "Cancellation available tomorrow",
                "permalink": "https://www.instagram.com/p/old/",
                "timestamp": "2026-09-01T19:00:00+0000",
            },
        ],
    }

    monkeypatch.setattr(source, "hashtag_id", lambda client, token, ig_user_id, tag: tag)
    monkeypatch.setattr(
        source,
        "recent_media",
        lambda client, token, ig_user_id, tag_id, limit: rows_by_tag[tag_id],
    )
    resolved = []

    def fake_resolve(permalink):
        resolved.append(permalink)
        return SimpleNamespace(
            username="artist_one",
            status="resolved",
            method="visible_text",
            confidence=0.95,
            reason="test",
        )

    monkeypatch.setattr(source, "resolve", fake_resolve)

    result = source.run(
        token="token",
        ig_user_id="ig",
        tags=("tattoo", "atlantatattoo"),
        limit=50,
        now=now,
    )

    assert result["signal_count"] == 1
    assert result["resolved_count"] == 1
    assert resolved == ["https://www.instagram.com/p/m1/"]
    assert result["signals"][0]["hashtags"] == ["tattoo", "atlantatattoo"]
    assert result["metrics"] == {
        "media_scanned": 4,
        "fresh_media": 3,
        "intent_matches": 2,
        "unique_candidate_posts": 1,
        "duplicate_hits": 1,
        "resolutions_attempted": 1,
        "resolved_count": 1,
        "unresolved_count": 0,
    }


def test_resolution_budget_defers_excess_candidates(monkeypatch):
    now = datetime(2026, 9, 6, 20, 0, tzinfo=timezone.utc)
    rows = [
        {
            "id": f"m{i}",
            "caption": "Cancellation today",
            "permalink": f"https://www.instagram.com/p/m{i}/",
            "timestamp": "2026-09-06T19:00:00+0000",
        }
        for i in range(3)
    ]
    monkeypatch.setattr(source, "hashtag_id", lambda *args: "tattoo")
    monkeypatch.setattr(source, "recent_media", lambda *args: rows)
    monkeypatch.setattr(
        source,
        "resolve",
        lambda permalink: SimpleNamespace(
            username="artist",
            status="resolved",
            method="visible_text",
            confidence=0.95,
            reason="test",
        ),
    )

    result = source.run(
        token="token",
        ig_user_id="ig",
        tags=("tattoo",),
        max_resolutions=1,
        now=now,
    )

    assert result["metrics"]["resolutions_attempted"] == 1
    assert result["signals"][1]["resolution_status"] == "deferred_limit"
    assert result["signals"][2]["resolution_status"] == "deferred_limit"
