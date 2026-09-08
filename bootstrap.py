"""Empty Chair 2.0 production bootstrap."""
import secrets
import uuid
from fastapi.responses import JSONResponse, RedirectResponse
import v2_app as core
from v2_app import app
import v2_db_namespace
import v2_sms
import v2_sms_only
import v2_timezone
import v2_offer_delivery
import v2_auth
import v2_apple_signin_repair
import v2_apple_calendar_web
import v2_phone_safe
import v2_client_sources
import v2_winner_link
import v2_crt_ui
import v2_entitlement
import v2_subscription_billing
import v2_settings
import v2_founder_ig_reels
import v2_instagram_stories
import v2_founder_reddit
import v2_founder_reddit_oauth
import v2_reddit_devvit_bridge
import v2_founder_reddit_public_discovery
import v2_artist_payments
import v2_billing_autoadopt
import v2_paypal_sellers
import v2_payment_settings_ui
import v2_pwa
import v2_native_calendar
import v2_native_auth
import v2_production_hardening
import v2_payment_failure_hardening
import v2_final_hardening
import v2_paid_finalize_recovery
import v2_native_finalize_bridge
import v2_instagram_growth as ig_growth
import v2_instagram_api_fix
import v2_instagram_growth_attribution
import v2_instagram_content
import v2_instagram_growth_brain
import v2_instagram_growth_report
import v2_instagram_publisher
import v2_instagram_crt_autopilot
import v2_instagram_reels_engine
import v2_instagram_reels_test
import v2_instagram_reels_launch
import v2_instagram_reels_app_screens
import v2_instagram_reels_cleanup_fix
import v2_instagram_webhook_subscription
import v2_hunter_operator
import v2_hunter_operator_transaction_fix
import v2_hunter_operator_phone_auth
import v2_hunter_crt_ui
import v2_hunter_auto_engage
import v2_hunter_auto_engage_cap
import v2_hunter_outreach
import v2_hunter_outreach_primary
import v2_hunter_outreach_runtime_fix
import v2_hunter_dm_variety
import v2_hunter_reply_opportunity
import v2_hunter_instagram_reply_sync
import v2_hunter_instagram_reply_graph_fix
import v2_hunter_instagram_reply_retry_fix
import v2_native_hunter

BUILD_ID = "bootstrap-apple-signin-repair-20260908"

@app.middleware("http")
async def bootstrap_entrypoints(request, call_next):
    path=request.url.path.rstrip("/") or "/"
    if path=="/__ec_build": return JSONResponse({"build":BUILD_ID,"instagram_bio":True})
    if path=="/ig":
        token=secrets.token_urlsafe(18)
        try:
            lead_id=str(uuid.uuid4()); created=ig_growth.now()
            core.run("INSERT INTO growth_instagram_leads(id,ig_user_id,username,comment_id,media_id,keyword,token,status,created_at,clicked_at) VALUES(?,?,?,?,?,?,?,?,?,?)",(lead_id,"organic","",f"organic:{uuid.uuid4()}","","bio",token,"CLICKED",created,created))
            ig_growth.log(lead_id,"instagram.organic_clicked",{"source":"bio"})
        except Exception as exc: print(f"IG bio attribution write failed: {exc}",flush=True)
        response=RedirectResponse("/",status_code=303); response.set_cookie("ec_growth",token,max_age=60*60*24*14,httponly=True,secure=core.BASE_URL.startswith("https://"),samesite="lax"); return response
    return await call_next(request)

print(f"Empty Chair 2.0 bootstrap loaded // {BUILD_ID}")