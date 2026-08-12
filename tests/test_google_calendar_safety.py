from unittest.mock import patch

import google_integration
import pilot


def test_slot_iso_uses_shop_timezone():
    value = google_integration.slot_iso("2026-08-18", "14:00", "America/New_York")
    assert value.startswith("2026-08-18T14:00:00")
    assert value.endswith("-04:00")


def test_opening_calendar_available_without_connection_returns_none():
    owner = {"id": "user_test", "timezone": "America/New_York"}
    opening = {"date": "2026-08-18", "start_time": "14:00", "end_time": "16:00"}
    with patch("google_integration.calendar_connected", return_value=False):
        assert pilot._opening_calendar_available(owner, opening) is None


def test_opening_calendar_busy_is_rejected():
    owner = {"id": "user_test", "timezone": "America/New_York"}
    opening = {"date": "2026-08-18", "start_time": "14:00", "end_time": "16:00"}
    with patch("google_integration.calendar_connected", return_value=True), patch(
        "google_integration.calendar_is_available_for_user", return_value=False
    ):
        assert pilot._opening_calendar_available(owner, opening) is False
