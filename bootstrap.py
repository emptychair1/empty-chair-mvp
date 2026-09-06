"""Empty Chair 2.0 production bootstrap.

Render imports only the headless 2.0 application and focused 2.0 extensions. Legacy 1.x
modules remain in the repository for history/rollback and are never imported in production.
"""
from v2_app import app
import v2_db_namespace  # noqa: F401,E402
import v2_sms  # noqa: F401,E402
import v2_sms_only  # noqa: F401,E402
import v2_timezone  # noqa: F401,E402
import v2_offer_delivery  # noqa: F401,E402
import v2_auth  # noqa: F401,E402
import v2_apple_calendar_web  # noqa: F401,E402
import v2_phone_safe  # noqa: F401,E402
import v2_client_sources  # noqa: F401,E402
import v2_winner_link  # noqa: F401,E402
import v2_crt_ui  # noqa: F401,E402
import v2_entitlement  # noqa: F401,E402
import v2_subscription_billing  # noqa: F401,E402
import v2_settings  # noqa: F401,E402
import v2_artist_payments  # noqa: F401,E402
import v2_billing_autoadopt  # noqa: F401,E402
import v2_paypal_sellers  # noqa: F401,E402
import v2_payment_settings_ui  # noqa: F401,E402
import v2_pwa  # noqa: F401,E402
import v2_native_calendar  # noqa: F401,E402
import v2_native_auth  # noqa: F401,E402
import v2_production_hardening  # noqa: F401,E402
import v2_payment_failure_hardening  # noqa: F401,E402
import v2_final_hardening  # noqa: F401,E402

print("Empty Chair 2.0 bootstrap loaded")
