import os
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from twilio.rest import Client


DB_PATH = os.getenv("EMPTY_CHAIR_DB", "empty_chair.db")

PUBLIC_BASE_URL = os.getenv(
    "EMPTY_CHAIR_BASE_URL",
    "http://localhost:8000",
)

DEMO_MODE = os.getenv(
    "EMPTY_CHAIR_DEMO_MODE",
    "true",
).lower() == "true"

TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")
TWILIO_FROM_NUMBER = os.getenv("TWILIO_FROM_NUMBER")


app = FastAPI(
    title="Empty Chair",
    version="0.1.0",
)

templates = Jinja2Templates(directory="templates")


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    conn = connect()

    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS shops (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            timezone TEXT NOT NULL DEFAULT 'America/New_York',
            phone TEXT,
            email TEXT,
            booking_url TEXT,
            status TEXT NOT NULL DEFAULT 'active',
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS artists (
            id TEXT PRIMARY KEY,
            shop_id TEXT NOT NULL,
            name TEXT NOT NULL,
            email TEXT,
            phone TEXT,
            styles TEXT NOT NULL DEFAULT '',
            services TEXT NOT NULL DEFAULT 'tattoo',
            active INTEGER NOT NULL DEFAULT 1,
            FOREIGN KEY(shop_id) REFERENCES shops(id)
        );

        CREATE TABLE IF NOT EXISTS customers (
            id TEXT PRIMARY KEY,
            shop_id TEXT NOT NULL,
            name TEXT NOT NULL,
            phone TEXT NOT NULL,
            email TEXT,
            communication_consent INTEGER NOT NULL DEFAULT 0,
            preferred_artists TEXT NOT NULL DEFAULT '',
            preferred_styles TEXT NOT NULL DEFAULT '',
            preferred_services TEXT NOT NULL DEFAULT 'tattoo',
            appointment_count INTEGER NOT NULL DEFAULT 0,
            completed_count INTEGER NOT NULL DEFAULT 0,
            cancellation_count INTEGER NOT NULL DEFAULT 0,
            no_show_count INTEGER NOT NULL DEFAULT 0,
            average_spend REAL NOT NULL DEFAULT 0,
            last_appointment_at TEXT,
            last_offer_at TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS openings (
            id TEXT PRIMARY KEY,
            shop_id TEXT NOT NULL,
            artist_id TEXT NOT NULL,
            date TEXT NOT NULL,
            start_time TEXT NOT NULL,
            end_time TEXT,
            service TEXT NOT NULL,
            style TEXT,
            price REAL NOT NULL,
            status TEXT NOT NULL DEFAULT 'OPEN',
            created_at TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            booking_id TEXT,
            FOREIGN KEY(shop_id) REFERENCES shops(id),
            FOREIGN KEY(artist_id) REFERENCES artists(id)
        );

        CREATE TABLE IF NOT EXISTS offers (
            id TEXT PRIMARY KEY,
            opening_id TEXT NOT NULL,
            customer_id TEXT NOT NULL,
            score REAL NOT NULL,
            rank INTEGER NOT NULL,
            channel TEXT NOT NULL DEFAULT 'sms',
            sent_at TEXT,
            opened_at TEXT,
            responded_at TEXT,
            claimed_at TEXT,
            declined_at TEXT,
            expires_at TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'PENDING',
            decline_reason TEXT,
            FOREIGN KEY(opening_id) REFERENCES openings(id),
            FOREIGN KEY(customer_id) REFERENCES customers(id)
        );

        CREATE TABLE IF NOT EXISTS bookings (
            id TEXT PRIMARY KEY,
            opening_id TEXT NOT NULL,
            customer_id TEXT NOT NULL,
            artist_id TEXT NOT NULL,
            external_booking_id TEXT,
            booking_url TEXT,
            status TEXT NOT NULL DEFAULT 'PENDING',
            amount REAL NOT NULL,
            deposit_amount REAL NOT NULL DEFAULT 0,
            booked_at TEXT,
            completed_at TEXT,
            cancelled_at TEXT,
            FOREIGN KEY(opening_id) REFERENCES openings(id),
            FOREIGN KEY(customer_id) REFERENCES customers(id),
            FOREIGN KEY(artist_id) REFERENCES artists(id)
        );

        CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_type TEXT NOT NULL,
            entity_type TEXT NOT NULL,
            entity_id TEXT NOT NULL,
            metadata TEXT,
            created_at TEXT NOT NULL
        );
        """
    )

    conn.commit()
    conn.close()


def event(event_type, entity_type, entity_id, metadata=""):
    conn = connect()

    conn.execute(
        """
        INSERT INTO events(
            event_type,
            entity_type,
            entity_id,
            metadata,
            created_at
        )
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            event_type,
            entity_type,
            entity_id,
            metadata,
            now_iso(),
        ),
    )

    conn.commit()
    conn.close()


def csv_values(value):
    return {
        x.strip().lower()
        for x in (value or "").split(",")
        if x.strip()
    }


def recovery_score(customer, opening):
    score = 0

    artist_prefs = csv_values(customer["preferred_artists"])
    style_prefs = csv_values(customer["preferred_styles"])
    service_prefs = csv_values(customer["preferred_services"])

    if opening["artist_id"].lower() in artist_prefs:
        score += 30

    if (opening["style"] or "").lower() in style_prefs:
        score += 25

    if opening["service"].lower() in service_prefs:
        score += 20

    if customer["completed_count"] >= 3:
        score += 10

    if (
        customer["cancellation_count"] == 0
        and customer["appointment_count"] > 0
    ):
        score += 5

    if customer["last_offer_at"]:
        try:
            last = datetime.fromisoformat(
                customer["last_offer_at"]
            )

            if datetime.now(timezone.utc) - last < timedelta(days=30):
                score -= 5

        except ValueError:
            pass

    return max(0, min(100, score))


def send_sms(customer, opening, offer_id):
    claim_url = (
        f"{PUBLIC_BASE_URL.rstrip('/')}"
        f"/offer/{offer_id}"
    )

    message = (
        f"Hey {customer['name'].split()[0]} — "
        f"{opening['style'] or 'Tattoo'} opening with your artist "
        f"is available on {opening['date']} at "
        f"{opening['start_time']} for "
        f"${opening['price']:.0f}. "
        f"Claim it: {claim_url}"
    )

    if DEMO_MODE:
        print("\n--- DEMO SMS ---")
        print(f"To: {customer['phone']}")
        print(message)
        print("----------------\n")
        return True

    if not all(
        [
            TWILIO_ACCOUNT_SID,
            TWILIO_AUTH_TOKEN,
            TWILIO_FROM_NUMBER,
        ]
    ):
        raise RuntimeError(
            "Twilio is not configured and DEMO_MODE is false."
        )

    client = Client(
        TWILIO_ACCOUNT_SID,
        TWILIO_AUTH_TOKEN,
    )

    client.messages.create(
        body=message,
        from_=TWILIO_FROM_NUMBER,
        to=customer["phone"],
    )

    return True


@app.on_event("startup")
def startup():
    init_db()


@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request):
    conn = connect()

    shop = conn.execute(
        """
        SELECT *
        FROM shops
        ORDER BY created_at
        LIMIT 1
        """
    ).fetchone()

    artists = conn.execute(
        """
        SELECT *
        FROM artists
        WHERE active = 1
        ORDER BY name
        """
    ).fetchall()

    openings = conn.execute(
        """
        SELECT
            o.*,
            a.name AS artist_name
        FROM openings o
        JOIN artists a
            ON a.id = o.artist_id
        ORDER BY
            o.date,
            o.start_time
        """
    ).fetchall()

    recovered = conn.execute(
        """
        SELECT
            COALESCE(SUM(b.amount), 0) AS total
        FROM bookings b
        WHERE b.status = 'COMPLETED'
        """
    ).fetchone()["total"]

    completed = conn.execute(
        """
        SELECT COUNT(*) AS n
        FROM bookings
        WHERE status = 'COMPLETED'
        """
    ).fetchone()["n"]

    total_openings = conn.execute(
        """
        SELECT COUNT(*) AS n
        FROM openings
        """
    ).fetchone()["n"]

    conn.close()

    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            "shop": shop,
            "artists": artists,
            "openings": openings,
            "recovered": recovered,
            "completed": completed,
            "total_openings": total_openings,
        },
    )


@app.post("/demo/setup")
def demo_setup():
    conn = connect()

    shop = conn.execute(
        "SELECT id FROM shops LIMIT 1"
    ).fetchone()

    if not shop:
        shop_id = "shop_demo"

        conn.execute(
            """
            INSERT INTO shops(
                id,
                name,
                timezone,
                booking_url,
                status,
                created_at
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                shop_id,
                "Demo Tattoo Studio",
                "America/New_York",
                "https://example.com/book",
                "active",
                now_iso(),
            ),
        )

        artists = [
            (
                "artist_alex",
                "Alex",
                "traditional,neo_traditional",
                "tattoo",
            ),
            (
                "artist_jordan",
                "Jordan",
                "blackwork,traditional",
                "tattoo",
            ),
        ]

        for (
            artist_id,
            name,
            styles,
            services,
        ) in artists:
            conn.execute(
                """
                INSERT INTO artists(
                    id,
                    shop_id,
                    name,
                    styles,
                    services
                )
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    artist_id,
                    shop_id,
                    name,
                    styles,
                    services,
                ),
            )

        customers = [
            (
                "cust_sarah",
                "Sarah Miller",
                "+15555550101",
                "artist_alex",
                "traditional",
                "tattoo",
                8,
                7,
                0,
            ),
            (
                "cust_mike",
                "Mike Rivera",
                "+15555550102",
                "artist_alex",
                "traditional",
                "tattoo",
                5,
                5,
                0,
            ),
            (
                "cust_jess",
                "Jessica Lee",
                "+15555550103",
                "artist_jordan",
                "blackwork",
                "tattoo",
                3,
                3,
                0,
            ),
            (
                "cust_taylor",
                "Taylor Smith",
                "+15555550104",
                "artist_alex,artist_jordan",
                "traditional,blackwork",
                "tattoo",
                2,
                2,
                0,
            ),
        ]

        for row in customers:
            (
                customer_id,
                name,
                phone,
                preferred_artists,
                preferred_styles,
                preferred_services,
                appointments,
                completed_count,
                cancellations,
            ) = row

            conn.execute(
                """
                INSERT INTO customers(
                    id,
                    shop_id,
                    name,
                    phone,
                    communication_consent,
                    preferred_artists,
                    preferred_styles,
                    preferred_services,
                    appointment_count,
                    completed_count,
                    cancellation_count,
                    created_at,
                    updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    customer_id,
                    shop_id,
                    name,
                    phone,
                    1,
                    preferred_artists,
                    preferred_styles,
                    preferred_services,
                    appointments,
                    completed_count,
                    cancellations,
                    now_iso(),
                    now_iso(),
                ),
            )

        conn.commit()

    conn.close()

    return RedirectResponse(
        "/",
        status_code=303,
    )


@app.post("/openings")
def create_opening(
    artist_id: str = Form(...),
    date: str = Form(...),
    start_time: str = Form(...),
    service: str = Form(...),
    style: str = Form(""),
    price: float = Form(...),
):
    conn = connect()

    artist = conn.execute(
        """
        SELECT *
        FROM artists
        WHERE id = ?
        """,
        (artist_id,),
    ).fetchone()

    if not artist:
        conn.close()
        raise HTTPException(
            404,
            "Artist not found",
        )

    opening_id = (
        f"opening_{uuid.uuid4().hex[:12]}"
    )

    expires_at = (
        datetime.now(timezone.utc)
        + timedelta(hours=24)
    )

    conn.execute(
        """
        INSERT INTO openings(
            id,
            shop_id,
            artist_id,
            date,
            start_time,
            service,
            style,
            price,
            status,
            created_at,
            expires_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            opening_id,
            artist["shop_id"],
            artist_id,
            date,
            start_time,
            service,
            style,
            price,
            "OPEN",
            now_iso(),
            expires_at.isoformat(),
        ),
    )

    conn.commit()
    conn.close()

    event(
        "opening.created",
        "opening",
        opening_id,
    )

    return RedirectResponse(
        f"/openings/{opening_id}",
        status_code=303,
    )


@app.get(
    "/openings/{opening_id}",
    response_class=HTMLResponse,
)
def opening_page(
    request: Request,
    opening_id: str,
):
    conn = connect()

    opening = conn.execute(
        """
        SELECT
            o.*,
            a.name AS artist_name
        FROM openings o
        JOIN artists a
            ON a.id = o.artist_id
        WHERE o.id = ?
        """,
        (opening_id,),
    ).fetchone()

    offers = conn.execute(
        """
        SELECT
            o.*,
            c.name AS customer_name,
            c.phone AS customer_phone
        FROM offers o
        JOIN customers c
            ON c.id = o.customer_id
        WHERE o.opening_id = ?
        ORDER BY o.rank
        """,
        (opening_id,),
    ).fetchall()

    conn.close()

    if not opening:
        raise HTTPException(
            404,
            "Opening not found",
        )

    return templates.TemplateResponse(
        "opening.html",
        {
            "request": request,
            "opening": opening,
            "offers": offers,
        },
    )


@app.post("/openings/{opening_id}/recover")
def start_recovery(opening_id: str):
    conn = connect()

    opening = conn.execute(
        """
        SELECT *
        FROM openings
        WHERE id = ?
        """,
        (opening_id,),
    ).fetchone()

    if not opening:
        conn.close()
        raise HTTPException(
            404,
            "Opening not found",
        )

    if opening["status"] not in (
        "OPEN",
        "RECOVERY_ACTIVE",
    ):
        conn.close()
        raise HTTPException(
            400,
            "Opening is not available for recovery",
        )

    customers = conn.execute(
        """
        SELECT *
        FROM customers
        WHERE shop_id = ?
          AND communication_consent = 1
        ORDER BY completed_count DESC
        """,
        (opening["shop_id"],),
    ).fetchall()

    scored = []

    for customer in customers:
        if customer["last_offer_at"]:
            try:
                last = datetime.fromisoformat(
                    customer["last_offer_at"]
                )

                if (
                    datetime.now(timezone.utc) - last
                    < timedelta(hours=24)
                ):
                    continue

            except ValueError:
                pass

        score = recovery_score(
            customer,
            opening,
        )

        scored.append(
            (
                score,
                customer,
            )
        )

    scored.sort(
        key=lambda x: x[0],
        reverse=True,
    )

    selected = scored[:5]

    conn.execute(
        """
        UPDATE openings
        SET status = 'RECOVERY_ACTIVE'
        WHERE id = ?
        """,
        (opening_id,),
    )

    for rank, (
        score,
        customer,
    ) in enumerate(
        selected,
        start=1,
    ):
        offer_id = (
            f"offer_{uuid.uuid4().hex[:12]}"
        )

        expires_at = (
            datetime.now(timezone.utc)
            + timedelta(minutes=30)
        )

        conn.execute(
            """
            INSERT INTO offers(
                id,
                opening_id,
                customer_id,
                score,
                rank,
                channel,
                expires_at,
                status
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                offer_id,
                opening_id,
                customer["id"],
                score,
                rank,
                "sms",
                expires_at.isoformat(),
                "PENDING",
            ),
        )

    conn.commit()

    offers = conn.execute(
        """
        SELECT
            o.*,
            c.name AS customer_name
        FROM offers o
        JOIN customers c
            ON c.id = o.customer_id
        WHERE o.opening_id = ?
        ORDER BY o.rank
        """,
        (opening_id,),
    ).fetchall()

    conn.close()

    for offer in offers:
        conn2 = connect()

        customer = conn2.execute(
            """
            SELECT *
            FROM customers
            WHERE id = ?
            """,
            (offer["customer_id"],),
        ).fetchone()

        opening_row = conn2.execute(
            """
            SELECT *
            FROM openings
            WHERE id = ?
            """,
            (opening_id,),
        ).fetchone()

        conn2.execute(
            """
            UPDATE offers
            SET
                status = 'SENT',
                sent_at = ?
            WHERE id = ?
            """,
            (
                now_iso(),
                offer["id"],
            ),
        )

        conn2.execute(
            """
            UPDATE customers
            SET
                last_offer_at = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (
                now_iso(),
                now_iso(),
                customer["id"],
            ),
        )

        conn2.commit()
        conn2.close()

        try:
            send_sms(
                customer,
                opening_row,
                offer["id"],
            )

            event(
                "offer.sent",
                "offer",
                offer["id"],
            )

        except Exception as exc:
            event(
                "offer.send_failed",
                "offer",
                offer["id"],
                str(exc),
            )

    event(
        "recovery.started",
        "opening",
        opening_id,
    )

    return RedirectResponse(
        f"/openings/{opening_id}",
        status_code=303,
    )


@app.get(
    "/offer/{offer_id}",
    response_class=HTMLResponse,
)
def offer_page(
    request: Request,
    offer_id: str,
):
    conn = connect()

    offer = conn.execute(
        """
        SELECT
            o.*,
            c.name AS customer_name,
            op.date,
            op.start_time,
            op.end_time,
            op.service,
            op.style,
            op.price,
            op.status AS opening_status,
            a.name AS artist_name,
            s.booking_url
        FROM offers o
        JOIN customers c
            ON c.id = o.customer_id
        JOIN openings op
            ON op.id = o.opening_id
        JOIN artists a
            ON a.id = op.artist_id
        JOIN shops s
            ON s.id = op.shop_id
        WHERE o.id = ?
        """,
        (offer_id,),
    ).fetchone()

    if not offer:
        conn.close()
        raise HTTPException(
            404,
            "Offer not found",
        )

    if not offer["opened_at"]:
        conn.execute(
            """
            UPDATE offers
            SET opened_at = ?
            WHERE id = ?
            """,
            (
                now_iso(),
                offer_id,
            ),
        )

        conn.commit()

        event(
            "offer.opened",
            "offer",
            offer_id,
        )

    conn.close()

    return templates.TemplateResponse(
        "offer.html",
        {
            "request": request,
            "offer": offer,
        },
    )


@app.post("/offer/{offer_id}/claim")
def claim_offer(offer_id: str):
    conn = connect()

    offer = conn.execute(
        """
        SELECT
            o.*,
            op.status AS opening_status,
            op.booking_id,
            op.shop_id,
            op.artist_id,
            op.price
        FROM offers o
        JOIN openings op
            ON op.id = o.opening_id
        WHERE o.id = ?
        """,
        (offer_id,),
    ).fetchone()

    if not offer:
        conn.close()
        raise HTTPException(
            404,
            "Offer not found",
        )

    if offer["status"] in (
        "CLAIMED",
        "EXPIRED",
        "CANCELLED",
        "DECLINED",
    ):
        conn.close()

        raise HTTPException(
            400,
            "This offer is no longer available.",
        )

    if offer["opening_status"] not in (
        "OPEN",
        "RECOVERY_ACTIVE",
    ):
        conn.close()

        raise HTTPException(
            400,
            "This opening is no longer available.",
        )

    conn.execute(
        """
        UPDATE offers
        SET
            status = 'CLAIMED',
            claimed_at = ?,
            responded_at = ?
        WHERE id = ?
        """,
        (
            now_iso(),
            now_iso(),
            offer_id,
        ),
    )

    conn.execute(
        """
        UPDATE openings
        SET status = 'CLAIMED'
        WHERE id = ?
        """,
        (offer["opening_id"],),
    )

    conn.execute(
        """
        UPDATE offers
        SET status = 'CANCELLED'
        WHERE opening_id = ?
          AND id != ?
          AND status IN (
              'PENDING',
              'SENT',
              'OPENED'
          )
        """,
        (
            offer["opening_id"],
            offer_id,
        ),
    )

    booking_id = (
        f"booking_{uuid.uuid4().hex[:12]}"
    )

    conn.execute(
        """
        INSERT INTO bookings(
            id,
            opening_id,
            customer_id,
            artist_id,
            booking_url,
            status,
            amount,
            booked_at
        )
        SELECT
            ?,
            o.id,
            ?,
            o.artist_id,
            s.booking_url,
            'PENDING',
            o.price,
            ?
        FROM openings o
        JOIN shops s
            ON s.id = o.shop_id
        WHERE o.id = ?
        """,
        (
            booking_id,
            offer["customer_id"],
            now_iso(),
            offer["opening_id"],
        ),
    )

    conn.execute(
        """
        UPDATE openings
        SET booking_id = ?
        WHERE id = ?
        """,
        (
            booking_id,
            offer["opening_id"],
        ),
    )

    conn.commit()
    conn.close()

    event(
        "offer.claimed",
        "offer",
        offer_id,
    )

    event(
        "booking.created",
        "booking",
        booking_id,
    )

    return RedirectResponse(
        f"/booking/{booking_id}",
        status_code=303,
    )


@app.post("/offer/{offer_id}/decline")
def decline_offer(
    offer_id: str,
    reason: str = Form("skip"),
):
    conn = connect()

    offer = conn.execute(
        """
        SELECT *
        FROM offers
        WHERE id = ?
        """,
        (offer_id,),
    ).fetchone()

    if not offer:
        conn.close()
        raise HTTPException(
            404,
            "Offer not found",
        )

    conn.execute(
        """
        UPDATE offers
        SET
            status = 'DECLINED',
            declined_at = ?,
            responded_at = ?,
            decline_reason = ?
        WHERE id = ?
        """,
        (
            now_iso(),
            now_iso(),
            reason,
            offer_id,
        ),
    )

    conn.commit()
    conn.close()

    event(
        "offer.declined",
        "offer",
        offer_id,
        reason,
    )

    return RedirectResponse(
        f"/offer/{offer_id}",
        status_code=303,
    )


@app.get(
    "/booking/{booking_id}",
    response_class=HTMLResponse,
)
def booking_page(
    request: Request,
    booking_id: str,
):
    conn = connect()

    booking = conn.execute(
        """
        SELECT
            b.*,
            c.name AS customer_name,
            o.date,
            o.start_time,
            o.service,
            o.style,
            a.name AS artist_name
        FROM bookings b
        JOIN customers c
            ON c.id = b.customer_id
        JOIN openings o
            ON o.id = b.opening_id
        JOIN artists a
            ON a.id = b.artist_id
        WHERE b.id = ?
        """,
        (booking_id,),
    ).fetchone()

    conn.close()

    if not booking:
        raise HTTPException(
            404,
            "Booking not found",
        )

    return templates.TemplateResponse(
        "booking.html",
        {
            "request": request,
            "booking": booking,
        },
    )


@app.post("/bookings/{booking_id}/confirm")
def confirm_booking(booking_id: str):
    conn = connect()

    booking = conn.execute(
        """
        SELECT *
        FROM bookings
        WHERE id = ?
        """,
        (booking_id,),
    ).fetchone()

    if not booking:
        conn.close()
        raise HTTPException(
            404,
            "Booking not found",
        )

    conn.execute(
        """
        UPDATE bookings
        SET
            status = 'CONFIRMED',
            booked_at = ?
        WHERE id = ?
        """,
        (
            now_iso(),
            booking_id,
        ),
    )

    conn.execute(
        """
        UPDATE openings
        SET status = 'BOOKED'
        WHERE id = ?
        """,
        (booking["opening_id"],),
    )

    conn.commit()
    conn.close()

    event(
        "booking.confirmed",
        "booking",
        booking_id,
    )

    return RedirectResponse(
        f"/booking/{booking_id}",
        status_code=303,
    )


@app.post("/bookings/{booking_id}/complete")
def complete_booking(booking_id: str):
    conn = connect()

    booking = conn.execute(
        """
        SELECT *
        FROM bookings
        WHERE id = ?
        """,
        (booking_id,),
    ).fetchone()

    if not booking:
        conn.close()
        raise HTTPException(
            404,
            "Booking not found",
        )

    conn.execute(
        """
        UPDATE bookings
        SET
            status = 'COMPLETED',
            completed_at = ?
        WHERE id = ?
        """,
        (
            now_iso(),
            booking_id,
        ),
    )

    conn.execute(
        """
        UPDATE openings
        SET status = 'COMPLETED'
        WHERE id = ?
        """,
        (booking["opening_id"],),
    )

    conn.execute(
        """
        UPDATE customers
        SET
            completed_count = completed_count + 1,
            appointment_count = appointment_count + 1,
            average_spend =
                (
                    (average_spend * completed_count)
                    + ?
                )
                /
                (completed_count + 1),
            last_appointment_at = ?,
            updated_at = ?
        WHERE id = ?
        """,
        (
            booking["amount"],
            now_iso(),
            now_iso(),
            booking["customer_id"],
        ),
    )

    conn.commit()
    conn.close()

    event(
        "booking.completed",
        "booking",
        booking_id,
    )

    event(
        "appointment.completed",
        "booking",
        booking_id,
    )

    return RedirectResponse(
        "/",
        status_code=303,
    )


@app.get("/debug/offer/{offer_id}")
def debug_offer(offer_id: str):
    conn = connect()

    offer = conn.execute(
        """
        SELECT
            o.id AS offer_id,
            o.status AS offer_status,
            o.expires_at AS offer_expires_at,
            o.sent_at,
            o.opened_at,
            o.claimed_at,
            o.declined_at,
            o.opening_id,
            o.customer_id,
            op.status AS opening_status,
            op.date AS opening_date,
            op.start_time AS opening_start_time,
            c.name AS customer_name
        FROM offers o
        JOIN openings op
            ON op.id = o.opening_id
        JOIN customers c
            ON c.id = o.customer_id
        WHERE o.id = ?
        """,
        (offer_id,),
    ).fetchone()

    conn.close()

    if not offer:
        raise HTTPException(
            404,
            "Offer not found",
        )

    result = dict(offer)

    now = datetime.now(timezone.utc)

    try:
        expires_at = datetime.fromisoformat(
            result["offer_expires_at"]
        )

        result["current_time_utc"] = now.isoformat()
        result["is_expired"] = now >= expires_at

    except (
        ValueError,
        TypeError,
    ):
        result["current_time_utc"] = now.isoformat()
        result["is_expired"] = "unable to determine"

    return result


@app.get("/health")
def health():
    return {
        "status": "ok",
        "demo_mode": DEMO_MODE,
        "base_url": PUBLIC_BASE_URL,
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
    )
