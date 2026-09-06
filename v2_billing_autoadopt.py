"""Silently bind Empty Chair SaaS billing to its already-connected Square merchant.

Artists paying Empty Chair must never be asked to sign in to Square. The artist-facing
subscription flow is card checkout only. Platform merchant setup is an internal concern.
"""
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


def _adopt_existing_platform_merchant(artist):
    """One-time silent setup using the already-connected Empty Chair Square merchant.

    We only adopt an account that can read the known Empty Chair subscription plan, so an
    arbitrary artist's Square connection cannot become the SaaS billing destination.
    """
    if billing._account():
        return True
    acct=artist_payments.square_account(artist["id"])
    token=artist_payments.square_token(acct) if acct else ""
    if not (acct and token and acct.get("location_id")):
        return False
    try:
        billing._raw_request(token,"GET",f"/v2/catalog/object/{billing.PARENT_PLAN_ID}")
        core.run(
            "INSERT INTO platform_billing_account(id,merchant_id,location_id,access_token,refresh_token,token_expires_at,monthly_plan_variation_id,connected_at) VALUES(1,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET merchant_id=excluded.merchant_id,location_id=excluded.location_id,access_token=excluded.access_token,refresh_token=excluded.refresh_token,token_expires_at=excluded.token_expires_at,connected_at=excluded.connected_at",
            (
                acct.get("merchant_id"),acct.get("location_id"),token,acct.get("refresh_token"),
                acct.get("token_expires_at"),None,core.utcnow(),
            ),
        )
        variation=billing._ensure_static_monthly(token)
        core.run("UPDATE platform_billing_account SET monthly_plan_variation_id=? WHERE id=1",(variation,))
        core.event("billing.square.adopted",artist["id"],{
            "merchant_id":acct.get("merchant_id"),
            "location_id":acct.get("location_id"),
            "plan_variation_id":variation,
        })
        return True
    except Exception as exc:
        try:core.run("DELETE FROM platform_billing_account WHERE id=1")
        except Exception:pass
        print(f"Platform Square adoption failed: {type(exc).__name__}: {exc}",flush=True)
        return False


# Replace the artist-facing subscribe GET so merchant setup can only happen silently.
core.app.router.routes[:]=[
    r for r in core.app.router.routes
    if not _replace_get("/billing/subscribe/{cadence}")(r)
    and not _replace_get("/billing/platform/connect")(r)
]


@core.app.get("/billing/subscribe/{cadence}")
def subscribe_page(request:Request,cadence:str):
    artist=core.current_artist(request)
    if not artist:
        return RedirectResponse("/setup")
    if cadence!="monthly":
        return RedirectResponse("/settings/subscription",303)
    if not billing._account() and not _adopt_existing_platform_merchant(artist):
        return core.page(
            "Billing unavailable",
            '<div class="center"><h1>EMPTY CHAIR // CHECK PAYMENT</h1><p>Subscription checkout is temporarily unavailable.</p><a class="button" href="/settings/subscription">BACK</a></div>',
            chair=True,
        )
    # Platform merchant is ready. Render the normal card-only $97 checkout.
    return billing.subscribe_page(request,"monthly")


@core.app.get("/billing/platform/connect")
def platform_connect_hidden(request:Request):
    # Never send an artist to Square OAuth for the act of paying Empty Chair.
    artist=core.current_artist(request)
    if not artist:
        return RedirectResponse("/setup")
    if _adopt_existing_platform_merchant(artist):
        return RedirectResponse("/billing/subscribe/monthly",303)
    return RedirectResponse("/settings/subscription",303)


print("Empty Chair 2.0 billing checkout loaded // no artist Square sign-in",flush=True)
