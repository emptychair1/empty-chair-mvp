import os
import csv
import io
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import (
    FastAPI,
    Form,
    HTTPException,
    Request,
    UploadFile,
    File,
)
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from twilio.rest import Client


# ============================================================
# CONFIGURATION
# ============================================================

DATABASE_URL = os.getenv("DATABASE_URL")

DB_PATH = os.getenv(
    "EMPTY_CHAIR_DB",
    "empty_chair.db",
)

PUBLIC_BASE_URL = os.getenv(
    "EMPTY_CHAIR_BASE_URL",
    "http://localhost:8000",
)

DEMO_MODE = (
    os.getenv(
        "EMPTY_CHAIR_DEMO_MODE",
        "true",
    ).lower()
    == "true"
)

TWILIO_ACCOUNT_SID = os.getenv(
    "TWILIO_ACCOUNT_SID"
)

TWILIO_AUTH_TOKEN = os.getenv(
    "TWILIO_AUTH_TOKEN"
)

TWILIO_FROM_NUMBER = os.getenv(
    "TWILIO_FROM_NUMBER"
)


# ============================================================
# DATABASE CONFIGURATION
# ============================================================

USE_POSTGRES = bool(DATABASE_URL)

if USE_POSTGRES:
    try:
        import psycopg2
        from psycopg2.extras import RealDictCursor
    except ImportError as exc:
        raise RuntimeError(
            "PostgreSQL is configured but psycopg2-binary "
            "is not installed. Add psycopg2-binary to "
            "requirements.txt."
        ) from exc


def connect():
    """
    Use PostgreSQL when DATABASE_URL exists.
    Otherwise use local SQLite.
    """

    if USE_POSTGRES:
        database_url = DATABASE_URL

        if database_url.startswith("postgres://"):
            database_url = database_url.replace(
                "postgres://",
                "postgresql://",
                1,
            )

        return psycopg2.connect(
            database_url,
            cursor_factory=RealDictCursor,
            sslmode="require",
        )

    conn = sqlite3.connect(DB_PATH)

    conn.row_factory = sqlite3.Row

    conn.execute(
        "PRAGMA foreign_keys = ON"
    )

    return conn


def db_execute(
    conn,
    query,
    params=(),
):
    """
    Application SQL uses ? placeholders.
    PostgreSQL requires %s.
    """

    if USE_POSTGRES:
        query = query.replace("?", "%s")

    cursor = conn.cursor()

    cursor.execute(
        query,
        params,
    )

    return cursor


def db_fetchone(
    conn,
    query,
    params=(),
):
    cursor = db_execute(
        conn,
        query,
        params,
    )

    return cursor.fetchone()


def db_fetchall(
    conn,
    query,
    params=(),
):
    cursor = db_execute(
        conn,
        query,
        params,
    )

    return cursor.fetchall()


# ============================================================
# DATABASE SCHEMA
# ============================================================

def init_db():
    conn = connect()

    if USE_POSTGRES:

        schema = """
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
            id BIGSERIAL PRIMARY KEY,
            event_type TEXT NOT NULL,
            entity_type TEXT NOT NULL,
            entity_id TEXT NOT NULL,
            metadata TEXT,
            created_at TEXT NOT NULL
        );
        """

    else:

        schema = """
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

    cursor = conn.cursor()
    cursor.execute(schema)

    conn.commit()
    conn.close()


# ============================================================
# HELPERS
# ============================================================

def now_iso():
    return datetime.now(
        timezone.utc
    ).isoformat()


def event(
    event_type,
    entity_type,
    entity_id,
    metadata="",
):
    conn = connect()

    db_execute(
        conn,
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


def recovery_score(
    customer,
    opening,
):
    score = 0

    artist_prefs = csv_values(
        customer["preferred_artists"]
    )

    style_prefs = csv_values(
        customer["preferred_styles"]
    )

    service_prefs = csv_values(
        customer["preferred_services"]
    )

    if (
        opening["artist_id"].lower()
        in artist_prefs
    ):
        score += 30

    if (
        (opening["style"] or "").lower()
        in style_prefs
    ):
        score += 25

    if (
        opening["service"].lower()
        in service_prefs
    ):
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

            if (
                datetime.now(timezone.utc)
                - last
                < timedelta(days=30)
            ):
                score -= 5

        except ValueError:
            pass

    return max(
        0,
        min(
            100,
            score,
        ),
    )


# ============================================================
# SMS
# ============================================================

def send_sms(
    customer,
    opening,
    offer_id,
):
    claim_url = (
        f"{PUBLIC_BASE_URL.rstrip('/')}"
        f"/offer/{offer_id}"
    )

    message = (
        f"Hey {customer['name'].split()[0]} — "
        f"{opening['style'] or 'Tattoo'} opening "
        f"with {opening.get('artist_name', 'your artist')} "
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
            "Twilio is not configured and "
            "DEMO_MODE is false."
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


# ============================================================
# SEQUENTIAL RECOVERY ENGINE
# ============================================================

def activate_next_offer(opening_id):
    """
    Find the next PENDING offer for an opening,
    activate it, and send the SMS.

    Only ONE offer can be active at a time.
    """

    conn = connect()

    opening = db_fetchone(
        conn,
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
    )

    if not opening:

        conn.close()
        return None

    # Do not send another offer if the opening
    # has already been claimed/booked/completed.
    if opening["status"] not in (
        "OPEN",
        "RECOVERY_ACTIVE",
    ):
        conn.close()
        return None

    # Check whether another offer is already active.
    active_offer = db_fetchone(
        conn,
        """
        SELECT *
        FROM offers
        WHERE opening_id = ?
          AND status = 'SENT'
        ORDER BY rank
        LIMIT 1
        """,
        (opening_id,),
    )

    if active_offer:

        # If it has expired, mark it expired and
        # continue to the next customer.
        try:
            expires_at = datetime.fromisoformat(
                active_offer["expires_at"]
            )

            if (
                datetime.now(timezone.utc)
                >= expires_at
            ):

                db_execute(
                    conn,
                    """
                    UPDATE offers
                    SET status = 'EXPIRED'
                    WHERE id = ?
                    """,
                    (active_offer["id"],),
                )

                db_execute(
                    conn,
                    """
                    UPDATE offers
                    SET responded_at = ?
                    WHERE id = ?
                    """,
                    (
                        now_iso(),
                        active_offer["id"],
                    ),
                )

                conn.commit()

            else:
                conn.close()
                return active_offer

        except ValueError:
            conn.close()
            return active_offer

    # Find the next customer in sequence.
    next_offer = db_fetchone(
        conn,
        """
        SELECT *
        FROM offers
        WHERE opening_id = ?
          AND status = 'PENDING'
        ORDER BY rank ASC
        LIMIT 1
        """,
        (opening_id,),
    )

    if not next_offer:

        db_execute(
            conn,
            """
            UPDATE openings
            SET status = 'NO_RECOVERY'
            WHERE id = ?
            """,
            (opening_id,),
        )

        conn.commit()
        conn.close()

        event(
            "recovery.exhausted",
            "opening",
            opening_id,
        )

        return None

    expires_at = (
        datetime.now(timezone.utc)
        + timedelta(minutes=30)
    )

    timestamp = now_iso()

    db_execute(
        conn,
        """
        UPDATE offers
        SET
            status = 'SENT',
            sent_at = ?,
            expires_at = ?
        WHERE id = ?
        """,
        (
            timestamp,
            expires_at.isoformat(),
            next_offer["id"],
        ),
    )

    db_execute(
        conn,
        """
        UPDATE customers
        SET
            last_offer_at = ?,
            updated_at = ?
        WHERE id = ?
        """,
        (
            timestamp,
            timestamp,
            next_offer["customer_id"],
        ),
    )

    db_execute(
        conn,
        """
        UPDATE openings
        SET status = 'RECOVERY_ACTIVE'
        WHERE id = ?
        """,
        (opening_id,),
    )

    customer = db_fetchone(
        conn,
        """
        SELECT *
        FROM customers
        WHERE id = ?
        """,
        (next_offer["customer_id"],),
    )

    conn.commit()
    conn.close()

    # Send only this one customer the SMS.
    try:

        send_sms(
            customer,
            opening,
            next_offer["id"],
        )

        event(
            "offer.sent",
            "offer",
            next_offer["id"],
        )

    except Exception as exc:

        event(
            "offer.send_failed",
            "offer",
            next_offer["id"],
            str(exc),
        )

    return next_offer


def expire_current_and_advance(opening_id):
    """
    If the active offer has expired, mark it expired
    and immediately send the next offer.
    """

    conn = connect()

    active = db_fetchone(
        conn,
        """
        SELECT *
        FROM offers
        WHERE opening_id = ?
          AND status = 'SENT'
        ORDER BY rank
        LIMIT 1
        """,
        (opening_id,),
    )

    if not active:
        conn.close()
        return activate_next_offer(opening_id)

    try:
        expires_at = datetime.fromisoformat(
            active["expires_at"]
        )
    except ValueError:
        conn.close()
        return active

    if datetime.now(timezone.utc) < expires_at:
        conn.close()
        return active

    db_execute(
        conn,
        """
        UPDATE offers
        SET
            status = 'EXPIRED',
            responded_at = ?
        WHERE id = ?
        """,
        (
            now_iso(),
            active["id"],
        ),
    )

    conn.commit()
    conn.close()

    event(
        "offer.expired",
        "offer",
        active["id"],
    )

    return activate_next_offer(opening_id)


# ============================================================
# DEMO DATA
# ============================================================

def ensure_demo_data():
    """
    Create demo data if the database is empty.
    """

    conn = connect()

    shop = db_fetchone(
        conn,
        """
        SELECT id
        FROM shops
        LIMIT 1
        """,
    )

    if shop:
        conn.close()
        return

    shop_id = "shop_demo"

    db_execute(
        conn,
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

        db_execute(
            conn,
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
            completed,
            cancellations,
        ) = row

        timestamp = now_iso()

        db_execute(
            conn,
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
            VALUES(
                ?, ?, ?, ?, ?, ?, ?, ?,
                ?, ?, ?, ?, ?
            )
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
                completed,
                cancellations,
                timestamp,
                timestamp,
            ),
        )

    conn.commit()
    conn.close()


# ============================================================
# APP
# ============================================================

app = FastAPI(
    title="Empty Chair",
    version="0.4.0",
)

templates = Jinja2Templates(
    directory="templates"
)


# ============================================================
# STARTUP
# ============================================================

@app.on_event("startup")
def startup():

    init_db()

    ensure_demo_data()


# ============================================================
# DASHBOARD
# ============================================================

@app.get(
    "/",
    response_class=HTMLResponse,
)
def dashboard(
    request: Request,
):

    conn = connect()

    shop = db_fetchone(
        conn,
        """
        SELECT *
        FROM shops
        ORDER BY created_at
        LIMIT 1
        """,
    )

    artists = db_fetchall(
        conn,
        """
        SELECT *
        FROM artists
        WHERE active = 1
        ORDER BY name
        """,
    )

    openings = db_fetchall(
        conn,
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
        """,
    )

    recovered_row = db_fetchone(
        conn,
        """
        SELECT
            COALESCE(
                SUM(amount),
                0
            ) AS total
        FROM bookings
        WHERE status = 'COMPLETED'
        """,
    )

    completed_row = db_fetchone(
        conn,
        """
        SELECT COUNT(*) AS n
        FROM bookings
        WHERE status = 'COMPLETED'
        """,
    )

    total_openings_row = db_fetchone(
        conn,
        """
        SELECT COUNT(*) AS n
        FROM openings
        """,
    )

    customer_count_row = db_fetchone(
        conn,
        """
        SELECT COUNT(*) AS n
        FROM customers
        """,
    )

    active_recovery_row = db_fetchone(
        conn,
        """
        SELECT COUNT(*) AS n
        FROM openings
        WHERE status = 'RECOVERY_ACTIVE'
        """,
    )

    recovered = (
        recovered_row["total"]
        if recovered_row
        else 0
    )

    completed = (
        completed_row["n"]
        if completed_row
        else 0
    )

    total_openings = (
        total_openings_row["n"]
        if total_openings_row
        else 0
    )

    customer_count = (
        customer_count_row["n"]
        if customer_count_row
        else 0
    )

    active_recovery = (
        active_recovery_row["n"]
        if active_recovery_row
        else 0
    )

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
            "customer_count": customer_count,
            "active_recovery": active_recovery,
        },
    )


# ============================================================
# CUSTOMER IMPORT PAGE
# ============================================================

@app.get(
    "/import/customers",
    response_class=HTMLResponse,
)
def customer_import_page():

    database_type = (
        "PostgreSQL"
        if USE_POSTGRES
        else "SQLite"
    )

    return HTMLResponse(
        f"""
<!doctype html>
<html>
<head>

<meta charset="utf-8">

<meta
    name="viewport"
    content="width=device-width, initial-scale=1"
>

<title>Import Customers · Empty Chair</title>

<style>

body {{
    font-family:
        Inter,
        system-ui,
        -apple-system,
        sans-serif;

    max-width: 720px;

    margin: 0 auto;

    padding: 32px;

    background: #f7f7f5;

    color: #161616;
}}

.card {{
    background: white;

    border: 1px solid #ddd;

    border-radius: 16px;

    padding: 28px;
}}

h1 {{
    margin-top: 0;
}}

.notice {{
    background: #eef6ff;

    border: 1px solid #c9def5;

    padding: 14px;

    border-radius: 10px;

    margin: 18px 0;
}}

.warning {{
    background: #fff4d6;

    border: 1px solid #ead28b;

    padding: 14px;

    border-radius: 10px;

    margin: 18px 0;
}}

input[type=file] {{
    width: 100%;

    padding: 12px;

    border: 1px solid #bbb;

    border-radius: 9px;

    background: white;

    box-sizing: border-box;
}}

button {{
    background: #111;

    color: white;

    border: 0;

    border-radius: 9px;

    padding: 13px 18px;

    cursor: pointer;

    font-size: 15px;

    margin-top: 15px;
}}

code {{
    background: #f1f1f1;

    padding: 3px 5px;

    border-radius: 5px;
}}

a {{
    color: #111;
}}

</style>

</head>

<body>

<div class="card">

<h1>Import Customers</h1>

<p>
Import your customer history into Empty Chair.
</p>

<div class="notice">
<strong>Database:</strong>
{database_type}
</div>

<div class="warning">
<strong>SMS consent matters.</strong>
<br>
Only import customers who have consented to receiving
SMS communications from the shop.
</div>

<h2>CSV columns</h2>

<p>
Your CSV should contain:
</p>

<p>
<code>name</code>,
<code>phone</code>,
<code>email</code>,
<code>communication_consent</code>,
<code>preferred_artists</code>,
<code>preferred_styles</code>,
<code>preferred_services</code>,
<code>appointment_count</code>,
<code>completed_count</code>,
<code>cancellation_count</code>
</p>

<p>
Optional:
<code>id</code>
</p>

<h2>Upload CSV</h2>

<form
    method="post"
    action="/import/customers"
    enctype="multipart/form-data"
>

<input
    type="file"
    name="file"
    accept=".csv,text/csv"
    required
>

<button type="submit">
Import Customers
</button>

</form>

<p style="margin-top:25px;">
<a href="/">← Back to dashboard</a>
</p>

</div>

</body>
</html>
"""
    )


# ============================================================
# CUSTOMER CSV IMPORT
# ============================================================

@app.post(
    "/import/customers",
    response_class=HTMLResponse,
)
async def import_customers(
    file: UploadFile = File(...),
):

    if not file.filename:
        raise HTTPException(
            400,
            "No CSV file selected.",
        )

    if not file.filename.lower().endswith(
        ".csv"
    ):
        raise HTTPException(
            400,
            "Please upload a CSV file.",
        )

    raw_data = await file.read()

    try:
        text = raw_data.decode(
            "utf-8-sig"
        )
    except UnicodeDecodeError as exc:
        raise HTTPException(
            400,
            "CSV must be UTF-8 encoded.",
        ) from exc

    reader = csv.DictReader(
        io.StringIO(text)
    )

    if not reader.fieldnames:
        raise HTTPException(
            400,
            "CSV has no header row.",
        )

    headers = {
        h.strip().lower()
        for h in reader.fieldnames
        if h
    }

    required_headers = {
        "name",
        "phone",
    }

    missing = (
        required_headers - headers
    )

    if missing:
        raise HTTPException(
            400,
            "Missing required columns: "
            + ", ".join(
                sorted(missing)
            ),
        )

    conn = connect()

    shop = db_fetchone(
        conn,
        """
        SELECT id
        FROM shops
        ORDER BY created_at
        LIMIT 1
        """,
    )

    if not shop:

        conn.close()

        return HTMLResponse(
            """
<!doctype html>
<html>
<body>

<h1>No shop configured</h1>

<p>
No shop exists in the database.
</p>

<p>
<a href="/">
Back to dashboard
</a>
</p>

</body>
</html>
""",
            status_code=400,
        )

    shop_id = shop["id"]

    imported = 0
    updated = 0
    skipped = 0
    errors = []

    for (
        row_number,
        raw_row,
    ) in enumerate(
        reader,
        start=2,
    ):

        try:

            row = {
                (key or "").strip().lower():
                (value or "").strip()
                for key, value
                in raw_row.items()
            }

            name = row.get(
                "name",
                "",
            ).strip()

            phone = row.get(
                "phone",
                "",
            ).strip()

            if not name or not phone:

                skipped += 1

                errors.append(
                    f"Row {row_number}: "
                    "name and phone are required."
                )

                continue

            customer_id = (
                row.get(
                    "id",
                    "",
                ).strip()
                or
                f"cust_{uuid.uuid4().hex[:12]}"
            )

            email = (
                row.get(
                    "email",
                    "",
                ).strip()
                or None
            )

            consent_value = (
                row.get(
                    "communication_consent",
                    "0",
                )
                .strip()
                .lower()
            )

            communication_consent = (
                1
                if consent_value
                in {
                    "1",
                    "true",
                    "yes",
                    "y",
                    "on",
                }
                else 0
            )

            preferred_artists = row.get(
                "preferred_artists",
                "",
            )

            preferred_styles = row.get(
                "preferred_styles",
                "",
            )

            preferred_services = (
                row.get(
                    "preferred_services",
                    "tattoo",
                )
                or "tattoo"
            )

            appointment_count = int(
                row.get(
                    "appointment_count",
                    "0",
                )
                or 0
            )

            completed_count = int(
                row.get(
                    "completed_count",
                    "0",
                )
                or 0
            )

            cancellation_count = int(
                row.get(
                    "cancellation_count",
                    "0",
                )
                or 0
            )

            timestamp = now_iso()

            existing = db_fetchone(
                conn,
                """
                SELECT id
                FROM customers
                WHERE id = ?
                   OR (
                        shop_id = ?
                        AND phone = ?
                   )
                LIMIT 1
                """,
                (
                    customer_id,
                    shop_id,
                    phone,
                ),
            )

            if existing:

                db_execute(
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
                        updated_at = ?
                    WHERE id = ?
                    """,
                    (
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
                        timestamp,
                        existing["id"],
                    ),
                )

                updated += 1

            else:

                db_execute(
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
                        created_at,
                        updated_at
                    )
                    VALUES(
                        ?, ?, ?, ?, ?, ?, ?, ?, ?,
                        ?, ?, ?, ?, ?
                    )
                    """,
                    (
                        customer_id,
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
                        timestamp,
                        timestamp,
                    ),
                )

                imported += 1

        except Exception as exc:

            skipped += 1

            errors.append(
                f"Row {row_number}: {str(exc)}"
            )

    conn.commit()
    conn.close()

    error_html = ""

    if errors:

        error_html = (
            "<h3>Rows needing attention</h3>"
            "<ul>"
            +
            "".join(
                f"<li>{error}</li>"
                for error in errors[:50]
            )
            +
            "</ul>"
        )

    return HTMLResponse(
        f"""
<!doctype html>
<html>

<head>

<meta charset="utf-8">

<meta
    name="viewport"
    content="width=device-width, initial-scale=1"
>

<title>Import Complete · Empty Chair</title>

<style>

body {{
    font-family:
        Inter,
        system-ui,
        -apple-system,
        sans-serif;

    max-width:
        720px;

    margin:
        0 auto;

    padding:
        32px;

    background:
        #f7f7f5;

    color:
        #161616;
}}

.card {{
    background:
        white;

    border:
        1px solid #ddd;

    border-radius:
        16px;

    padding:
        28px;
}}

.metric {{
    font-size:
        32px;

    font-weight:
        700;

    margin:
        8px 0 20px;
}}

button,
a {{
    background:
        #111;

    color:
        white;

    border:
        0;

    border-radius:
        9px;

    padding:
        12px 16px;

    text-decoration:
        none;

    display:
        inline-block;

    margin-top:
        10px;
}}

</style>

</head>

<body>

<div class="card">

<h1>Import complete</h1>

<p>
<strong>New customers:</strong>
</p>

<div class="metric">
{imported}
</div>

<p>
<strong>Updated customers:</strong>
</p>

<div class="metric">
{updated}
</div>

<p>
<strong>Skipped/error rows:</strong>
</p>

<div class="metric">
{skipped}
</div>

{error_html}

<a href="/import/customers">
Import another CSV
</a>

<a href="/">
Back to dashboard
</a>

</div>

</body>

</html>
"""
    )


# ============================================================
# DEMO SETUP
# ============================================================

@app.post("/demo/setup")
def demo_setup():

    ensure_demo_data()

    return RedirectResponse(
        "/",
        status_code=303,
    )


# ============================================================
# CREATE OPENING
# ============================================================

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

    artist = db_fetchone(
        conn,
        """
        SELECT *
        FROM artists
        WHERE id = ?
        """,
        (artist_id,),
    )

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

    db_execute(
        conn,
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
        VALUES(
            ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
        )
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


# ============================================================
# OPENING PAGE
# ============================================================

@app.get(
    "/openings/{opening_id}",
    response_class=HTMLResponse,
)
def opening_page(
    request: Request,
    opening_id: str,
):

    # Automatically advance a timed-out customer
    # before rendering the opening page.
    expire_current_and_advance(
        opening_id
    )

    conn = connect()

    opening = db_fetchone(
        conn,
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
    )

    offers = db_fetchall(
        conn,
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
    )

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


# ============================================================
# START SEQUENTIAL RECOVERY
# ============================================================

@app.post(
    "/openings/{opening_id}/recover"
)
def start_recovery(
    opening_id: str,
):

    conn = connect()

    opening = db_fetchone(
        conn,
        """
        SELECT *
        FROM openings
        WHERE id = ?
        """,
        (opening_id,),
    )

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

    # Prevent duplicate recovery campaigns.
    existing_offer = db_fetchone(
        conn,
        """
        SELECT id
        FROM offers
        WHERE opening_id = ?
        LIMIT 1
        """,
        (opening_id,),
    )

    if existing_offer:

        conn.close()

        # If there is already a campaign,
        # simply make sure the current customer
        # is active.
        activate_next_offer(
            opening_id
        )

        return RedirectResponse(
            f"/openings/{opening_id}",
            status_code=303,
        )

    customers = db_fetchall(
        conn,
        """
        SELECT *
        FROM customers
        WHERE shop_id = ?
          AND communication_consent = 1
        ORDER BY completed_count DESC
        """,
        (opening["shop_id"],),
    )

    scored = []

    for customer in customers:

        if customer["last_offer_at"]:

            try:

                last = datetime.fromisoformat(
                    customer["last_offer_at"]
                )

                if (
                    datetime.now(timezone.utc)
                    - last
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

    # Create the ranked queue.
    # IMPORTANT:
    # Every offer starts as PENDING.
    # Only activate_next_offer() sends #1.
    for rank, (
        score,
        customer,
    ) in enumerate(
        scored,
        start=1,
    ):

        offer_id = (
            f"offer_{uuid.uuid4().hex[:12]}"
        )

        expires_at = (
            datetime.now(timezone.utc)
            + timedelta(minutes=30)
        )

        db_execute(
            conn,
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
            VALUES(
                ?, ?, ?, ?, ?, ?, ?, ?
            )
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
    conn.close()

    event(
        "recovery.queue_created",
        "opening",
        opening_id,
        f"customers={len(scored)}",
    )

    # This sends ONLY rank #1.
    activate_next_offer(
        opening_id
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


# ============================================================
# OFFER PAGE
# ============================================================

@app.get(
    "/offer/{offer_id}",
    response_class=HTMLResponse,
)
def offer_page(
    request: Request,
    offer_id: str,
):

    conn = connect()

    offer = db_fetchone(
        conn,
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
            a.name AS artist_name,
            s.booking_url,
            op.status AS opening_status
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
    )

    if not offer:

        conn.close()

        raise HTTPException(
            404,
            "Offer not found",
        )

    opening_id = offer["opening_id"]

    conn.close()

    # If this offer has expired, advance the queue.
    if offer["status"] == "SENT":

        try:

            expires_at = datetime.fromisoformat(
                offer["expires_at"]
            )

            if datetime.now(timezone.utc) >= expires_at:

                expire_current_and_advance(
                    opening_id
                )

                conn = connect()

                offer = db_fetchone(
                    conn,
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
                        a.name AS artist_name,
                        s.booking_url,
                        op.status AS opening_status
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
                )

                conn.close()

        except ValueError:
            pass

    conn = connect()

    # Mark the current offer as opened.
    if offer and not offer["opened_at"]:

        db_execute(
            conn,
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


# ============================================================
# CLAIM OFFER
# ============================================================

@app.post(
    "/offer/{offer_id}/claim"
)
def claim_offer(
    offer_id: str,
):

    conn = connect()

    offer = db_fetchone(
        conn,
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
    )

    if not offer:

        conn.close()

        raise HTTPException(
            404,
            "Offer not found",
        )

    if offer["status"] != "SENT":

        conn.close()

        raise HTTPException(
            400,
            "This offer is no longer active.",
        )

    try:

        expires_at = datetime.fromisoformat(
            offer["expires_at"]
        )

        if datetime.now(timezone.utc) >= expires_at:

            conn.close()

            expire_current_and_advance(
                offer["opening_id"]
            )

            raise HTTPException(
                400,
                "This offer expired. "
                "The next customer has been contacted.",
            )

    except ValueError:
        pass

    if offer["opening_status"] not in (
        "OPEN",
        "RECOVERY_ACTIVE",
    ):

        conn.close()

        raise HTTPException(
            400,
            "This opening is no longer available.",
        )

    timestamp = now_iso()

    # The customer who claims wins the opening.
    db_execute(
        conn,
        """
        UPDATE offers
        SET
            status = 'CLAIMED',
            claimed_at = ?,
            responded_at = ?
        WHERE id = ?
        """,
        (
            timestamp,
            timestamp,
            offer_id,
        ),
    )

    db_execute(
        conn,
        """
        UPDATE openings
        SET status = 'CLAIMED'
        WHERE id = ?
        """,
        (offer["opening_id"],),
    )

    # Cancel everyone else in the queue.
    db_execute(
        conn,
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

    shop = db_fetchone(
        conn,
        """
        SELECT booking_url
        FROM shops
        WHERE id = ?
        """,
        (offer["shop_id"],),
    )

    booking_url = (
        shop["booking_url"]
        if shop
        else None
    )

    db_execute(
        conn,
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
        VALUES(
            ?, ?, ?, ?, ?, ?, ?, ?
        )
        """,
        (
            booking_id,
            offer["opening_id"],
            offer["customer_id"],
            offer["artist_id"],
            booking_url,
            "PENDING",
            offer["price"],
            now_iso(),
        ),
    )

    db_execute(
        conn,
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


# ============================================================
# DECLINE OFFER
# ============================================================

@app.post(
    "/offer/{offer_id}/decline"
)
def decline_offer(
    offer_id: str,
    reason: str = Form("skip"),
):

    conn = connect()

    offer = db_fetchone(
        conn,
        """
        SELECT *
        FROM offers
        WHERE id = ?
        """,
        (offer_id,),
    )

    if not offer:

        conn.close()

        raise HTTPException(
            404,
            "Offer not found",
        )

    if offer["status"] != "SENT":

        conn.close()

        raise HTTPException(
            400,
            "This offer is no longer active.",
        )

    timestamp = now_iso()

    db_execute(
        conn,
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
            timestamp,
            timestamp,
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

    # THIS IS THE KEY SEQUENTIAL STEP.
    # Only after the current customer declines
    # do we contact the next customer.
    activate_next_offer(
        offer["opening_id"]
    )

    return RedirectResponse(
        f"/offer/{offer_id}",
        status_code=303,
    )


# ============================================================
# BOOKING PAGE
# ============================================================

@app.get(
    "/booking/{booking_id}",
    response_class=HTMLResponse,
)
def booking_page(
    request: Request,
    booking_id: str,
):

    conn = connect()

    booking = db_fetchone(
        conn,
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
    )

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


# ============================================================
# CONFIRM BOOKING
# ============================================================

@app.post(
    "/bookings/{booking_id}/confirm"
)
def confirm_booking(
    booking_id: str,
):

    conn = connect()

    booking = db_fetchone(
        conn,
        """
        SELECT *
        FROM bookings
        WHERE id = ?
        """,
        (booking_id,),
    )

    if not booking:

        conn.close()

        raise HTTPException(
            404,
            "Booking not found",
        )

    db_execute(
        conn,
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

    db_execute(
        conn,
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


# ============================================================
# COMPLETE BOOKING
# ============================================================

@app.post(
    "/bookings/{booking_id}/complete"
)
def complete_booking(
    booking_id: str,
):

    conn = connect()

    booking = db_fetchone(
        conn,
        """
        SELECT *
        FROM bookings
        WHERE id = ?
        """,
        (booking_id,),
    )

    if not booking:

        conn.close()

        raise HTTPException(
            404,
            "Booking not found",
        )

    db_execute(
        conn,
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

    db_execute(
        conn,
        """
        UPDATE openings
        SET status = 'COMPLETED'
        WHERE id = ?
        """,
        (booking["opening_id"],),
    )

    customer = db_fetchone(
        conn,
        """
        SELECT *
        FROM customers
        WHERE id = ?
        """,
        (booking["customer_id"],),
    )

    if customer:

        old_completed = (
            customer["completed_count"]
            or 0
        )

        old_average = (
            customer["average_spend"]
            or 0
        )

        new_completed_count = (
            old_completed + 1
        )

        new_average_spend = (
            (
                old_average
                * old_completed
            )
            + booking["amount"]
        ) / new_completed_count

        timestamp = now_iso()

        db_execute(
            conn,
            """
            UPDATE customers
            SET
                completed_count = ?,
                appointment_count =
                    appointment_count + 1,
                average_spend = ?,
                last_appointment_at = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (
                new_completed_count,
                new_average_spend,
                timestamp,
                timestamp,
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


# ============================================================
# MANUALLY ADVANCE RECOVERY
# ============================================================

@app.post(
    "/openings/{opening_id}/advance"
)
def advance_recovery(
    opening_id: str,
):

    result = expire_current_and_advance(
        opening_id
    )

    return RedirectResponse(
        f"/openings/{opening_id}",
        status_code=303,
    )


# ============================================================
# HEALTH CHECK
# ============================================================

@app.get("/health")
def health():

    database_type = (
        "postgresql"
        if USE_POSTGRES
        else "sqlite"
    )

    try:

        conn = connect()

        db_fetchone(
            conn,
            "SELECT 1 AS ok",
        )

        conn.close()

        database_status = "connected"

    except Exception as exc:

        database_status = (
            f"error: {str(exc)}"
        )

    return {
        "status": "ok",
        "demo_mode": DEMO_MODE,
        "database": database_type,
        "database_status": database_status,
        "sequential_messaging": True,
    }


# ============================================================
# MAIN
# ============================================================

if __name__ == "__main__":

    import uvicorn

    uvicorn.run(
        "app:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
    )