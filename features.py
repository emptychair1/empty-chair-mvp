import csv
import io
import json
import uuid

from fastapi import File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse

import app as core

app = core.app


def remove_route(path, method):
    method = method.upper()
    app.router.routes = [
        route
        for route in app.router.routes
        if not (
            getattr(route, "path", None) == path
            and method in (getattr(route, "methods", set()) or set())
        )
    ]


@app.get("/bookings", response_class=HTMLResponse)
def bookings_page(request: Request):
    user, redirect = core.login_required_redirect(request)
    if redirect:
        return redirect

    conn = core.connect()
    shop = core.db_fetchone(
        conn,
        "SELECT * FROM shops WHERE id = ? LIMIT 1",
        (user["shop_id"],),
    )
    bookings = core.db_fetchall(
        conn,
        """
        SELECT
            b.*,
            c.name AS customer_name,
            c.phone AS customer_phone,
            o.date,
            o.start_time,
            o.service,
            o.style,
            a.name AS artist_name
        FROM bookings b
        JOIN customers c ON c.id = b.customer_id
        JOIN openings o ON o.id = b.opening_id
        JOIN artists a ON a.id = b.artist_id
        WHERE o.shop_id = ?
        ORDER BY o.date DESC, o.start_time DESC
        """,
        (user["shop_id"],),
    )
    conn.close()

    return core.templates.TemplateResponse(
        request=request,
        name="bookings.html",
        context={
            "user": user,
            "shop": shop,
            "bookings": bookings,
        },
    )


@app.get("/recovery", response_class=HTMLResponse)
def recovery_page(request: Request):
    user, redirect = core.login_required_redirect(request)
    if redirect:
        return redirect

    conn = core.connect()
    shop = core.db_fetchone(
        conn,
        "SELECT * FROM shops WHERE id = ? LIMIT 1",
        (user["shop_id"],),
    )
    openings = core.db_fetchall(
        conn,
        """
        SELECT o.*, a.name AS artist_name
        FROM openings o
        JOIN artists a ON a.id = o.artist_id
        WHERE o.shop_id = ?
          AND o.status IN (
              'RECOVERY_ACTIVE',
              'CLAIMED',
              'BOOKED',
              'COMPLETED',
              'NO_RECOVERY'
          )
        ORDER BY o.created_at DESC
        """,
        (user["shop_id"],),
    )

    campaigns = []
    for opening in openings:
        offers = core.db_fetchall(
            conn,
            """
            SELECT ofr.*, c.name AS customer_name
            FROM offers ofr
            JOIN customers c ON c.id = ofr.customer_id
            WHERE ofr.opening_id = ?
            ORDER BY ofr.rank
            """,
            (opening["id"],),
        )
        active = next(
            (offer for offer in offers if offer["status"] == "SENT"),
            None,
        )
        claimed = next(
            (offer for offer in offers if offer["status"] == "CLAIMED"),
            None,
        )
        campaigns.append(
            {
                "opening": opening,
                "offers": offers,
                "active": active,
                "claimed": claimed,
            }
        )

    conn.close()

    return core.templates.TemplateResponse(
        request=request,
        name="recovery.html",
        context={
            "user": user,
            "shop": shop,
            "campaigns": campaigns,
        },
    )


@app.get("/customers", response_class=HTMLResponse)
def customers_page(request: Request):
    user, redirect = core.login_required_redirect(request)
    if redirect:
        return redirect

    conn = core.connect()
    shop = core.db_fetchone(
        conn,
        "SELECT * FROM shops WHERE id = ? LIMIT 1",
        (user["shop_id"],),
    )
    customers = core.db_fetchall(
        conn,
        """
        SELECT *
        FROM customers
        WHERE shop_id = ?
        ORDER BY completed_count DESC, name
        """,
        (user["shop_id"],),
    )
    conn.close()

    consented = sum(
        1
        for customer in customers
        if customer["communication_consent"]
    )
    estimated_lifetime_spend = sum(
        float(customer["average_spend"] or 0)
        * int(customer["completed_count"] or 0)
        for customer in customers
    )

    return core.templates.TemplateResponse(
        request=request,
        name="customers.html",
        context={
            "user": user,
            "shop": shop,
            "customers": customers,
            "consented": consented,
            "estimated_lifetime_spend": estimated_lifetime_spend,
        },
    )


@app.get("/settings", response_class=HTMLResponse)
def settings_page(request: Request, saved: int = 0):
    user, redirect = core.login_required_redirect(request)
    if redirect:
        return redirect

    conn = core.connect()
    shop = core.db_fetchone(
        conn,
        "SELECT * FROM shops WHERE id = ? LIMIT 1",
        (user["shop_id"],),
    )
    conn.close()

    return core.templates.TemplateResponse(
        request=request,
        name="settings.html",
        context={
            "user": user,
            "shop": shop,
            "saved": bool(saved),
            "sms_ready": all(
                [
                    core.TWILIO_ACCOUNT_SID,
                    core.TWILIO_AUTH_TOKEN,
                    core.TWILIO_FROM_NUMBER,
                ]
            ),
            "email_ready": bool(core.RESEND_API_KEY),
            "demo_mode": core.DEMO_MODE,
            "database_type": "PostgreSQL" if core.USE_POSTGRES else "SQLite",
        },
    )


@app.post("/settings")
def update_settings(
    request: Request,
    name: str = Form(...),
    email: str = Form(""),
    phone: str = Form(""),
    booking_url: str = Form(""),
    timezone_name: str = Form("America/New_York"),
):
    user, redirect = core.login_required_redirect(request)
    if redirect:
        return redirect

    name = name.strip()
    if not name:
        raise HTTPException(400, "Shop name is required.")

    conn = core.connect()
    core.db_execute(
        conn,
        """
        UPDATE shops
        SET
            name = ?,
            email = ?,
            phone = ?,
            booking_url = ?,
            timezone = ?
        WHERE id = ?
        """,
        (
            name,
            email.strip() or None,
            phone.strip() or None,
            booking_url.strip() or None,
            timezone_name.strip() or "America/New_York",
            user["shop_id"],
        ),
    )
    conn.commit()
    conn.close()

    core.event(
        "shop.settings_updated",
        "shop",
        user["shop_id"],
    )

    return RedirectResponse(
        "/settings?saved=1",
        status_code=303,
    )


remove_route("/import/customers", "POST")


@app.post("/import/customers", response_class=HTMLResponse)
async def import_customers_safe(
    request: Request,
    file: UploadFile = File(...),
):
    user, redirect = core.login_required_redirect(request)
    if redirect:
        return redirect

    if not file.filename or not file.filename.lower().endswith(".csv"):
        raise HTTPException(400, "Please upload a CSV file.")

    raw_data = await file.read()
    try:
        text = raw_data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise HTTPException(400, "CSV must be UTF-8 encoded.") from exc

    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        raise HTTPException(400, "CSV has no header row.")

    headers = {
        header.strip().lower()
        for header in reader.fieldnames
        if header
    }
    missing = {"name", "phone"} - headers
    if missing:
        raise HTTPException(
            400,
            "Missing required columns: " + ", ".join(sorted(missing)),
        )

    conn = core.connect()
    shop_id = user["shop_id"]
    imported = 0
    updated = 0
    skipped = 0
    errors = []

    for row_number, raw_row in enumerate(reader, start=2):
        try:
            row = {
                (key or "").strip().lower(): (value or "").strip()
                for key, value in raw_row.items()
            }

            name = row.get("name", "")
            phone = row.get("phone", "")
            if not name or not phone:
                skipped += 1
                errors.append(
                    f"Row {row_number}: name and phone are required."
                )
                continue

            supplied_id = row.get("id", "")
            existing = None

            if supplied_id:
                existing = core.db_fetchone(
                    conn,
                    """
                    SELECT *
                    FROM customers
                    WHERE id = ?
                      AND shop_id = ?
                    LIMIT 1
                    """,
                    (supplied_id, shop_id),
                )

            if not existing:
                existing = core.db_fetchone(
                    conn,
                    """
                    SELECT *
                    FROM customers
                    WHERE shop_id = ?
                      AND phone = ?
                    LIMIT 1
                    """,
                    (shop_id, phone),
                )

            consent = (
                1
                if row.get("communication_consent", "0").lower()
                in {"1", "true", "yes", "y", "on"}
                else 0
            )

            email = row.get("email", "") or None
            preferred_artists = row.get("preferred_artists", "")
            preferred_styles = row.get("preferred_styles", "")
            preferred_services = (
                row.get("preferred_services", "tattoo") or "tattoo"
            )
            appointment_count = core.normalize_int(
                row.get("appointment_count", "0")
            )
            completed_count = core.normalize_int(
                row.get("completed_count", "0")
            )
            cancellation_count = core.normalize_int(
                row.get("cancellation_count", "0")
            )
            no_show_count = core.normalize_int(
                row.get("no_show_count", "0")
            )
            average_spend = core.normalize_float(
                row.get("average_spend", "0")
            )
            timestamp = core.now_iso()

            if existing:
                core.db_execute(
                    conn,
                    """
                    UPDATE customers
                    SET
                        name = ?,
                        phone = ?,
                        email = ?,
                        communication_consent = ?,
                        preferred_artists = ?,
                        preferred_styles = ?,
                        preferred_services = ?,
                        appointment_count = ?,
                        completed_count = ?,
                        cancellation_count = ?,
                        no_show_count = ?,
                        average_spend = ?,
                        updated_at = ?
                    WHERE id = ?
                      AND shop_id = ?
                    """,
                    (
                        name,
                        phone,
                        email,
                        consent,
                        preferred_artists,
                        preferred_styles,
                        preferred_services,
                        appointment_count,
                        completed_count,
                        cancellation_count,
                        no_show_count,
                        average_spend,
                        timestamp,
                        existing["id"],
                        shop_id,
                    ),
                )
                updated += 1
            else:
                customer_id = (
                    supplied_id
                    or f"cust_{uuid.uuid4().hex[:12]}"
                )

                id_conflict = core.db_fetchone(
                    conn,
                    "SELECT id FROM customers WHERE id = ? LIMIT 1",
                    (customer_id,),
                )
                if id_conflict:
                    customer_id = f"cust_{uuid.uuid4().hex[:12]}"

                core.db_execute(
                    conn,
                    """
                    INSERT INTO customers(
                        id,
                        shop_id,
                        name,
                        phone,
                        email,
                        communication_consent,
                        preferred_artists,
                        preferred_styles,
                        preferred_services,
                        appointment_count,
                        completed_count,
                        cancellation_count,
                        no_show_count,
                        average_spend,
                        created_at,
                        updated_at
                    )
                    VALUES(
                        ?, ?, ?, ?, ?, ?, ?, ?,
                        ?, ?, ?, ?, ?, ?, ?, ?
                    )
                    """,
                    (
                        customer_id,
                        shop_id,
                        name,
                        phone,
                        email,
                        consent,
                        preferred_artists,
                        preferred_styles,
                        preferred_services,
                        appointment_count,
                        completed_count,
                        cancellation_count,
                        no_show_count,
                        average_spend,
                        timestamp,
                        timestamp,
                    ),
                )
                imported += 1

            conn.commit()

        except Exception as exc:
            conn.rollback()
            skipped += 1
            errors.append(f"Row {row_number}: {exc}")

    conn.close()

    core.event(
        "customers.imported",
        "shop",
        shop_id,
        json.dumps(
            {
                "imported": imported,
                "updated": updated,
                "skipped": skipped,
            }
        ),
    )

    return core.templates.TemplateResponse(
        request=request,
        name="import_result.html",
        context={
            "imported": imported,
            "updated": updated,
            "skipped": skipped,
            "errors": errors,
            "return_url": "/customers",
            "return_label": "Back to Customers",
        },
    )
