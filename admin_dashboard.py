"""Private Empty Chair owner dashboard across every pilot studio."""

import os

from fastapi import HTTPException, Request
from fastapi.responses import HTMLResponse

import app as core
import stripe_deposits


PILOT_MONTHLY_PRICE = float(os.getenv("EMPTY_CHAIR_PILOT_MONTHLY_PRICE", "99"))
ADMIN_EMAILS = {
    core.normalize_email(email)
    for email in os.getenv(
        "EMPTY_CHAIR_ADMIN_EMAILS",
        "daniels.joshua100@gmail.com",
    ).split(",")
    if core.normalize_email(email)
}


def is_platform_admin(user):
    return bool(user and core.normalize_email(user["email"]) in ADMIN_EMAILS)


core.templates.env.globals["is_platform_admin"] = is_platform_admin


def _count(conn, query, params=()):
    row = core.db_fetchone(conn, query, params)
    return int(row["n"] or 0) if row else 0


def _money(conn, query, params=()):
    row = core.db_fetchone(conn, query, params)
    return float(row["total"] or 0) if row else 0.0


def _subscription_financials(subscription_id):
    if not subscription_id or not stripe_deposits.STRIPE_SECRET_KEY:
        return 0.0, 0.0, "not_connected"
    try:
        subscription = stripe_deposits._stripe_get(f"/subscriptions/{subscription_id}")
        invoices = stripe_deposits._stripe_get(
            f"/invoices?subscription={subscription_id}&status=paid&limit=100"
        )
        collected = sum(float(invoice.get("amount_paid") or 0) for invoice in invoices.get("data", [])) / 100
        status = subscription.get("status") or "unknown"
        mrr = PILOT_MONTHLY_PRICE if status in {"active", "trialing"} else 0.0
        return mrr, collected, status
    except Exception:
        return PILOT_MONTHLY_PRICE, 0.0, "unavailable"


def _studio_snapshot(conn, shop):
    shop_id = shop["id"]
    artist_count = _count(
        conn,
        "SELECT COUNT(*) AS n FROM artists WHERE shop_id=? AND active=1",
        (shop_id,),
    )
    customer_count = _count(
        conn,
        "SELECT COUNT(*) AS n FROM customers WHERE shop_id=?",
        (shop_id,),
    )
    calendar_count = _count(
        conn,
        """SELECT COUNT(*) AS n FROM google_calendar_connections gc
           JOIN users u ON u.id=gc.user_id WHERE u.shop_id=?""",
        (shop_id,),
    )
    chairs_filling = _count(
        conn,
        "SELECT COUNT(*) AS n FROM openings WHERE shop_id=? AND status='RECOVERY_ACTIVE'",
        (shop_id,),
    )
    chairs_filled = _count(
        conn,
        "SELECT COUNT(*) AS n FROM openings WHERE shop_id=? AND status IN ('BOOKED','COMPLETED')",
        (shop_id,),
    )
    total_chairs = _count(
        conn,
        "SELECT COUNT(*) AS n FROM openings WHERE shop_id=?",
        (shop_id,),
    )
    recovered_revenue = _money(
        conn,
        """SELECT COALESCE(SUM(price),0) AS total FROM openings
           WHERE shop_id=? AND status IN ('BOOKED','COMPLETED')""",
        (shop_id,),
    )
    paid_activation = core.db_fetchone(
        conn,
        """SELECT ca.subscription_id,ca.consumed_at FROM consumed_activations ca
           JOIN users u ON u.id=ca.user_id WHERE u.shop_id=?
           ORDER BY ca.consumed_at DESC LIMIT 1""",
        (shop_id,),
    )
    owner = core.db_fetchone(
        conn,
        "SELECT name,email,created_at FROM users WHERE shop_id=? ORDER BY created_at LIMIT 1",
        (shop_id,),
    )

    steps = [
        {"label": "Account", "done": True},
        {"label": "Artist", "done": artist_count > 0},
        {"label": "Customers", "done": customer_count > 0},
        {"label": "Calendar", "done": calendar_count > 0},
        {
            "label": "Stripe",
            "done": bool(shop["stripe_charges_enabled"] and shop["stripe_payouts_enabled"]),
        },
    ]
    completed_steps = sum(1 for step in steps if step["done"])
    onboarding_percent = int(round(completed_steps / len(steps) * 100))
    your_mrr, your_revenue, subscription_status = _subscription_financials(
        paid_activation["subscription_id"] if paid_activation else ""
    )

    if onboarding_percent == 100:
        onboarding_status = "Ready"
    elif completed_steps <= 1:
        onboarding_status = "Just joined"
    else:
        onboarding_status = "In progress"

    return {
        "id": shop_id,
        "name": shop["name"],
        "email": shop["email"] or (owner["email"] if owner else ""),
        "owner_name": owner["name"] if owner else "Owner",
        "joined_at": paid_activation["consumed_at"] if paid_activation else shop["created_at"],
        "is_paid_pilot": bool(paid_activation),
        "steps": steps,
        "completed_steps": completed_steps,
        "onboarding_percent": onboarding_percent,
        "onboarding_status": onboarding_status,
        "artist_count": artist_count,
        "customer_count": customer_count,
        "chairs_filling": chairs_filling,
        "chairs_filled": chairs_filled,
        "total_chairs": total_chairs,
        "recovered_revenue": recovered_revenue,
        "your_mrr": your_mrr,
        "your_revenue": your_revenue,
        "subscription_status": subscription_status,
    }


@core.app.get("/owner", response_class=HTMLResponse)
def owner_control_room(request: Request):
    user, redirect = core.login_required_redirect(request)
    if redirect:
        return redirect
    if not is_platform_admin(user):
        raise HTTPException(404, "Not found")

    conn = core.connect()
    try:
        shops = core.db_fetchall(
            conn,
            """SELECT * FROM shops
               WHERE id NOT IN ('shop_demo','shop_live_demo')
                 AND status='active'
               ORDER BY created_at DESC""",
        )
        studios = [_studio_snapshot(conn, shop) for shop in shops]
    finally:
        conn.close()

    paid_studios = [studio for studio in studios if studio["is_paid_pilot"]]
    metrics = {
        "studios": len(studios),
        "paid_studios": len(paid_studios),
        "ready_studios": sum(1 for studio in studios if studio["onboarding_percent"] == 100),
        "chairs_filling": sum(studio["chairs_filling"] for studio in studios),
        "chairs_filled": sum(studio["chairs_filled"] for studio in studios),
        "studio_revenue": sum(studio["recovered_revenue"] for studio in studios),
        "your_mrr": sum(studio["your_mrr"] for studio in studios),
        "your_revenue": sum(studio["your_revenue"] for studio in studios),
    }

    current_shop = next((shop for shop in shops if shop["id"] == user["shop_id"]), None)
    return core.templates.TemplateResponse(
        request=request,
        name="owner_dashboard.html",
        context={
            "user": user,
            "shop": current_shop,
            "studios": studios,
            "metrics": metrics,
            "pilot_price": PILOT_MONTHLY_PRICE,
        },
    )
