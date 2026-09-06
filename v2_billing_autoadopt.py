"""Reuse the founder's existing connected Square merchant for Empty Chair billing when safe.

This removes an unnecessary second Square sign-in during setup. The existing artist Square
OAuth token is only adopted when that merchant can read Empty Chair's known subscription
plan, which proves it is the platform merchant account.
"""
from fastapi import Request
from fastapi.responses import RedirectResponse
import v2_app as core
import v2_artist_payments as artist_payments
import v2_subscription_billing as billing


def _replace_platform_connect(route):
    path=getattr(route,"path",None)
    methods=getattr(route,"methods",set()) or set()
    return path=="/billing/platform/connect" and "GET" in methods


core.app.router.routes[:]=[r for r in core.app.router.routes if not _replace_platform_connect(r)]


@core.app.get("/billing/platform/connect")
def platform_connect(request:Request):
    artist=core.current_artist(request)
    if not artist:
        return RedirectResponse("/setup")

    # Already configured once: nothing else to do.
    if billing._account():
        return RedirectResponse("/settings/subscription",303)

    # First choice: reuse this artist's already-connected Square merchant. This avoids
    # another Square login for the founder while still refusing arbitrary artist accounts.
    acct=artist_payments.square_account(artist["id"])
    token=artist_payments.square_token(acct) if acct else ""
    if acct and token and acct.get("location_id"):
        try:
            # Only the Square merchant that owns the known Empty Chair catalog plan can
            # pass this lookup. If it fails, we fall back to normal Square OAuth below.
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
            core.event("billing.square.adopted",artist["id"],{"merchant_id":acct.get("merchant_id"),"location_id":acct.get("location_id"),"plan_variation_id":variation})
            return RedirectResponse("/billing/subscribe/monthly",303)
        except Exception as exc:
            try:core.run("DELETE FROM platform_billing_account WHERE id=1")
            except Exception:pass
            print(f"Existing Square merchant not usable for platform billing: {type(exc).__name__}: {exc}",flush=True)

    # Fallback only when the existing connected merchant is not the Empty Chair merchant.
    return billing.platform_connect(request)


print("Empty Chair 2.0 billing auto-adopt loaded",flush=True)
