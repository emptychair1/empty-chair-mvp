"""Harden secure quote -> Stripe Checkout handoff.

No DB or network work occurs at import time. This middleware intercepts only the
public quote deposit POST so Stripe/API errors cannot become a bare production 500.
"""
import html
import urllib.parse

from fastapi import Request
from fastapi.responses import HTMLResponse, RedirectResponse

import app as core
import consultation_quotes
import stripe_deposits


def _error_page(title, detail, token, status_code=503):
    safe_title = html.escape(str(title))
    safe_detail = html.escape(str(detail))
    inner = f"""
    <section class='q-card'>
      <div class='q-kicker'>Secure Deposit</div>
      <h1>{safe_title}</h1>
      <div class='q-status'>{safe_detail}</div>
      <a class='q-button' href='/q/{html.escape(token)}'>Back to quote</a>
      <div class='q-note'>Your quote is still accepted. No card was charged by this failed attempt.</div>
    </section>
    """
    return HTMLResponse(
        consultation_quotes._customer_shell(title, inner),
        status_code=status_code,
        headers={"Cache-Control": "no-store"},
    )


def _load_quote(token):
    conn = core.connect()
    try:
        return consultation_quotes._quote_by_token(conn, token)
    finally:
        conn.close()


def _save_checkout(quote_id, session_id):
    conn = core.connect()
    try:
        core.db_execute(
            conn,
            """UPDATE consultation_quotes
               SET deposit_status='PENDING',stripe_checkout_session_id=?
               WHERE id=? AND deposit_status<>'PAID'""",
            (session_id, quote_id),
        )
        conn.commit()
    finally:
        conn.close()


def _checkout_fields(q, token, include_on_behalf_of=True):
    deposit = float(q["deposit_amount"] or 0)
    amount_cents = int(round(deposit * 100))
    quote_id = str(q["id"])
    shop_account = str(q["stripe_account_id"] or "")
    shop_name = str(q["shop_name"] or "Studio")
    project_title = str(q["title"] or "Tattoo project")
    base = core.PUBLIC_BASE_URL.rstrip("/")
    fields = {
        "mode": "payment",
        "success_url": f"{base}/q/{token}?deposit=success&session_id={{CHECKOUT_SESSION_ID}}",
        "cancel_url": f"{base}/q/{token}?deposit=cancelled",
        "client_reference_id": quote_id,
        "line_items[0][quantity]": "1",
        "line_items[0][price_data][currency]": stripe_deposits.STRIPE_CURRENCY,
        "line_items[0][price_data][unit_amount]": str(amount_cents),
        "line_items[0][price_data][product_data][name]": f"Tattoo deposit · {shop_name}",
        "line_items[0][price_data][product_data][description]": project_title,
        "metadata[quote_id]": quote_id,
        "payment_intent_data[metadata][quote_id]": quote_id,
        "payment_intent_data[transfer_data][destination]": shop_account,
    }
    if include_on_behalf_of:
        fields["payment_intent_data[on_behalf_of]"] = shop_account
    customer_email = str(q["customer_email"] or "").strip()
    if customer_email:
        fields["customer_email"] = customer_email
    return fields


def _create_checkout(q, token):
    quote_id = str(q["id"])
    shop_account = str(q["stripe_account_id"] or "")

    # Validate against Stripe at click time instead of trusting stale DB flags.
    account = stripe_deposits._stripe_get(
        "/accounts/" + urllib.parse.quote(shop_account, safe="")
    )
    if not account.get("charges_enabled"):
        raise RuntimeError("The studio's Stripe account is connected but card payments are not enabled yet.")
    if not account.get("payouts_enabled"):
        raise RuntimeError("The studio's Stripe account still needs payout verification before it can receive deposits.")

    # on_behalf_of is useful when supported, but is not required for a destination
    # charge. Some Connect account configurations reject it. Retry safely without it.
    try:
        return stripe_deposits._stripe_post(
            "/checkout/sessions",
            _checkout_fields(q, token, include_on_behalf_of=True),
            idempotency_key=f"empty-chair-quote-deposit-{quote_id}-v2",
        )
    except Exception as first_exc:
        core.event(
            "quote.deposit_checkout_retry",
            "quote",
            quote_id,
            str(first_exc)[:500],
        )
        return stripe_deposits._stripe_post(
            "/checkout/sessions",
            _checkout_fields(q, token, include_on_behalf_of=False),
            idempotency_key=f"empty-chair-quote-deposit-{quote_id}-v2-fallback",
        )


@core.app.middleware("http")
async def safe_quote_deposit_checkout(request: Request, call_next):
    path = request.url.path.rstrip("/")
    parts = path.split("/")
    if request.method != "POST" or len(parts) != 4 or parts[1] != "q" or parts[3] != "deposit":
        return await call_next(request)

    token = parts[2]
    try:
        q = _load_quote(token)
        if not q:
            return _error_page("Quote unavailable", "This secure quote could not be found.", token, 404)
        if str(q["status"]) != "accepted":
            return RedirectResponse(f"/q/{token}", status_code=303)
        if str(q["deposit_status"]) == "PAID":
            return RedirectResponse(f"/q/{token}", status_code=303)
        if float(q["deposit_amount"] or 0) <= 0:
            return RedirectResponse(f"/q/{token}", status_code=303)
        if not stripe_deposits.STRIPE_SECRET_KEY:
            return _error_page("Deposit setup incomplete", "Stripe is not configured for secure deposits yet.", token)
        if not q["stripe_account_id"]:
            return _error_page("Deposit setup incomplete", "The studio needs to connect Stripe before accepting this deposit.", token)

        session = _create_checkout(q, token)
        session_id = str(session.get("id") or "")
        checkout_url = str(session.get("url") or "")
        if not session_id or not checkout_url:
            raise RuntimeError("Stripe did not return a usable Checkout session.")

        _save_checkout(q["id"], session_id)
        core.event("quote.deposit_checkout_created", "quote", q["id"], session_id)
        return RedirectResponse(checkout_url, status_code=303)
    except Exception as exc:
        core.event("quote.deposit_checkout_failed", "quote", token[:64], str(exc)[:900])
        message = str(exc)
        if "No such account" in message or "does not exist" in message:
            message = "The studio's saved Stripe connection does not match the active Stripe environment. Reconnect Stripe in Empty Chair settings, then try again."
        elif "Stripe request failed" in message:
            # Keep enough information to make the next failure actionable without
            # exposing keys or stack traces to the customer.
            message = "Stripe could not start the secure checkout. The studio has been given the payment error so it can be corrected without losing your accepted quote."
        return _error_page("Deposit checkout unavailable", message, token)
