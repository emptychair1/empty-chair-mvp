"""Silently establish Empty Chair SaaS billing from the founder merchant once.

Artist subscription checkout is always card-only. Square merchant setup never appears in
the artist payment flow.
"""
import uuid
from fastapi import Request
from fastapi.responses import RedirectResponse
import v2_app as core
import v2_artist_payments as artist_payments
import v2_subscription_billing as billing


def _replace_get(path):
    def matches(route):
        methods=getattr(route,"methods",set()) or set()
        return getattr(route,"path",None)==path and "GET" in methods
    return matches


def _new_static_monthly(token):
    """Create Empty Chair's dedicated $97 plan in the connected founder merchant."""
    plan=billing._raw_request(token,"POST","/v2/catalog/object",{
        "idempotency_key":str(uuid.uuid4()),
        "object":{"type":"SUBSCRIPTION_PLAN","id":"#empty-chair-plan","present_at_all_locations":True,
                  "subscription_plan_data":{"name":"Empty Chair","all_items":True}}
    }).get("catalog_object") or {}
    plan_id=plan.get("id")
    if not plan_id:raise RuntimeError("Square did not create Empty Chair billing plan")
    result=billing._raw_request(token,"POST","/v2/catalog/object",{
        "idempotency_key":str(uuid.uuid4()),
        "object":{"type":"SUBSCRIPTION_PLAN_VARIATION","id":"#empty-chair-monthly-97","present_at_all_locations":True,
                  "subscription_plan_variation_data":{"name":"Empty Chair // $97 Monthly","subscription_plan_id":plan_id,
                  "phases":[{"cadence":"MONTHLY","ordinal":0,"pricing":{"type":"STATIC","price":{"amount":9700,"currency":"USD"}}}]}}
    })
    variation=(result.get("catalog_object") or {}).get("id")
    if not variation:raise RuntimeError("Square did not create Empty Chair monthly variation")
    return variation


def _adopt_existing_platform_merchant(artist):
    if billing._account():return True
    acct=artist_payments.square_account(artist["id"]);token=artist_payments.square_token(acct) if acct else ""
    if not (acct and token and acct.get("location_id")):return False
    try:
        # The founder has already explicitly connected this Square merchant. Persist it as
        # Empty Chair's billing merchant, then provision the subscription catalog if the old
        # dashboard plan ID is stale or belongs to a different Square catalog.
        core.run("INSERT INTO platform_billing_account(id,merchant_id,location_id,access_token,refresh_token,token_expires_at,monthly_plan_variation_id,connected_at) VALUES(1,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET merchant_id=excluded.merchant_id,location_id=excluded.location_id,access_token=excluded.access_token,refresh_token=excluded.refresh_token,token_expires_at=excluded.token_expires_at,connected_at=excluded.connected_at",(acct.get("merchant_id"),acct.get("location_id"),token,acct.get("refresh_token"),acct.get("token_expires_at"),None,core.utcnow()))
        try:variation=billing._ensure_static_monthly(token)
        except Exception as old_plan_error:
            print(f"Existing Square plan unavailable; provisioning dedicated plan: {type(old_plan_error).__name__}: {old_plan_error}",flush=True)
            variation=_new_static_monthly(token)
        core.run("UPDATE platform_billing_account SET monthly_plan_variation_id=? WHERE id=1",(variation,))
        core.event("billing.square.adopted",artist["id"],{"merchant_id":acct.get("merchant_id"),"location_id":acct.get("location_id"),"plan_variation_id":variation})
        return True
    except Exception as exc:
        try:core.run("DELETE FROM platform_billing_account WHERE id=1")
        except Exception:pass
        print(f"Platform Square adoption failed: {type(exc).__name__}: {exc}",flush=True);return False

core.app.router.routes[:]=[r for r in core.app.router.routes if not _replace_get("/billing/subscribe/{cadence}")(r) and not _replace_get("/billing/platform/connect")(r)]

@core.app.get("/billing/subscribe/{cadence}")
def subscribe_page(request:Request,cadence:str):
    artist=core.current_artist(request)
    if not artist:return RedirectResponse("/setup")
    if cadence!="monthly":return RedirectResponse("/settings/subscription",303)
    if not billing._account() and not _adopt_existing_platform_merchant(artist):return core.page("Billing unavailable",'<div class="center"><h1>EMPTY CHAIR // CHECK PAYMENT</h1><p>Subscription checkout is temporarily unavailable.</p><a class="button" href="/settings/subscription">BACK</a></div>',chair=True)
    return billing.subscribe_page(request,"monthly")

@core.app.get("/billing/platform/connect")
def platform_connect_hidden(request:Request):
    artist=core.current_artist(request)
    if not artist:return RedirectResponse("/setup")
    if _adopt_existing_platform_merchant(artist):return RedirectResponse("/billing/subscribe/monthly",303)
    return RedirectResponse("/settings/subscription",303)

print("Empty Chair 2.0 billing checkout loaded // self-provisioning founder merchant",flush=True)
