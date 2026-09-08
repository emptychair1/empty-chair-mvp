from hunter.broadcast_channel_probe import parse_profile_payload


def payload(channels):
    return {"data": {"user": {"pinned_channels_info": {"channels": channels}}}}


def test_last_minute_openings_is_high_intent():
    result = parse_profile_payload("Artist.Name", payload([
        {
            "thread_id": "123",
            "title": "Last Minute Openings",
            "invite_link": "https://ig.me/j/example",
            "member_count": 321,
        }
    ]))
    assert result.ok is True
    assert result.status == "channels_found"
    assert result.channel_count == 1
    assert result.recovery_channel_count == 1
    assert result.best_intent_score == 55
    channel = result.channels[0]
    assert channel.title == "Last Minute Openings"
    assert channel.member_count == 321
    assert channel.recovery_signal is True
    assert "last minute" in channel.recovery_matches
    assert "openings" in channel.recovery_matches


def test_cancellation_channel_scores_highest():
    result = parse_profile_payload("artist", payload([
        {"thread_id": "9", "title": "Cancellations + Openings"}
    ]))
    assert result.recovery_channel_count == 1
    assert result.best_intent_score == 60


def test_non_recovery_broadcast_channel_is_still_signal():
    result = parse_profile_payload("artist", payload([
        {"thread_id": "8", "title": "Studio Updates"}
    ]))
    assert result.channel_count == 1
    assert result.recovery_channel_count == 0
    assert result.best_intent_score == 15


def test_no_channels_is_clean_success():
    result = parse_profile_payload("artist", {"data": {"user": {"username": "artist"}}})
    assert result.ok is True
    assert result.status == "no_channels"
    assert result.channels == []


def test_missing_user_is_not_false_negative():
    result = parse_profile_payload("artist", {"data": {}})
    assert result.ok is False
    assert result.status == "no_profile_data"


def test_nested_duplicate_channel_is_deduplicated():
    channel = {"thread_id": "42", "title": "Open Spots", "member_count": 77}
    result = parse_profile_payload("artist", {
        "data": {
            "user": {
                "pinned_channels_info": {
                    "channels": [channel],
                    "nested": {"channel": dict(channel)},
                }
            }
        }
    })
    assert result.channel_count == 1
    assert result.channels[0].thread_id == "42"


def test_alternate_broadcast_channel_shape():
    result = parse_profile_payload("artist", {
        "data": {
            "user": {
                "broadcast_channel": {
                    "thread_v2_id": "abc",
                    "channel_name": "Same Day Availability",
                    "subscriber_count": "44",
                    "creator": {"username": "artist"},
                }
            }
        }
    })
    assert result.channel_count == 1
    assert result.recovery_channel_count == 1
    assert result.channels[0].member_count == 44
    assert result.channels[0].creator_username == "artist"
