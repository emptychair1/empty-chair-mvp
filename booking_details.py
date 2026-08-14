"""Studio-facing booking detail view for calendar appointments."""
from fastapi import HTTPException, Request
from fastapi.responses import HTMLResponse

import app as core

app = core.app


def _owner_booking_response(request: Request, booking_id: str):
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


@app.get("/bookings/{booking_id}", response_class=HTMLResponse)
def booking_details(request: Request, booking_id: str):
    return _owner_booking_response(request, booking_id)


@app.get("/opening/{opening_id}", response_class=HTMLResponse)
def opening_booking_details(request: Request, opening_id: str):
    user, redirect = core.login_required_redirect(request)
    if redirect:
        return redirect

    conn = core.connect()
    try:
        opening = core.db_fetchone(
            conn,
            """
            SELECT booking_id
            FROM openings
            WHERE id = ? AND shop_id = ?
            LIMIT 1
            """,
            (opening_id, user["shop_id"]),
        )
    finally:
        conn.close()

    if not opening:
        raise HTTPException(404, "Opening not found")

    if opening["booking_id"]:
        return _owner_booking_response(request, opening["booking_id"])

    raise HTTPException(404, "No booking exists for this opening")


# Calendar links in the current UI still point to /booking/{id}. Put the
# authenticated studio handler ahead of the older customer-facing route so a
# logged-in owner sees studio controls, while unauthenticated customer links
# continue to fall through to the existing public booking route.
_public_booking_route = next(
    (
        route
        for route in app.router.routes
        if getattr(route, "path", None) == "/booking/{booking_id}"
        and "GET" in (getattr(route, "methods", set()) or set())
    ),
    None,
)

if _public_booking_route is not None:
    app.router.routes.remove(_public_booking_route)


@app.get("/booking/{booking_id}", response_class=HTMLResponse)
def booking_details_compat(request: Request, booking_id: str):
    if request.query_params.get("customer") == "1":
        if _public_booking_route is None:
            raise HTTPException(404, "Booking not found")
        return _public_booking_route.endpoint(request, booking_id)

    user = core.get_current_user(request)
    if user:
        return _owner_booking_response(request, booking_id)
    if _public_booking_route is None:
        raise HTTPException(404, "Booking not found")
    return _public_booking_route.endpoint(request, booking_id)
