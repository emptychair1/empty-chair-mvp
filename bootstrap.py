"""Explicit production bootstrap for Empty Chair.

Render launches this module so additive routes and notification integrations are
always registered before the ASGI app starts serving requests.
"""

import app as core

# Register additive pages/routes first.
import features  # noqa: F401,E402

# Install SMS/email notification overrides after core is fully imported.
import notifications  # noqa: F401,E402

# Replace the public claim endpoint with the atomic implementation after
# notification overrides are installed.
import claim_flow  # noqa: F401,E402

# Register Pilot v1.1 readiness, Autopilot, health, and outcome reporting.
import pilot  # noqa: F401,E402

# Apply Pilot safety rules after Pilot routes are registered. This adds a hard
# customer contact cooldown and preserves shop isolation in Pilot activity data.
import pilot_safety  # noqa: F401,E402

app = core.app

print(
    "Empty Chair bootstrap loaded: "
    f"version={pilot.PILOT_VERSION}, "
    f"sms_live={notifications.SMS_LIVE}, "
    f"email_live={notifications.EMAIL_LIVE}, "
    f"resend_configured={bool(core.RESEND_API_KEY)}, "
    f"contact_cooldown_hours={pilot_safety.CONTACT_COOLDOWN_HOURS}"
)
