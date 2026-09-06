"""Artist-safe Empty Chair SaaS subscription checkout bridge."""
from fastapi import Request
from fastapi.responses import RedirectResponse
import v2_app as core
import v2_artist_payments as artist_payments
import v2_subscription_billing as billing


def _matches(path,method):
    def yes(route):
        methods=getattr(route,"methods",set()) or set()
        return getattr(route,"path",None)==path and method in methods
    return yes


def _adopt_existing_platform_merchant(artist):
    """One-time founder/platform setup; never shown as part of artist checkout."""
    if billing._account():return True
    acct=artist_payments.square_account(artist["id"])
    token=artist_payments.square_token(acct) if acct else ""
    if not (acct and token and acct.get("location_id")):return False
    try:
        core.run("INSERT INTO platform_billing_account(id,merchant_id,location_id,access_token,refresh_token,token_expires_at,monthly_plan_variation_id,connected_at) VALUES(1,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET merchant_id=excluded.merchant_id,location_id=excluded.location_id,access_token=excluded.access_token,refresh_token=excluded.refresh_token,token_expires_at=excluded.token_expires_at,connected_at=excluded.connected_at",(acct.get("merchant_id"),acct.get("location_id"),token,acct.get("refresh_token"),acct.get("token_expires_at"),None,core.utcnow()))
        variation=billing._ensure_static_monthly(token)
        core.run("UPDATE platform_billing_account SET monthly_plan_variation_id=? WHERE id=1",(variation,))
        core.event("billing.square.adopted",artist["id"],{"merchant_id":acct.get("merchant_id"),"location_id":acct.get("location_id"),"plan_variation_id":variation})
        return True
    except Exception as exc:
        try:core.run("DELETE FROM platform_billing_account WHERE id=1")
        except Exception:pass
        print(f"Platform Square adoption failed: {type(exc).__name__}: {exc}",flush=True)
        return False


# Replace only the artist-facing GET routes. The production POST subscription handler remains
# v2_subscription_billing.subscribe_monthly with the real $97 monthly variation.
core.app.router.routes[:]=[
    r for r in core.app.router.routes
    if not _matches("/billing/subscribe/{cadence}","GET")(r)
    and not _matches("/billing/platform/connect","GET")(r)
]


@core.app.get("/billing/subscribe/{cadence}")
def subscribe_page(request:Request,cadence:str):
    artist=core.current_artist(request)
    if not artist:return RedirectResponse("/setup")
    if cadence!="monthly":return RedirectResponse("/settings/subscription",303)
    if not billing._account() and not _adopt_existing_platform_merchant(artist):
        return core.page("Billing unavailable",'<div class="center"><h1>EMPTY CHAIR // CHECK PAYMENT</h1><p>Subscription checkout is temporarily unavailable.</p><a class="button" href="/settings/subscription">BACK</a></div>',chair=True)
    return billing.subscribe_page(request,"monthly")


@core.app.get("/billing/platform/connect")
def platform_connect_hidden(request:Request):
    artist=core.current_artist(request)
    if not artist:return RedirectResponse("/setup")
    if _adopt_existing_platform_merchant(artist):return RedirectResponse("/billing/subscribe/monthly",303)
    return RedirectResponse("/settings/subscription",303)


print("Empty Chair 2.0 billing checkout loaded // production $97 only",flush=True)
