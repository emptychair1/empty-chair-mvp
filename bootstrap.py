"""Explicit production bootstrap for Empty Chair.

Render launches this module so additive routes and notification integrations are
always registered before the ASGI app starts serving requests.
"""

import app as core

# Register additive pages/routes first.
import features  # noqa: F401,E402

# Register M4's values, conversational Meeting, and authored voice routes in the
# production process. Language/voice remain replaceable faculties; M4 owns its
# evidence and values.
import m4_values  # noqa: F401,E402
import m4_meeting  # noqa: F401,E402

# Isolated Gemini Live experiment. This does not replace /meeting; it exists so
# we can rapidly prove or kill Gemini as a realtime voice faculty.
import m4_gemini_lab  # noqa: F401,E402

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
    f"m4_language_configured={bool(m4_meeting.API_KEY)}, "
    f"gemini_lab_configured={bool(m4_gemini_lab.GEMINI_API_KEY)}, "
    f"contact_cooldown_hours={pilot_safety.CONTACT_COOLDOWN_HOURS}"
)
