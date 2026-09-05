"""Empty Chair 2.0 production bootstrap.

Render imports only the headless 2.0 application, isolated 2.0 database namespace,
resilient SMS transport, SMS-only communications, timezone-safe appointment formatting,
delivery-aware recovery, social auth, safe phone signup boundary, multi-source client
import, test payment support, durable winner links, subtle CRT styling, rare-use settings,
and phone/PWA surface. Legacy 1.x modules remain in the repository for history/rollback
and are never imported in production.
"""
from v2_app import app
import v2_db_namespace  # noqa: F401,E402
import v2_sms  # noqa: F401,E402
import v2_sms_only  # noqa: F401,E402
import v2_timezone  # noqa: F401,E402
import v2_offer_delivery  # noqa: F401,E402
import v2_auth  # noqa: F401,E402
import v2_phone_safe  # noqa: F401,E402
import v2_client_sources  # noqa: F401,E402
import v2_test_payment  # noqa: F401,E402
import v2_winner_link  # noqa: F401,E402
import v2_crt_ui  # noqa: F401,E402
import v2_settings  # noqa: F401,E402
import v2_pwa  # noqa: F401,E402

print("Empty Chair 2.0 bootstrap loaded")
