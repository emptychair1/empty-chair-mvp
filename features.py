import csv
import calendar
import io
import json
import uuid
from datetime import date, datetime, timezone

from fastapi import File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse

import app as core
import delivery_safety
import google_integration

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
            o.end_time,
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
    open_slots = core.db_fetchall(
        conn,
        """
        SELECT
            o.id,
            o.date,
            o.start_time,
            o.end_time,
            o.service,
            o.style,
            o.price,
            o.status,
            a.name AS artist_name
        FROM openings o
        JOIN artists a ON a.id = o.artist_id
        WHERE o.shop_id = ?
          AND o.status IN ('OPEN', 'NO_RECOVERY', 'RECOVERY_ACTIVE', 'CLAIMED')
        ORDER BY o.date, o.start_time
        """,
        (user["shop_id"],),
    )
    conn.close()

    month_text = request.query_params.get("month", "")
    try:
        selected_month = date.fromisoformat(f"{month_text}-01") if month_text else date.today().replace(day=1)
    except ValueError:
        selected_month = date.today().replace(day=1)

    previous_month = (
        selected_month.replace(year=selected_month.year - 1, month=12)
        if selected_month.month == 1
        else selected_month.replace(month=selected_month.month - 1)
    )
    next_month = (
        selected_month.replace(year=selected_month.year + 1, month=1)
        if selected_month.month == 12
        else selected_month.replace(month=selected_month.month + 1)
    )
    calendar_weeks = calendar.Calendar(firstweekday=6).monthdatescalendar(
        selected_month.year,
        selected_month.month,
    )
    calendar_events = {}
    confirmed_count = 0
    confirmed_revenue = 0.0
    for row in bookings:
        if row["status"] not in ("CONFIRMED", "COMPLETED"):
            continue
        confirmed_count += 1
        confirmed_revenue += float(row["amount"] or 0)
        if str(row["date"])[:7] == selected_month.strftime("%Y-%m"):
            event = dict(row)
            event.update(
                {
                    "calendar_state": "completed" if row["status"] == "COMPLETED" else "filled",
                    "status_label": "Completed" if row["status"] == "COMPLETED" else "Filled",
                    "detail": row["customer_name"],
                    "value": float(row["amount"] or 0),
                    "href": f"/booking/{row['id']}",
                }
            )
            calendar_events.setdefault(str(row["date"]), []).append(event)

    needs_fill_count = 0
    working_count = 0
    for row in open_slots:
        if row["status"] in ("OPEN", "NO_RECOVERY"):
            needs_fill_count += 1
            calendar_state = "open"
            status_label = "Needs filling"
        else:
            working_count += 1
            calendar_state = "working"
            status_label = "Claim pending" if row["status"] == "CLAIMED" else "Empty Chair working"
        if str(row["date"])[:7] == selected_month.strftime("%Y-%m"):
            event = dict(row)
            event.update(
                {
                    "calendar_state": calendar_state,
                    "status_label": status_label,
                    "detail": row["style"] or row["service"] or "Appointment",
                    "value": float(row["price"] or 0),
                    "href": f"/opening/{row['id']}",
                }
            )
            calendar_events.setdefault(str(row["date"]), []).append(event)

    month_start_iso = datetime(selected_month.year, selected_month.month, 1, tzinfo=timezone.utc).isoformat()
    month_end_iso = datetime(next_month.year, next_month.month, 1, tzinfo=timezone.utc).isoformat()
    try:
        external_events = google_integration.external_calendar_events_for_shop(
            user["shop_id"],
            month_start_iso,
            month_end_iso,
        )
    except Exception as exc:
        external_events = []
        core.event("calendar.import_failed", "shop", user["shop_id"], str(exc))
    for external in external_events:
        try:
            start = datetime.fromisoformat(external["start"].replace("Z", "+00:00"))
            end = datetime.fromisoformat(external["end"].replace("Z", "+00:00"))
        except (TypeError, ValueError):
            continue
        day_key = start.date().isoformat()
        start_label = start.strftime("%H:%M")
        end_label = end.strftime("%H:%M")
        calendar_events[day_key] = [
            event
            for event in calendar_events.get(day_key, [])
            if not (
                event.get("artist_name") == external["artist_name"]
                and event.get("calendar_state") in ("open", "working")
                and str(event.get("start_time", ""))[:5] < end_label
                and str(event.get("end_time", ""))[:5] > start_label
            )
        ]
        calendar_events.setdefault(day_key, []).append(
            {
                "id": external["id"],
                "artist_name": external["artist_name"],
                "start_time": start_label,
                "end_time": end_label,
                "calendar_state": "external",
                "status_label": "Google Calendar busy",
                "detail": "External booking",
                "value": 0,
                "style": "",
                "service": "",
                "href": external["html_link"] or "/bookings",
                "external": True,
            }
        )

    for day_events in calendar_events.values():
        day_events.sort(key=lambda event: str(event["start_time"]))

    return core.templates.TemplateResponse(
        request=request,
        name="bookings.html",
        context={
            "user": user,
            "shop": shop,
            "bookings": bookings,
            "calendar_weeks": calendar_weeks,
            "calendar_events": calendar_events,
            "selected_month": selected_month,
            "previous_month": previous_month.strftime("%Y-%m"),
            "next_month": next_month.strftime("%Y-%m"),
            "today": date.today(),
            "confirmed_count": confirmed_count,
            "confirmed_revenue": confirmed_revenue,
            "needs_fill_count": needs_fill_count,
            "working_count": working_count,
        },
    )


@app.get("/recovery", response_class=HTMLResponse)
def recovery_page(request: Request, demo_launched: int = 0):
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
            "demo_mode": core.DEMO_MODE,
            "demo_launched": bool(demo_launched),
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
    customer_rows = []
    for row in customers:
        customer = dict(row)
        customer.update(delivery_safety.contact_status(row))
        customer_rows.append(customer)
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
            "customers": customer_rows,
            "consented": consented,
            "estimated_lifetime_spend": estimated_lifetime_spend,
        },
    )


@app.get("/settings", response_class=HTMLResponse)
def settings_page(request: Request, saved: int = 0, test_email: str = ""):
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
            "test_email": test_email,
            "stripe_ready": bool(__import__("stripe_deposits").configured()),
        },
    )


@app.post("/settings")
def update_settings(
    request: Request,
    name: str = Form(...),
    email: str = Form(""),
    phone: str = Form(""),
    booking_url: str = Form(""),
    deposits_enabled: str = Form(""),
    default_deposit_amount: float = Form(0),
    timezone_name: str = Form("America/New_York"),
):
    user, redirect = core.login_required_redirect(request)
    if redirect:
        return redirect

    name = name.strip()
    if not name:
        raise HTTPException(400, "Shop name is required.")
    default_deposit_amount = max(0, min(float(default_deposit_amount or 0), 10000))

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
            timezone = ?,
            deposits_enabled = ?,
            default_deposit_amount = ?
        WHERE id = ?
        """,
        (
            name,
            email.strip() or None,
            phone.strip() or None,
            booking_url.strip() or None,
            timezone_name.strip() or "America/New_York",
            1 if deposits_enabled else 0,
            default_deposit_amount,
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
            if email and not delivery_safety.valid_email(email):
                errors.append(f"Row {row_number}: email is invalid or a placeholder and was removed.")
                email = None
            if not delivery_safety.valid_phone(phone) and not email:
                consent = 0
                errors.append(f"Row {row_number}: no deliverable email or E.164 phone; contact disabled.")
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

@app.post("/demo/launch-recovery")
def demo_launch_recovery(request: Request):
    user, redirect = core.login_required_redirect(request)
    if redirect:
        return redirect

    if not core.DEMO_MODE:
        raise HTTPException(404, "Demo campaign launcher is disabled.")

    conn = core.connect()
    shop_id = user["shop_id"]

    artist = core.db_fetchone(
        conn,
        """
        SELECT *
        FROM artists
        WHERE shop_id = ?
          AND active = 1
        ORDER BY name
        LIMIT 1
        """,
        (shop_id,),
    )

    if not artist:
        artist_id = f"artist_demo_{uuid.uuid4().hex[:10]}"
        core.db_execute(
            conn,
            """
            INSERT INTO artists(
                id, shop_id, name, email, phone,
                styles, services, active
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, 1)
            """,
            (
                artist_id,
                shop_id,
                "Demo Artist",
                user["email"],
                None,
                "traditional, blackwork",
                "tattoo",
            ),
        )
        artist = {
            "id": artist_id,
            "name": "Demo Artist",
        }

    timestamp = core.now_iso()
    demo_names = [
        ("Demo Sarah", 9, 7, 240.0),
        ("Demo Mike", 7, 6, 210.0),
        ("Demo Jessica", 6, 5, 195.0),
        ("Demo Taylor", 5, 4, 175.0),
        ("Demo Avery", 4, 4, 160.0),
    ]

    for index, (name, appointments, completed, spend) in enumerate(
        demo_names,
        start=1,
    ):
        customer_id = f"demo_test_{shop_id}_{index}"
        existing = core.db_fetchone(
            conn,
            "SELECT id FROM customers WHERE id = ? LIMIT 1",
            (customer_id,),
        )

        values = (
            name,
            f"+15550001{index:03d}",
            user["email"],
            1,
            artist["name"],
            "traditional, blackwork",
            "tattoo",
            appointments,
            completed,
            0,
            0,
            spend,
            None,
            timestamp,
            customer_id,
            shop_id,
        )

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
                    last_offer_at = ?,
                    updated_at = ?
                WHERE id = ?
                  AND shop_id = ?
                """,
                values,
            )
        else:
            core.db_execute(
                conn,
                """
                INSERT INTO customers(
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
                    last_offer_at,
                    updated_at,
                    id,
                    shop_id,
                    created_at
                )
                VALUES(
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
                )
                """,
                values + (timestamp,),
            )

    opening_id = f"opening_demo_{uuid.uuid4().hex[:12]}"
    tomorrow = (
        core.datetime.now(core.timezone.utc)
        + core.timedelta(days=1)
    ).date().isoformat()
    opening_expires = (
        core.datetime.now(core.timezone.utc)
        + core.timedelta(hours=24)
    ).isoformat()

    core.db_execute(
        conn,
        """
        INSERT INTO openings(
            id,
            shop_id,
            artist_id,
            date,
            start_time,
            end_time,
            service,
            style,
            price,
            status,
            created_at,
            expires_at,
            booking_id
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            opening_id,
            shop_id,
            artist["id"],
            tomorrow,
            "14:00",
            "16:00",
            "tattoo",
            "traditional",
            250.0,
            "OPEN",
            timestamp,
            opening_expires,
            None,
        ),
    )

    conn.commit()
    conn.close()

    core.event(
        "demo.recovery_launched",
        "opening",
        opening_id,
        json.dumps(
            {
                "shop_id": shop_id,
                "artist_id": artist["id"],
                "test_customer_count": len(demo_names),
            }
        ),
    )

    conn = core.connect()
    opening = core.db_fetchone(
        conn,
        "SELECT * FROM openings WHERE id = ? LIMIT 1",
        (opening_id,),
    )
    artist_row = core.db_fetchone(
        conn,
        "SELECT * FROM artists WHERE id = ? LIMIT 1",
        (artist["id"],),
    )
    demo_customers = core.db_fetchall(
        conn,
        """
        SELECT *
        FROM customers
        WHERE shop_id = ?
          AND id LIKE ?
          AND communication_consent = 1
        ORDER BY completed_count DESC
        """,
        (shop_id, f"demo_test_{shop_id}_%"),
    )

    candidates = [
        (core.recovery_score(customer, opening, artist_row), customer)
        for customer in demo_customers
    ]
    candidates.sort(
        key=lambda item: (item[0], item[1]["completed_count"] or 0),
        reverse=True,
    )

    for rank, (score, customer) in enumerate(candidates[:5], start=1):
        offer_id = f"offer_{uuid.uuid4().hex[:12]}"
        placeholder_expiration = (
            core.datetime.now(core.timezone.utc)
            + core.timedelta(minutes=30)
        ).isoformat()
        core.db_execute(
            conn,
            """
            INSERT INTO offers(
                id, opening_id, customer_id, score, rank,
                channel, expires_at, status
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                offer_id, opening_id, customer["id"], score, rank,
                "email", placeholder_expiration, "PENDING",
            ),
        )

    core.db_execute(
        conn,
        "UPDATE openings SET status = 'RECOVERY_ACTIVE' WHERE id = ?",
        (opening_id,),
    )
    conn.commit()
    conn.close()

    core.send_next_recovery_offer(opening_id)

    return RedirectResponse(
        "/recovery?demo_launched=1",
        status_code=303,
    )
