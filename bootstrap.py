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

# Add deployed data-gift evidence to every M4 session without claiming anything
# broader than this application's endpoint can verify. Both /meeting and the Gemini
# lab call m4_meeting._session_instructions at runtime, so they receive the same facts.
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
# Transcript analysis owns the prospect behavior contract; keep it separate from
# realtime audio transport so behavior can iterate without destabilizing playback.
import m4_prospect_behavior  # noqa: F401,E402
import m4_prospect_transcript  # noqa: F401,E402
# Durable event-level observability distinguishes browser/network, Gemini, transport,
# playback, transcription assembly, and persistence failures on one timeline.
import m4_prospect_events  # noqa: F401,E402
# Protect partial transcription before normal turn finalization. This must load
# after the canonical transcript module so recovery reads can include checkpoints.
import m4_prospect_checkpoint  # noqa: F401,E402
import m4_gemini_smooth  # noqa: F401,E402
import m4_prospect_meeting  # noqa: F401,E402

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
