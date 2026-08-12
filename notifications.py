"""Customer notification layer for Empty Chair.

This module augments the existing core notification functions without changing
legacy routes. Recovery offers are delivered by SMS and email when an email is
available. Successful claims send customer confirmations through both channels.
"""

from html import escape

import app as core
from twilio.rest import Client


_PATCHED = False
_ORIGINAL_SEND_SMS = core.send_sms
_ORIGINAL_SEND_RECOVERY_EMAIL = core.send_recovery_email


def _first_name(name):
    value = (name or "there").strip()
    return value.split()[0] if value else "there"


def _claim_url(offer_id):
    return f"{core.PUBLIC_BASE_URL.rstrip('/')}/offer/{offer_id}"


def _booking_url(booking_id):
    return f"{core.PUBLIC_BASE_URL.rstrip('/')}/booking/{booking_id}"


def _send_text(to_phone, body):
    if not to_phone:
        return False

    if core.DEMO_MODE:
        print()
        print("--- DEMO SMS ---")
        print(f"To: {to_phone}")
        print(body)
        print("----------------")
        print()
        return True

    if not all(
        [
            core.TWILIO_ACCOUNT_SID,
            core.TWILIO_AUTH_TOKEN,
            core.TWILIO_FROM_NUMBER,
        ]
    ):
        print("SMS skipped: Twilio is not configured.")
        return False

    try:
        client = Client(
            core.TWILIO_ACCOUNT_SID,
            core.TWILIO_AUTH_TOKEN,
        )
        client.messages.create(
            body=body,
            from_=core.TWILIO_FROM_NUMBER,
            to=to_phone,
        )
        return True
    except Exception as exc:
        print("SMS send failed:", str(exc))
        return False


def send_offer_email(customer, opening, offer_id):
    email = core.normalize_email(customer["email"] if "email" in customer.keys() else None)
    if not email:
        return False

    first_name = escape(_first_name(customer["name"]))
    style = escape(opening["style"] or "tattoo")
    date = escape(str(opening["date"]))
    start_time = escape(str(opening["start_time"]))
    price = float(opening["price"] or 0)
    claim_url = _claim_url(offer_id)

    return core.send_email(
        email,
        "A tattoo opening just became available",
        f"""
        <div style="font-family:Arial,sans-serif;max-width:560px;margin:auto;line-height:1.55;">
            <h2>Hey {first_name} — an opening just dropped.</h2>
            <p>
                A <strong>{style}</strong> appointment is available on
                <strong>{date}</strong> at <strong>{start_time}</strong>
                for <strong>${price:.0f}</strong>.
            </p>
            <p>This offer is held for you for 30 minutes.</p>
            <p style="margin:28px 0;">
                <a href="{claim_url}"
                   style="background:#9f1118;color:#fff;text-decoration:none;padding:14px 20px;border-radius:8px;display:inline-block;font-weight:700;">
                    Claim this opening
                </a>
            </p>
            <p style="font-size:13px;color:#666;">
                If you do not want it, you can decline from the offer page and
                Empty Chair will pass it to the next customer.
            </p>
        </div>
        """,
    )


def send_offer_multichannel(customer, opening, offer_id):
    """Preserve the existing SMS send and add customer email when available."""
    sms_sent = _ORIGINAL_SEND_SMS(customer, opening, offer_id)

    email_sent = False
    try:
        email_sent = send_offer_email(customer, opening, offer_id)
    except Exception as exc:
        print("Offer email send failed:", str(exc))

    core.event(
        "offer.delivery",
        "offer",
        offer_id,
        {
            "sms": bool(sms_sent),
            "email": bool(email_sent),
        },
    )

    return bool(sms_sent or email_sent)


def _claim_details(opening_id):
    conn = core.connect()
    try:
        return core.db_fetchone(
            conn,
            """
            SELECT
                o.id AS opening_id,
                o.date,
                o.start_time,
                o.price,
                b.id AS booking_id,
                c.name AS customer_name,
                c.phone AS customer_phone,
                c.email AS customer_email,
                a.name AS artist_name,
                s.name AS shop_name
            FROM openings o
            JOIN bookings b ON b.id = o.booking_id
            JOIN customers c ON c.id = b.customer_id
            JOIN artists a ON a.id = o.artist_id
            JOIN shops s ON s.id = o.shop_id
            WHERE o.id = ?
            LIMIT 1
            """,
            (opening_id,),
        )
    finally:
        conn.close()


def send_customer_claim_confirmation(opening_id):
    row = _claim_details(opening_id)
    if not row:
        return False

    first_name = _first_name(row["customer_name"])
    booking_url = _booking_url(row["booking_id"])
    price = float(row["price"] or 0)

    sms_body = (
        f"You're in, {first_name}! Your opening with {row['artist_name']} "
        f"on {row['date']} at {row['start_time']} has been claimed. "
        f"Details: {booking_url}"
    )
    sms_sent = _send_text(row["customer_phone"], sms_body)

    email_sent = False
    customer_email = core.normalize_email(row["customer_email"])
    if customer_email:
        email_sent = core.send_email(
            customer_email,
            f"You claimed the opening at {row['shop_name']}",
            f"""
            <div style="font-family:Arial,sans-serif;max-width:560px;margin:auto;line-height:1.55;">
                <h2>You got the chair.</h2>
                <p>Hey {escape(first_name)},</p>
                <p>
                    You claimed the opening with
                    <strong>{escape(str(row['artist_name']))}</strong> on
                    <strong>{escape(str(row['date']))}</strong> at
                    <strong>{escape(str(row['start_time']))}</strong>.
                </p>
                <p>Appointment value: <strong>${price:.0f}</strong></p>
                <p style="margin:28px 0;">
                    <a href="{booking_url}"
                       style="background:#9f1118;color:#fff;text-decoration:none;padding:14px 20px;border-radius:8px;display:inline-block;font-weight:700;">
                        View booking details
                    </a>
                </p>
            </div>
            """,
        )

    core.event(
        "booking.customer_notified",
        "booking",
        row["booking_id"],
        {
            "sms": bool(sms_sent),
            "email": bool(email_sent),
        },
    )

    return bool(sms_sent or email_sent)


def send_recovery_email_with_customer_confirmation(opening_id):
    """Keep the shop recovery email and add customer confirmation delivery."""
    shop_email_sent = False
    try:
        shop_email_sent = _ORIGINAL_SEND_RECOVERY_EMAIL(opening_id)
    finally:
        try:
            send_customer_claim_confirmation(opening_id)
        except Exception as exc:
            print("Customer claim confirmation failed:", str(exc))

    return shop_email_sent


def install():
    global _PATCHED
    if _PATCHED:
        return

    core.send_sms = send_offer_multichannel
    core.send_recovery_email = send_recovery_email_with_customer_confirmation
    _PATCHED = True


install()
