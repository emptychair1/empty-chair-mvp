"""Explicit production bootstrap for Empty Chair.

Render launches this module so additive routes and notification integrations are
always registered before the ASGI app starts serving requests.
"""

import json

import app as core

# Register additive pages/routes first.
import features  # noqa: F401,E402

# Register M4's values, conversational Meeting, and authored voice routes in the
# production process. Language/voice remain replaceable faculties; M4 owns its
# evidence and values.
import m4_values  # noqa: F401,E402
import m4_meeting  # noqa: F401,E402

# Privacy-first customer-data gift. Uploaded CSV bytes are transformed in request
# memory and returned directly; this module does not persist raw, parsed, or output
# customer data or write it into M4 relationship memory.
import m4_data_gift  # noqa: F401,E402

_base_session_instructions = m4_meeting._session_instructions


def _session_instructions_with_data_gift(user):
    instructions = _base_session_instructions(user)
    verified = {
        "enrichment_available": True,
        "accepted_format": "csv",
        "max_bytes": m4_data_gift.MAX_BYTES,
        "max_rows": m4_data_gift.MAX_ROWS,
        "processing": "request_memory_only",
        "raw_data_persisted_by_endpoint": False,
        "parsed_data_persisted_by_endpoint": False,
        "result_persisted_by_endpoint": False,
        "written_to_m4_relationship_memory": False,
        "response_cache": "no-store",
        "returned_as_owner_download": True,
        "verified_scope": "Empty Chair application endpoint behavior",
        "not_yet_verified": [
            "hosting infrastructure transient retention",
            "network/provider logging outside this endpoint",
            "formal deletion attestation",
            "provider-wide non-training guarantees",
        ],
        "speech_rule": (
            "You may truthfully say this Empty Chair endpoint does not write the uploaded, "
            "parsed, or enriched customer data to its database, filesystem, or M4 memory and "
            "returns the result directly with no-store caching. Do not broaden that into 'not a "
            "shred is retained anywhere' or a provider-wide non-training/deletion promise until "
            "the not_yet_verified items are independently proven."
        ),
    }
    return instructions + "\n\nVERIFIED DATA GIFT CAPABILITIES\n" + json.dumps(verified)


m4_meeting._session_instructions = _session_instructions_with_data_gift

# Gemini Live fallback and isolated prospect meeting stack.
import m4_gemini_lab  # noqa: F401,E402
import m4_prospect_behavior  # noqa: F401,E402
import m4_prospect_transcript  # noqa: F401,E402
import m4_prospect_events  # noqa: F401,E402
import m4_prospect_checkpoint  # noqa: F401,E402
# Deterministic behavioral controller: explicit prospect corrections become durable
# meeting state rather than prompt-only suggestions.
import m4_behavior_state  # noqa: F401,E402
import m4_gemini_smooth  # noqa: F401,E402
# Correct generation ownership after barge-in without destabilizing the underlying
# audio/transcript page. Must load after m4_gemini_smooth so it can replace that route.
import m4_gemini_transport_patch  # noqa: F401,E402
import m4_prospect_meeting  # noqa: F401,E402

# Install SMS/email notification overrides after core is fully imported.
import notifications  # noqa: F401,E402
# Finished M4 prospect meetings export transcript + flight-recorder diagnostics to
# the signed-in owner's own email, enabling connected-assistant analysis without
# public transcript endpoints or manual copy/paste.
import m4_analysis_email  # noqa: F401,E402
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
import pilot_safety  # noqa: F401,E402

# Register the canonical Fill Chairs GET/POST flow.
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
    f"data_gift_registered=True, "
    f"m4_event_recorder_registered=True, "
    f"m4_analysis_email_registered=True, "
    f"m4_behavior_controller_registered=True, "
    f"m4_transport_patch_registered=True, "
    f"contact_cooldown_hours={pilot_safety.CONTACT_COOLDOWN_HOURS}"
)
