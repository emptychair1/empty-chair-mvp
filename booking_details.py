"""Studio-facing booking detail view for calendar appointments."""
from fastapi import HTTPException, Request
from fastapi.responses import HTMLResponse

import app as core

app = core.app


@app.get("/bookings/{booking_id}", response_class=HTMLResponse)
def booking_details(request: Request, booking_id: str):
    user, redirect = core.login_required_redirect(request)
    if redirect:
        return redirect

    conn = core.connect()
    try:
        booking = core.db_fetchone(
            conn,
            """
            SELECT
                b.*,
                o.shop_id,
                o.date,
                o.start_time,
                o.end_time,
                o.service,
                o.style,
                o.price,
                a.name AS artist_name,
                c.name AS customer_name,
                c.phone AS customer_phone,
                c.email AS customer_email
            FROM bookings b
            JOIN openings o ON o.id = b.opening_id
            JOIN artists a ON a.id = b.artist_id
            JOIN customers c ON c.id = b.customer_id
            WHERE b.id = ? AND o.shop_id = ?
            LIMIT 1
            """,
            (booking_id, user["shop_id"]),
        )
    finally:
        conn.close()

    if not booking:
        raise HTTPException(404, "Booking not found")

    return core.templates.TemplateResponse(
        request=request,
        name="booking_details.html",
        context={"user": user, "booking": booking},
    )
