from unittest.mock import patch

import calendar_safety


def test_busy_calendar_prevents_recovery_offer():
    owner = {"id": "user_test"}
    opening = {
        "id": "open_test",
        "shop_id": "shop_test",
        "date": "2026-08-18",
        "start_time": "14:00",
        "end_time": "16:00",
        "shop_timezone": "America/New_York",
    }
    with patch.object(calendar_safety, "_calendar_owner_and_opening", return_value=(owner, opening)), patch(
        "google_integration.calendar_connected", return_value=True
    ), patch("google_integration.calendar_is_available_for_user", return_value=False), patch(
        "calendar_safety.core.connect"
    ) as connect, patch.object(calendar_safety, "_ORIGINAL_START_RECOVERY_CAMPAIGN") as original:
        connection = connect.return_value
        calendar_safety.start_recovery_campaign_calendar_safe("open_test")
        original.assert_not_called()
        connection.commit.assert_called_once()


def test_manual_fallback_starts_recovery_without_calendar():
    owner = {"id": "user_test"}
    opening = {
        "id": "open_test",
        "shop_id": "shop_test",
        "date": "2026-08-18",
        "start_time": "14:00",
        "end_time": "16:00",
        "shop_timezone": "America/New_York",
    }
    with patch.object(calendar_safety, "_calendar_owner_and_opening", return_value=(owner, opening)), patch(
        "google_integration.calendar_connected", return_value=False
    ), patch.object(calendar_safety, "_ORIGINAL_START_RECOVERY_CAMPAIGN", return_value="offer_test") as original:
        result = calendar_safety.start_recovery_campaign_calendar_safe("open_test")
        assert result == "offer_test"
        original.assert_called_once_with("open_test")
