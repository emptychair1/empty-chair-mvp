"""Explicit production bootstrap for Empty Chair.

Render launches this module so additive routes and notification integrations are
always registered before the ASGI app starts serving requests.
"""

from fastapi import Request
from fastapi.responses import HTMLResponse

import app as core

# Register additive pages/routes first.
import features  # noqa: F401,E402

# Install SMS/email notification overrides after core is fully imported.
import notifications  # noqa: F401,E402
import delivery_safety  # noqa: F401,E402
import stripe_deposits  # noqa: F401,E402

# Register Google authentication and the optional Calendar double-booking safety layer.
import google_integration  # noqa: F401,E402

# Guard every recovery campaign with Google Calendar free/busy when connected.
import calendar_safety  # noqa: F401,E402

# Replace the public claim endpoint with the atomic implementation after
# notification overrides are installed.
import claim_flow  # noqa: F401,E402
import booking_confirmation  # noqa: F401,E402
import booking_details  # noqa: F401,E402
import pilot_operations  # noqa: F401,E402

# Register Pilot v1.1 data structures and core Autopilot helpers.
import pilot  # noqa: F401,E402

# Apply Pilot safety rules before the canonical Fill Chairs routes are registered.
# This preserves the hard customer-contact cooldown and shop isolation.
import pilot_safety  # noqa: F401,E402

# Register the canonical Fill Chairs GET/POST flow. Page loads are database-only,
# while Calendar checks and offer delivery run after START FILLING redirects.
import fill_chairs_flow  # noqa: F401,E402

# Optional isolated live-demo account. Disabled unless explicitly enabled.
import demo_mode  # noqa: F401,E402

# Verify one-time paid activation tokens issued by the standalone sales site.
import paid_activation  # noqa: F401,E402

# Register the private platform-owner control room.
import admin_dashboard  # noqa: F401,E402

# Replace the legacy artist roster page with forward-looking utilization cards.
import artist_metrics  # noqa: F401,E402

# Register the guided first-run setup flow before the dashboard override.
import onboarding  # noqa: F401,E402

# Replace the legacy dashboard with the utilization-first owner view.
import dashboard_metrics  # noqa: F401,E402

# Register the safe, read-only M4 intelligence page.
import m4_dashboard  # noqa: F401,E402

# The Meeting is deliberately non-critical. A Meeting-specific configuration or
# provider failure must never prevent the Empty Chair core app from starting.
meeting_v2 = None
meeting_import_error = None
try:
    import meeting_v2 as _meeting_v2  # noqa: F401,E402
    meeting_v2 = _meeting_v2
except Exception as meeting_exc:  # pragma: no cover - production safety guard
    meeting_import_error = repr(meeting_exc)
    print(f"Meeting v2 disabled: {meeting_exc}")

# Always expose the public Meeting route. If the isolated subsystem cannot import,
# show the exact failure instead of returning a misleading 404.
@core.app.get("/meet-m4", response_class=HTMLResponse)
def meet_m4_bootstrap(request: Request):
    if meeting_v2 is not None:
        return meeting_v2.meeting_v2_page(request)
    return HTMLResponse(
        f"<html><body style='font-family:system-ui;padding:32px'><h1>The Meeting is unavailable</h1><pre>{meeting_import_error}</pre></body></html>",
        status_code=503,
        headers={"Cache-Control": "no-store"},
    )

# Add a safe Settings-page Twilio delivery tester.
import settings_sms_test  # noqa: F401,E402

# Continuously expires stale offers and advances active campaigns even when
# nobody has the dashboard open.
import pilot_worker  # noqa: F401,E402

app = core.app

print(
    "Empty Chair bootstrap loaded: "
    f"version={pilot.PILOT_VERSION}, "
    f"sms_live={notifications.SMS_LIVE}, "
    f"email_live={notifications.EMAIL_LIVE}, "
    f"resend_configured={bool(core.RESEND_API_KEY)}, "
    f"google_configured={bool(google_integration.GOOGLE_CLIENT_ID)}, "
    f"stripe_configured={stripe_deposits.configured()}, "
    f"contact_cooldown_hours={pilot_safety.CONTACT_COOLDOWN_HOURS}"
)
