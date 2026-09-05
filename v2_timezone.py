"""Timezone-safe display formatting for Empty Chair 2.0.

Render runs in UTC. Customer/artist appointment messages must be formatted in the
artist's operating timezone instead of the server timezone.
"""
from __future__ import annotations

import os
from datetime import datetime
from zoneinfo import ZoneInfo

import v2_app as core

DEFAULT_TIMEZONE = os.getenv("EMPTY_CHAIR_TIMEZONE", "America/New_York")

try:
    DISPLAY_TZ = ZoneInfo(DEFAULT_TIMEZONE)
except Exception:
    DISPLAY_TZ = ZoneInfo("America/New_York")


def fmt_when(iso: str) -> str:
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=DISPLAY_TZ)
        else:
            dt = dt.astimezone(DISPLAY_TZ)
        return dt.strftime("%a // %-I:%M %p")
    except Exception:
        return iso


# Existing 2.0 flows call core.fmt_when dynamically, so this corrects artist SMS,
# customer offers, payment copy, confirmation messages, and success pages together.
core.fmt_when = fmt_when
print(f"Empty Chair 2.0 display timezone: {DISPLAY_TZ.key}", flush=True)
