"""Empty Chair 2.0 production bootstrap.

Render imports only the headless 2.0 application and focused 2.0 extensions. Legacy 1.x
modules remain in the repository for history/rollback and are never imported in production.
"""
import secrets
import uuid

from fastapi.responses import JSONResponse, RedirectResponse

import v2_app as core
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
import v2_paid_finalize_recovery  # noqa: F401,E402
import v2_native_finalize_bridge  # noqa: F401,E402
import v2_instagram_growth as ig_growth  # noqa: F401,E402
import v2_instagram_api_fix  # noqa: F401,E402
import v2_instagram_growth_attribution  # noqa: F401,E402
import v2_instagram_content  # noqa: F401,E402
import v2_instagram_growth_brain  # noqa: F401,E402
import v2_instagram_growth_report  # noqa: F401,E402
import v2_instagram_publisher  # noqa: F401,E402
import v2_instagram_crt_autopilot  # noqa: F401,E402
import v2_instagram_webhook_subscription  # noqa: F401,E402
import v2_hunter_operator  # noqa: F401,E402
import v2_hunter_operator_transaction_fix  # noqa: F401,E402
import v2_hunter_operator_phone_auth  # noqa: F401,E402
import v2_hunter_crt_ui  # noqa: F401,E402
import v2_hunter_auto_engage  # noqa: F401,E402
import v2_hunter_auto_engage_cap  # noqa: F401,E402
import v2_hunter_outreach  # noqa: F401,E402
import v2_hunter_outreach_primary  # noqa: F401,E402
import v2_hunter_outreach_runtime_fix  # noqa: F401,E402
import v2_hunter_dm_variety  # noqa: F401,E402
import v2_hunter_reply_opportunity  # noqa: F401,E402
import v2_hunter_instagram_reply_sync  # noqa: F401,E402
import v2_hunter_instagram_reply_graph_fix  # noqa: F401,E402
import v2_hunter_instagram_reply_retry_fix  # noqa: F401,E402
import v2_native_hunter  # noqa: F401,E402

BUILD_ID = "bootstrap-hunter-reply-retry-fix-20260907"


@app.middleware("http")
async def bootstrap_entrypoints(request, call_next):
    path = request.url.path.rstrip("/") or "/"
    if path == "/__ec_build":
        return JSONResponse({"build": BUILD_ID, "instagram_bio": True})
    if path == "/ig":
        token = secrets.token_urlsafe(18)
        try:
            lead_id = str(uuid.uuid4())
            created = ig_growth.now()
            core.run(
                "INSERT INTO growth_instagram_leads(id,ig_user_id,username,comment_id,media_id,keyword,token,status,created_at,clicked_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
                (lead_id, "organic", "", f"organic:{uuid.uuid4()}", "", "bio", token, "CLICKED", created, created),
            )
            ig_growth.log(lead_id, "instagram.organic_clicked", {"source": "bio"})
        except Exception as exc:
            print(f"IG bio attribution write failed: {exc}", flush=True)
        response = RedirectResponse("/", status_code=303)
        response.set_cookie(
            "ec_growth",
            token,
            max_age=60 * 60 * 24 * 14,
            httponly=True,
            secure=core.BASE_URL.startswith("https://"),
            samesite="lax",
        )
        return response
    return await call_next(request)


print(f"Empty Chair 2.0 bootstrap loaded // {BUILD_ID}")
