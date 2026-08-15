import os
import base64
import csv
import io
import sqlite3
import uuid
import hashlib
import hmac
import json
import secrets
import resend
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

from fastapi import (
    FastAPI,
    File,
    Form,
    HTTPException,
    Request,
    UploadFile,
)
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from twilio.rest import Client
from starlette.middleware.sessions import SessionMiddleware


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

USE_POSTGRES = bool(DATABASE_URL)


SESSION_SECRET = os.getenv(
    "EMPTY_CHAIR_SESSION_SECRET",
    "change-me-in-production",
)

RESEND_API_KEY = os.getenv(
    "RESEND_API_KEY"
)

EMAIL_FROM = os.getenv(
    "EMPTY_CHAIR_EMAIL_FROM",
    "Empty Chair <onboarding@resend.dev>",
)

PASSWORD_RESET_MINUTES = int(
    os.getenv(
        "EMPTY_CHAIR_PASSWORD_RESET_MINUTES",
        "30",
    )
)


if USE_POSTGRES:
    try:
        import psycopg2
        from psycopg2.extras import RealDictCursor
    except ImportError as exc:
        raise RuntimeError(
            "PostgreSQL is configured but "
            "psycopg2-binary is not installed."
        ) from exc


# ============================================================
# APP
# ============================================================

app = FastAPI(
    title="Empty Chair",
    version="0.7.0",
)

app.mount(
    "/static",
    StaticFiles(directory="static"),
    name="static",
)

templates = Jinja2Templates(
    directory="templates"
)


app.add_middleware(
    SessionMiddleware,
    secret_key=SESSION_SECRET,
    same_site="lax",
    https_only=PUBLIC_BASE_URL.lower().startswith("https://"),
    max_age=60 * 60 * 24 * 30,
)


# ============================================================
# DATABASE
# ============================================================

def connect():
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

    conn = sqlite3.connect(
        DB_PATH,
        check_same_thread=False,
    )

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
    if USE_POSTGRES:
        query = query.replace(
            "?",
            "%s",
        )

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
            deposits_enabled INTEGER NOT NULL DEFAULT 0,
            default_deposit_amount REAL NOT NULL DEFAULT 0,
            stripe_account_id TEXT,
            stripe_details_submitted INTEGER NOT NULL DEFAULT 0,
            stripe_charges_enabled INTEGER NOT NULL DEFAULT 0,
            stripe_payouts_enabled INTEGER NOT NULL DEFAULT 0,
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
            deposit_status TEXT NOT NULL DEFAULT 'NOT_REQUIRED',
            deposit_paid_at TEXT,
            stripe_checkout_session_id TEXT,
            stripe_payment_intent_id TEXT,
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

        cursor = conn.cursor()
        cursor.execute(schema)

    else:
        schema = """
        CREATE TABLE IF NOT EXISTS shops (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            timezone TEXT NOT NULL DEFAULT 'America/New_York',
            phone TEXT,
            email TEXT,
            booking_url TEXT,
            deposits_enabled INTEGER NOT NULL DEFAULT 0,
            default_deposit_amount REAL NOT NULL DEFAULT 0,
            stripe_account_id TEXT,
            stripe_details_submitted INTEGER NOT NULL DEFAULT 0,
            stripe_charges_enabled INTEGER NOT NULL DEFAULT 0,
            stripe_payouts_enabled INTEGER NOT NULL DEFAULT 0,
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
            deposit_status TEXT NOT NULL DEFAULT 'NOT_REQUIRED',
            deposit_paid_at TEXT,
            stripe_checkout_session_id TEXT,
            stripe_payment_intent_id TEXT,
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

        conn.executescript(schema)

    db_execute(
        conn,
        """
        CREATE TABLE IF NOT EXISTS users (
            id TEXT PRIMARY KEY,
            shop_id TEXT NOT NULL,
            name TEXT NOT NULL,
            email TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            password_salt TEXT NOT NULL,
            is_active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL,
            FOREIGN KEY(shop_id) REFERENCES shops(id)
        )
        """,
    )

    db_execute(
        conn,
        """
        CREATE TABLE IF NOT EXISTS password_reset_tokens (
            id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            token_hash TEXT NOT NULL UNIQUE,
            expires_at TEXT NOT NULL,
            used_at TEXT,
            created_at TEXT NOT NULL,
            FOREIGN KEY(user_id) REFERENCES users(id)
        )
        """,
    )

    db_execute(
        conn,
        """
        CREATE INDEX IF NOT EXISTS idx_users_shop_id
        ON users(shop_id)
        """,
    )

    db_execute(
        conn,
        """
        CREATE INDEX IF NOT EXISTS idx_reset_user_id
        ON password_reset_tokens(user_id)
        """,
    )

    conn.commit()
    conn.close()


# ============================================================
# GENERAL HELPERS
# ============================================================

def now_iso():
    return datetime.now(
        timezone.utc
    ).isoformat()


def parse_datetime(value):
    if not value:
        return None

    try:
        dt = datetime.fromisoformat(value)

        if dt.tzinfo is None:
            dt = dt.replace(
                tzinfo=timezone.utc
            )

        return dt

    except (ValueError, TypeError):
        return None


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
        item.strip().lower()
        for item in (value or "").split(",")
        if item.strip()
    }


def normalize_int(
    value,
    default=0,
):
    try:
        return int(
            value or default
        )
    except (
        ValueError,
        TypeError,
    ):
        return default


def normalize_float(
    value,
    default=0.0,
):
    try:
        return float(
            value or default
        )
    except (
        ValueError,
        TypeError,
    ):
        return default



# ============================================================
# AUTHENTICATION / EMAIL
# ============================================================

def normalize_email(value):
    return (value or "").strip().lower()


def hash_password(password, salt=None):
    if salt is None:
        salt = secrets.token_hex(16)

    digest = hashlib.scrypt(
        password.encode("utf-8"),
        salt=bytes.fromhex(salt),
        n=2**14,
        r=8,
        p=1,
        dklen=64,
    )

    return digest.hex(), salt


def verify_password(password, stored_hash, stored_salt):
    try:
        candidate_hash, _ = hash_password(
            password,
            stored_salt,
        )

        return hmac.compare_digest(
            candidate_hash,
            stored_hash,
        )
    except (ValueError, TypeError):
        return False


def token_digest(token):
    return hashlib.sha256(
        token.encode("utf-8")
    ).hexdigest()


def get_current_user(request):
    user_id = request.session.get(
        "user_id"
    )

    if not user_id:
        return None

    conn = connect()

    user = db_fetchone(
        conn,
        """
        SELECT
            u.*,
            s.name AS shop_name,
            s.timezone AS shop_timezone,
            s.email AS shop_email,
            s.phone AS shop_phone,
            s.booking_url AS shop_booking_url
        FROM users u
        JOIN shops s
            ON s.id = u.shop_id
        WHERE u.id = ?
          AND u.is_active = 1
        LIMIT 1
        """,
        (
            user_id,
        ),
    )

    conn.close()

    if not user:
        request.session.clear()
        return None

    return user


def login_required_redirect(request):
    user = get_current_user(request)

    if user:
        return user, None

    next_path = request.url.path

    return None, RedirectResponse(
        f"/login?next={next_path}",
        status_code=303,
    )


def user_owns_opening(user, opening_id):
    conn = connect()

    row = db_fetchone(
        conn,
        """
        SELECT id
        FROM openings
        WHERE id = ?
          AND shop_id = ?
        LIMIT 1
        """,
        (
            opening_id,
            user["shop_id"],
        ),
    )

    conn.close()

    return bool(row)


def user_owns_booking(user, booking_id):
    conn = connect()

    row = db_fetchone(
        conn,
        """
        SELECT b.id
        FROM bookings b
        JOIN openings o
            ON o.id = b.opening_id
        WHERE b.id = ?
          AND o.shop_id = ?
        LIMIT 1
        """,
        (
            booking_id,
            user["shop_id"],
        ),
    )

    conn.close()

    return bool(row)


def user_owns_offer(user, offer_id):
    conn = connect()

    row = db_fetchone(
        conn,
        """
        SELECT ofr.id
        FROM offers ofr
        JOIN openings o
            ON o.id = ofr.opening_id
        WHERE ofr.id = ?
          AND o.shop_id = ?
        LIMIT 1
        """,
        (
            offer_id,
            user["shop_id"],
        ),
    )

    conn.close()

    return bool(row)


def send_email(to_email, subject, html):
    to_email = normalize_email(to_email)

    if not to_email:
        return False

    if DEMO_MODE and not RESEND_API_KEY:
        print()
        print("--- DEMO EMAIL ---")
        print(f"To: {to_email}")
        print(f"Subject: {subject}")
        print(html)
        print("------------------")
        print()
        return True

    if not RESEND_API_KEY:
        print(
            "Email skipped: RESEND_API_KEY "
            "is not configured."
        )
        return False

    try:
        resend.api_key = RESEND_API_KEY

        response = resend.Emails.send(
            {
                "from": EMAIL_FROM,
                "to": [to_email],
                "subject": subject,
                "html": html,
            }
        )

        print(
            f"Email sent successfully to {to_email}: "
            f"{response}"
        )
        return True

    except Exception as exc:
        print(
            "Email send failed:",
            str(exc),
        )
        return False

def send_welcome_email(user_name, email, shop_name):
    first_name = (
        (user_name or "there")
        .strip()
        .split()[0]
    )

    return send_email(
        email,
        "Welcome to Empty Chair",
        f"""
        <div style="font-family:Arial,sans-serif;max-width:560px;margin:auto;">
            <h2>Welcome to Empty Chair, {first_name}.</h2>
            <p>
                Your account for <strong>{shop_name}</strong> is ready.
            </p>
            <p>
                You can now create openings, launch recovery campaigns,
                and track recovered revenue from your dashboard.
            </p>
            <p>
                <a href="{PUBLIC_BASE_URL.rstrip('/')}/login">
                    Sign in to Empty Chair
                </a>
            </p>
        </div>
        """,
    )


def send_password_reset_email(user_name, email, token):
    reset_url = (
        f"{PUBLIC_BASE_URL.rstrip('/')}"
        f"/reset-password?token={token}"
    )

    first_name = (
        (user_name or "there")
        .strip()
        .split()[0]
    )

    return send_email(
        email,
        "Reset your Empty Chair password",
        f"""
        <div style="font-family:Arial,sans-serif;max-width:560px;margin:auto;">
            <h2>Password reset</h2>
            <p>Hi {first_name},</p>
            <p>
                Use the link below to choose a new Empty Chair password.
                The link expires in {PASSWORD_RESET_MINUTES} minutes.
            </p>
            <p>
                <a href="{reset_url}">Reset password</a>
            </p>
            <p>
                If you did not request this, you can ignore this email.
            </p>
        </div>
        """,
    )


def send_password_changed_email(user_name, email):
    first_name = (
        (user_name or "there")
        .strip()
        .split()[0]
    )

    return send_email(
        email,
        "Your Empty Chair password was changed",
        f"""
        <div style="font-family:Arial,sans-serif;max-width:560px;margin:auto;">
            <h2>Password changed</h2>
            <p>Hi {first_name},</p>
            <p>
                Your Empty Chair password was changed successfully.
            </p>
            <p>
                If you did not make this change, contact your administrator
                and rotate your credentials immediately.
            </p>
        </div>
        """,
    )


def send_recovery_email(opening_id):
    conn = connect()

    row = db_fetchone(
        conn,
        """
        SELECT
            o.id,
            o.date,
            o.start_time,
            o.price,
            a.name AS artist_name,
            c.name AS customer_name,
            s.name AS shop_name,
            u.name AS user_name,
            u.email AS user_email
        FROM openings o
        JOIN artists a
            ON a.id = o.artist_id
        JOIN bookings b
            ON b.id = o.booking_id
        JOIN customers c
            ON c.id = b.customer_id
        JOIN shops s
            ON s.id = o.shop_id
        JOIN users u
            ON u.shop_id = s.id
           AND u.is_active = 1
        WHERE o.id = ?
        ORDER BY u.created_at
        LIMIT 1
        """,
        (
            opening_id,
        ),
    )

    conn.close()

    if not row:
        return False

    return send_email(
        row["user_email"],
        "Empty Chair recovered an opening",
        f"""
        <div style="font-family:Arial,sans-serif;max-width:560px;margin:auto;">
            <h2>Chair recovered</h2>
            <p>
                <strong>{row["customer_name"]}</strong> claimed the
                {row["date"]} opening at {row["start_time"]} with
                {row["artist_name"]}.
            </p>
            <p>
                Estimated recovered revenue:
                <strong>${float(row["price"]):.0f}</strong>
            </p>
            <p>
                <a href="{PUBLIC_BASE_URL.rstrip('/')}/openings/{opening_id}">
                    View the opening
                </a>
            </p>
        </div>
        """,
    )


# ============================================================
# MATCHING
# ============================================================

def recovery_score(
    customer,
    opening,
    artist,
):
    score = 0

    artist_preferences = csv_values(
        customer["preferred_artists"]
    )

    style_preferences = csv_values(
        customer["preferred_styles"]
    )

    service_preferences = csv_values(
        customer["preferred_services"]
    )

    artist_id = (
        opening["artist_id"] or ""
    ).lower()

    artist_name = (
        artist["name"] or ""
    ).lower()

    style = (
        opening["style"] or ""
    ).lower()

    service = (
        opening["service"] or ""
    ).lower()

    artist_styles = csv_values(
        artist["styles"]
    )

    if artist_id in artist_preferences:
        score += 30

    if artist_name in artist_preferences:
        score += 30

    if style and style in style_preferences:
        score += 25

    if service and service in service_preferences:
        score += 20

    if style and style in artist_styles:
        score += 5

    if (
        customer["completed_count"] or 0
    ) >= 3:
        score += 10

    if (
        (customer["cancellation_count"] or 0) == 0
        and
        (customer["appointment_count"] or 0) > 0
    ):
        score += 5

    if customer["last_offer_at"]:
        last_offer = parse_datetime(
            customer["last_offer_at"]
        )

        if (
            last_offer
            and
            datetime.now(timezone.utc) - last_offer
            < timedelta(days=30)
        ):
            score -= 5

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

    if customer["name"]:
        first_name = (
            customer["name"]
            .strip()
            .split()[0]
        )
    else:
        first_name = "there"

    style = (
        opening["style"]
        or "tattoo"
    )

    message = (
        f"Hey {first_name} — "
        f"a {style} opening is available "
        f"on {opening['date']} at "
        f"{opening['start_time']} "
        f"for ${float(opening['price']):.0f}. "
        f"Claim it: {claim_url}"
    )

    if DEMO_MODE:
        print()
        print("--- DEMO SMS ---")
        print(
            f"To: {customer['phone']}"
        )
        print(message)
        print("----------------")
        print()

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
            "EMPTY_CHAIR_DEMO_MODE is false."
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
# DEMO DATA
# ============================================================

def ensure_demo_data():
    conn = connect()

    existing_shop = db_fetchone(
        conn,
        """
        SELECT id
        FROM shops
        LIMIT 1
        """,
    )

    if existing_shop:
        conn.close()
        return False

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
            appointment_count,
            completed_count,
            cancellation_count,
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
                appointment_count,
                completed_count,
                cancellation_count,
                timestamp,
                timestamp,
            ),
        )

    conn.commit()
    conn.close()

    return True


# ============================================================
# SEQUENTIAL RECOVERY
# ============================================================

def create_recovery_queue(
    opening_id,
):
    conn = connect()

    opening = db_fetchone(
        conn,
        """
        SELECT *
        FROM openings
        WHERE id = ?
        """,
        (
            opening_id,
        ),
    )

    if not opening:
        conn.close()
        return 0

    artist = db_fetchone(
        conn,
        """
        SELECT *
        FROM artists
        WHERE id = ?
        """,
        (
            opening["artist_id"],
        ),
    )

    if not artist:
        conn.close()
        return 0

    existing_count_row = db_fetchone(
        conn,
        """
        SELECT COUNT(*) AS n
        FROM offers
        WHERE opening_id = ?
        """,
        (
            opening_id,
        ),
    )

    existing_count = (
        existing_count_row["n"]
        if existing_count_row
        else 0
    )

    if existing_count:
        conn.close()
        return existing_count

    customers = db_fetchall(
        conn,
        """
        SELECT *
        FROM customers
        WHERE shop_id = ?
          AND communication_consent = 1
        ORDER BY completed_count DESC
        """,
        (
            opening["shop_id"],
        ),
    )

    candidates = []

    for customer in customers:
        score = recovery_score(
            customer,
            opening,
            artist,
        )

        candidates.append(
            (
                score,
                customer,
            )
        )

    candidates.sort(
        key=lambda item: (
            item[0],
            item[1]["completed_count"] or 0,
        ),
        reverse=True,
    )

    selected = candidates[:5]

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

        placeholder_expiration = (
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
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                offer_id,
                opening_id,
                customer["id"],
                score,
                rank,
                "sms",
                placeholder_expiration.isoformat(),
                "PENDING",
            ),
        )

    if selected:
        db_execute(
            conn,
            """
            UPDATE openings
            SET status = 'RECOVERY_ACTIVE'
            WHERE id = ?
            """,
            (
                opening_id,
            ),
        )
    else:
        db_execute(
            conn,
            """
            UPDATE openings
            SET status = 'NO_RECOVERY'
            WHERE id = ?
            """,
            (
                opening_id,
            ),
        )

    conn.commit()
    conn.close()

    return len(selected)


def send_next_recovery_offer(
    opening_id,
):
    conn = connect()

    opening = db_fetchone(
        conn,
        """
        SELECT *
        FROM openings
        WHERE id = ?
        """,
        (
            opening_id,
        ),
    )

    if not opening:
        conn.close()
        return None

    if opening["status"] in (
        "CLAIMED",
        "BOOKED",
        "COMPLETED",
        "CANCELLED",
    ):
        conn.close()
        return None

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
        (
            opening_id,
        ),
    )

    if active_offer:
        expires_at = parse_datetime(
            active_offer["expires_at"]
        )

        if (
            expires_at
            and
            datetime.now(timezone.utc) >= expires_at
        ):
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
                    active_offer["id"],
                ),
            )

            conn.commit()

            event(
                "offer.expired",
                "offer",
                active_offer["id"],
            )

        else:
            conn.close()
            return active_offer["id"]

    next_offer = db_fetchone(
        conn,
        """
        SELECT *
        FROM offers
        WHERE opening_id = ?
          AND status = 'PENDING'
        ORDER BY rank
        LIMIT 1
        """,
        (
            opening_id,
        ),
    )

    if not next_offer:
        db_execute(
            conn,
            """
            UPDATE openings
            SET status = 'NO_RECOVERY'
            WHERE id = ?
              AND status = 'RECOVERY_ACTIVE'
            """,
            (
                opening_id,
            ),
        )

        conn.commit()
        conn.close()

        event(
            "recovery.exhausted",
            "opening",
            opening_id,
        )

        return None

    customer = db_fetchone(
        conn,
        """
        SELECT *
        FROM customers
        WHERE id = ?
        """,
        (
            next_offer["customer_id"],
        ),
    )

    if not customer:
        db_execute(
            conn,
            """
            UPDATE offers
            SET status = 'FAILED'
            WHERE id = ?
            """,
            (
                next_offer["id"],
            ),
        )

        conn.commit()
        conn.close()

        return send_next_recovery_offer(
            opening_id
        )

    timestamp = now_iso()

    expires_at = (
        datetime.now(timezone.utc)
        + timedelta(minutes=30)
    )

    try:
        send_sms(
            customer,
            opening,
            next_offer["id"],
        )

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
                customer["id"],
            ),
        )

        db_execute(
            conn,
            """
            UPDATE openings
            SET status = 'RECOVERY_ACTIVE'
            WHERE id = ?
            """,
            (
                opening_id,
            ),
        )

        conn.commit()
        conn.close()

        event(
            "offer.sent",
            "offer",
            next_offer["id"],
        )

        return next_offer["id"]

    except Exception as exc:
        db_execute(
            conn,
            """
            UPDATE offers
            SET status = 'FAILED'
            WHERE id = ?
            """,
            (
                next_offer["id"],
            ),
        )

        conn.commit()
        conn.close()

        event(
            "offer.send_failed",
            "offer",
            next_offer["id"],
            str(exc),
        )

        return send_next_recovery_offer(
            opening_id
        )


def start_recovery_campaign(
    opening_id,
):
    conn = connect()

    opening = db_fetchone(
        conn,
        """
        SELECT *
        FROM openings
        WHERE id = ?
        """,
        (
            opening_id,
        ),
    )

    if not opening:
        conn.close()

        raise HTTPException(
            404,
            "Opening not found",
        )

    if opening["status"] in (
        "CLAIMED",
        "BOOKED",
        "COMPLETED",
        "CANCELLED",
    ):
        conn.close()

        raise HTTPException(
            400,
            "This opening is no longer available "
            "for recovery.",
        )

    conn.close()

    queue_size = create_recovery_queue(
        opening_id
    )

    if queue_size == 0:
        return None

    return send_next_recovery_offer(
        opening_id
    )


def expire_offer_and_continue(
    offer_id,
):
    conn = connect()

    offer = db_fetchone(
        conn,
        """
        SELECT *
        FROM offers
        WHERE id = ?
        """,
        (
            offer_id,
        ),
    )

    if not offer:
        conn.close()
        return None

    if offer["status"] not in (
        "PENDING",
        "SENT",
    ):
        opening_id = (
            offer["opening_id"]
        )

        conn.close()

        return send_next_recovery_offer(
            opening_id
        )

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
            offer_id,
        ),
    )

    opening_id = (
        offer["opening_id"]
    )

    conn.commit()
    conn.close()

    event(
        "offer.expired",
        "offer",
        offer_id,
    )

    return send_next_recovery_offer(
        opening_id
    )


def advance_opening_queue(
    opening_id,
):
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
        (
            opening_id,
        ),
    )

    conn.close()

    if active:
        return expire_offer_and_continue(
            active["id"]
        )

    return send_next_recovery_offer(
        opening_id
    )


# ============================================================
# STARTUP
# ============================================================

@app.on_event("startup")
def startup():
    mascot_source = os.path.join("static", "empty-chair-reaper-seated-v3-webp.b64")
    mascot_target = os.path.join("static", "empty-chair-reaper-seated-v3.webp")
    if os.path.exists(mascot_source):
        with open(mascot_source, "r", encoding="utf-8") as source:
            encoded_mascot = source.read().strip()
        with open(mascot_target, "wb") as target:
            target.write(base64.b64decode(encoded_mascot))
    init_db()



# ============================================================
# AUTH ROUTES
# ============================================================

@app.get(
    "/signup",
    response_class=HTMLResponse,
)
def signup_page(
    request: Request,
):
    if get_current_user(request):
        return RedirectResponse(
            "/",
            status_code=303,
        )

    return templates.TemplateResponse(
        request=request,
        name="signup.html",
        context={
            "error": None,
        },
    )


@app.post(
    "/signup",
    response_class=HTMLResponse,
)
def signup(
    request: Request,
    name: str = Form(...),
    shop_name: str = Form(...),
    email: str = Form(...),
    password: str = Form(...),
):
    name = name.strip()
    shop_name = shop_name.strip()
    email = normalize_email(email)

    if not name or not shop_name or not email:
        return templates.TemplateResponse(
            request=request,
            name="signup.html",
            status_code=400,
            context={
                "error": "All fields are required.",
            },
        )

    if len(password) < 8:
        return templates.TemplateResponse(
            request=request,
            name="signup.html",
            status_code=400,
            context={
                "error": (
                    "Password must be at least "
                    "8 characters."
                ),
            },
        )

    conn = connect()

    existing = db_fetchone(
        conn,
        """
        SELECT id
        FROM users
        WHERE email = ?
        LIMIT 1
        """,
        (
            email,
        ),
    )

    if existing:
        conn.close()

        return templates.TemplateResponse(
            request=request,
            name="signup.html",
            status_code=400,
            context={
                "error": (
                    "An account with that email "
                    "already exists."
                ),
            },
        )

    user_id = (
        f"user_{uuid.uuid4().hex[:12]}"
    )

    shop_id = (
        f"shop_{uuid.uuid4().hex[:12]}"
    )

    password_hash, password_salt = (
        hash_password(password)
    )

    timestamp = now_iso()

    try:
        db_execute(
            conn,
            """
            INSERT INTO shops(
                id,
                name,
                timezone,
                email,
                status,
                created_at
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                shop_id,
                shop_name,
                "America/New_York",
                email,
                "active",
                timestamp,
            ),
        )

        db_execute(
            conn,
            """
            INSERT INTO users(
                id,
                shop_id,
                name,
                email,
                password_hash,
                password_salt,
                is_active,
                created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                user_id,
                shop_id,
                name,
                email,
                password_hash,
                password_salt,
                1,
                timestamp,
            ),
        )

        conn.commit()

    except Exception:
        conn.rollback()
        conn.close()
        raise

    conn.close()

    request.session.clear()
    request.session["user_id"] = user_id

    event(
        "user.created",
        "user",
        user_id,
    )

    send_welcome_email(
        name,
        email,
        shop_name,
    )

    return RedirectResponse(
        "/",
        status_code=303,
    )


@app.get(
    "/login",
    response_class=HTMLResponse,
)
def login_page(
    request: Request,
    next: str = "/",
    fresh: int = 0,
):
    # Public sales-site login should always show the form, even if this
    # browser still holds a demo or owner session.
    if fresh:
        request.session.clear()

    if get_current_user(request):
        return RedirectResponse(
            "/",
            status_code=303,
        )

    return templates.TemplateResponse(
        request=request,
        name="login.html",
        context={
            "error": None,
            "next": next,
        },
    )


@app.post(
    "/login",
    response_class=HTMLResponse,
)
def login(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    next: str = Form("/"),
):
    email = normalize_email(email)

    conn = connect()

    user = db_fetchone(
        conn,
        """
        SELECT *
        FROM users
        WHERE email = ?
          AND is_active = 1
        LIMIT 1
        """,
        (
            email,
        ),
    )

    conn.close()

    if (
        not user
        or not verify_password(
            password,
            user["password_hash"],
            user["password_salt"],
        )
    ):
        return templates.TemplateResponse(
            request=request,
            name="login.html",
            status_code=400,
            context={
                "error": "Invalid email or password.",
                "next": next,
            },
        )

    request.session.clear()
    request.session["user_id"] = user["id"]

    if (
        not next
        or not next.startswith("/")
        or next.startswith("//")
    ):
        next = "/"

    event(
        "user.logged_in",
        "user",
        user["id"],
    )

    return RedirectResponse(
        next,
        status_code=303,
    )


@app.post("/logout")
def logout(
    request: Request,
):
    request.session.clear()

    return RedirectResponse(
        "/login",
        status_code=303,
    )


@app.get(
    "/forgot-password",
    response_class=HTMLResponse,
)
def forgot_password_page(
    request: Request,
):
    return templates.TemplateResponse(
        request=request,
        name="forgot_password.html",
        context={
            "sent": False,
            "error": None,
        },
    )


@app.post(
    "/forgot-password",
    response_class=HTMLResponse,
)
def forgot_password(
    request: Request,
    email: str = Form(...),
):
    email = normalize_email(email)

    conn = connect()

    user = db_fetchone(
        conn,
        """
        SELECT *
        FROM users
        WHERE email = ?
          AND is_active = 1
        LIMIT 1
        """,
        (
            email,
        ),
    )

    if user:
        raw_token = secrets.token_urlsafe(32)

        reset_id = (
            f"reset_{uuid.uuid4().hex[:12]}"
        )

        expires_at = (
            datetime.now(timezone.utc)
            + timedelta(
                minutes=PASSWORD_RESET_MINUTES
            )
        )

        db_execute(
            conn,
            """
            UPDATE password_reset_tokens
            SET used_at = ?
            WHERE user_id = ?
              AND used_at IS NULL
            """,
            (
                now_iso(),
                user["id"],
            ),
        )

        db_execute(
            conn,
            """
            INSERT INTO password_reset_tokens(
                id,
                user_id,
                token_hash,
                expires_at,
                used_at,
                created_at
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                reset_id,
                user["id"],
                token_digest(raw_token),
                expires_at.isoformat(),
                None,
                now_iso(),
            ),
        )

        conn.commit()

        send_password_reset_email(
            user["name"],
            user["email"],
            raw_token,
        )

        event(
            "password.reset_requested",
            "user",
            user["id"],
        )

    conn.close()

    return templates.TemplateResponse(
        request=request,
        name="forgot_password.html",
        context={
            "sent": True,
            "error": None,
        },
    )


def get_valid_reset(token):
    if not token:
        return None

    conn = connect()

    reset = db_fetchone(
        conn,
        """
        SELECT
            prt.*,
            u.name AS user_name,
            u.email AS user_email
        FROM password_reset_tokens prt
        JOIN users u
            ON u.id = prt.user_id
        WHERE prt.token_hash = ?
          AND prt.used_at IS NULL
          AND u.is_active = 1
        LIMIT 1
        """,
        (
            token_digest(token),
        ),
    )

    conn.close()

    if not reset:
        return None

    expiration = parse_datetime(
        reset["expires_at"]
    )

    if (
        not expiration
        or datetime.now(timezone.utc) >= expiration
    ):
        return None

    return reset


@app.get(
    "/reset-password",
    response_class=HTMLResponse,
)
def reset_password_page(
    request: Request,
    token: str = "",
):
    reset = get_valid_reset(token)

    return templates.TemplateResponse(
        request=request,
        name="reset_password.html",
        status_code=200 if reset else 400,
        context={
            "token": token,
            "valid": bool(reset),
            "error": None,
            "success": False,
        },
    )


@app.post(
    "/reset-password",
    response_class=HTMLResponse,
)
def reset_password(
    request: Request,
    token: str = Form(...),
    password: str = Form(...),
    password_confirm: str = Form(...),
):
    reset = get_valid_reset(token)

    if not reset:
        return templates.TemplateResponse(
            request=request,
            name="reset_password.html",
            status_code=400,
            context={
                "token": token,
                "valid": False,
                "error": (
                    "This reset link is invalid "
                    "or has expired."
                ),
                "success": False,
            },
        )

    if len(password) < 8:
        return templates.TemplateResponse(
            request=request,
            name="reset_password.html",
            status_code=400,
            context={
                "token": token,
                "valid": True,
                "error": (
                    "Password must be at least "
                    "8 characters."
                ),
                "success": False,
            },
        )

    if password != password_confirm:
        return templates.TemplateResponse(
            request=request,
            name="reset_password.html",
            status_code=400,
            context={
                "token": token,
                "valid": True,
                "error": "Passwords do not match.",
                "success": False,
            },
        )

    password_hash, password_salt = (
        hash_password(password)
    )

    conn = connect()

    db_execute(
        conn,
        """
        UPDATE users
        SET
            password_hash = ?,
            password_salt = ?
        WHERE id = ?
        """,
        (
            password_hash,
            password_salt,
            reset["user_id"],
        ),
    )

    db_execute(
        conn,
        """
        UPDATE password_reset_tokens
        SET used_at = ?
        WHERE user_id = ?
          AND used_at IS NULL
        """,
        (
            now_iso(),
            reset["user_id"],
        ),
    )

    conn.commit()
    conn.close()

    request.session.clear()
    request.session["user_id"] = (
        reset["user_id"]
    )

    event(
        "password.changed",
        "user",
        reset["user_id"],
    )

    send_password_changed_email(
        reset["user_name"],
        reset["user_email"],
    )

    return RedirectResponse(
        "/",
        status_code=303,
    )


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
    user, redirect = login_required_redirect(
        request
    )

    if redirect:
        return redirect

    conn = connect()

    shop = db_fetchone(
        conn,
        """
        SELECT *
        FROM shops
        WHERE id = ?
        LIMIT 1
        """,
        (
            user["shop_id"],
        ),
    )

    artists = db_fetchall(
        conn,
        """
        SELECT *
        FROM artists
        WHERE shop_id = ?
          AND active = 1
        ORDER BY name
        """,
        (
            user["shop_id"],
        ),
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
        WHERE o.shop_id = ?
        ORDER BY
            o.date DESC,
            o.start_time DESC
        """,
        (
            user["shop_id"],
        ),
    )

    recovery_metrics_row = db_fetchone(
    conn,
        """
        SELECT
            COALESCE(SUM(price), 0) AS total,
            COUNT(*) AS count
        FROM openings
        WHERE shop_id = ?
            AND status IN ('BOOKED', 'COMPLETED')
        """,
        (
            user["shop_id"],
        ),
    )

    completed_row = db_fetchone(
        conn,
        """
        SELECT
            COUNT(*) AS n
        FROM bookings b
        JOIN openings o
            ON o.id = b.opening_id
        WHERE b.status = 'COMPLETED'
          AND o.shop_id = ?
        """,
        (
            user["shop_id"],
        ),
    )

    total_openings_row = db_fetchone(
        conn,
        """
        SELECT COUNT(*) AS n
        FROM openings
        WHERE shop_id = ?
        """,
        (
            user["shop_id"],
        ),
    )

    customer_count_row = db_fetchone(
        conn,
        """
        SELECT COUNT(*) AS n
        FROM customers
        WHERE shop_id = ?
        """,
        (
            user["shop_id"],
        ),
    )

    conn.close()

    recovered = (
        recovery_metrics_row["total"]
        if recovery_metrics_row
        else 0
    )

    completed = (
        recovery_metrics_row["count"]
        if recovery_metrics_row
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

    return templates.TemplateResponse(
        request=request,
        name="dashboard.html",
        context={
            "user": user,
            "shop": shop,
            "artists": artists,
            "openings": openings,
            "recovered": recovered,
            "completed": completed,
            "total_openings": total_openings,
            "customer_count": customer_count,
            "demo_mode": DEMO_MODE,
        },
    )


# ============================================================
# DEMO SETUP
# ============================================================

@app.get("/demo/setup")
def demo_setup_get(
    request: Request,
):
    user, redirect = login_required_redirect(
        request
    )

    if redirect:
        return redirect

    return RedirectResponse(
        "/",
        status_code=303,
    )


@app.post("/demo/setup")
def demo_setup_post(
    request: Request,
):
    user, redirect = login_required_redirect(
        request
    )

    if redirect:
        return redirect

    return RedirectResponse(
        "/",
        status_code=303,
    )


# ============================================================
# ARTISTS
# ============================================================

@app.get(
    "/artists",
    response_class=HTMLResponse,
)
def artists_page(
    request: Request,
):
    user, redirect = login_required_redirect(
        request
    )

    if redirect:
        return redirect

    conn = connect()

    shop = db_fetchone(
        conn,
        """
        SELECT *
        FROM shops
        WHERE id = ?
        LIMIT 1
        """,
        (
            user["shop_id"],
        ),
    )

    artists = db_fetchall(
        conn,
        """
        SELECT *
        FROM artists
        WHERE shop_id = ?
        ORDER BY active DESC, name
        """,
        (
            user["shop_id"],
        ),
    )

    conn.close()

    return templates.TemplateResponse(
        request=request,
        name="artists.html",
        context={
            "user": user,
            "shop": shop,
            "artists": artists,
        },
    )


@app.post("/artists")
def create_artist(
    request: Request,
    name: str = Form(...),
    email: str = Form(""),
    phone: str = Form(""),
    styles: str = Form(""),
    services: str = Form("tattoo"),
):
    user, redirect = login_required_redirect(
        request
    )

    if redirect:
        return redirect

    name = name.strip()
    email = email.strip() or None
    phone = phone.strip() or None
    styles = styles.strip()
    services = services.strip() or "tattoo"

    if not name:
        raise HTTPException(
            400,
            "Artist name is required.",
        )

    conn = connect()

    existing = db_fetchone(
        conn,
        """
        SELECT id
        FROM artists
        WHERE shop_id = ?
          AND LOWER(name) = LOWER(?)
        LIMIT 1
        """,
        (
            user["shop_id"],
            name,
        ),
    )

    if existing:
        conn.close()
        raise HTTPException(
            400,
            "An artist with that name already exists.",
        )

    artist_id = f"artist_{uuid.uuid4().hex[:12]}"

    db_execute(
        conn,
        """
        INSERT INTO artists(
            id,
            shop_id,
            name,
            email,
            phone,
            styles,
            services,
            active
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, 1)
        """,
        (
            artist_id,
            user["shop_id"],
            name,
            email,
            phone,
            styles,
            services,
        ),
    )

    conn.commit()
    conn.close()

    event(
        "artist.created",
        "artist",
        artist_id,
    )

    return RedirectResponse(
        "/artists",
        status_code=303,
    )


@app.post("/artists/{artist_id}/toggle")
def toggle_artist(
    artist_id: str,
    request: Request,
):
    user, redirect = login_required_redirect(
        request
    )

    if redirect:
        return redirect

    conn = connect()

    artist = db_fetchone(
        conn,
        """
        SELECT *
        FROM artists
        WHERE id = ?
          AND shop_id = ?
        LIMIT 1
        """,
        (
            artist_id,
            user["shop_id"],
        ),
    )

    if not artist:
        conn.close()
        raise HTTPException(
            404,
            "Artist not found.",
        )

    new_active = 0 if artist["active"] else 1

    db_execute(
        conn,
        """
        UPDATE artists
        SET active = ?
        WHERE id = ?
          AND shop_id = ?
        """,
        (
            new_active,
            artist_id,
            user["shop_id"],
        ),
    )

    conn.commit()
    conn.close()

    event(
        "artist.status_changed",
        "artist",
        artist_id,
        {
            "active": new_active,
        },
    )

    return RedirectResponse(
        "/artists",
        status_code=303,
    )


# ============================================================
# ARTIST IMPORT
# ============================================================

@app.get(
    "/import/artists",
    response_class=HTMLResponse,
)
def artist_import_page(
    request: Request,
):
    user, redirect = login_required_redirect(
        request
    )

    if redirect:
        return redirect

    return templates.TemplateResponse(
        request=request,
        name="import_artists.html",
        context={
            "database_type": (
                "PostgreSQL"
                if USE_POSTGRES
                else "SQLite"
            ),
        },
    )


@app.post(
    "/import/artists",
    response_class=HTMLResponse,
)
async def import_artists(
    request: Request,
    file: UploadFile = File(...),
):
    user, redirect = login_required_redirect(
        request
    )

    if redirect:
        return redirect

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
        header.strip().lower()
        for header in reader.fieldnames
        if header
    }

    if "name" not in headers:
        raise HTTPException(
            400,
            "Missing required column: name",
        )

    conn = connect()
    shop_id = user["shop_id"]

    imported = 0
    updated = 0
    skipped = 0
    errors = []

    for row_number, raw_row in enumerate(
        reader,
        start=2,
    ):
        try:
            row = {
                (key or "").strip().lower():
                (value or "").strip()
                for key, value in raw_row.items()
            }

            name = row.get("name", "")

            if not name:
                skipped += 1
                errors.append(
                    f"Row {row_number}: name is required."
                )
                continue

            supplied_id = row.get("id", "")
            email = row.get("email", "") or None
            phone = row.get("phone", "") or None
            styles = row.get("styles", "")
            services = row.get("services", "tattoo") or "tattoo"

            active_raw = row.get(
                "active",
                "1",
            ).lower()

            active = (
                0
                if active_raw in {
                    "0",
                    "false",
                    "no",
                    "n",
                    "off",
                    "inactive",
                }
                else 1
            )

            existing = None

            if supplied_id:
                existing = db_fetchone(
                    conn,
                    """
                    SELECT *
                    FROM artists
                    WHERE id = ?
                      AND shop_id = ?
                    LIMIT 1
                    """,
                    (
                        supplied_id,
                        shop_id,
                    ),
                )

            if not existing:
                existing = db_fetchone(
                    conn,
                    """
                    SELECT *
                    FROM artists
                    WHERE shop_id = ?
                      AND LOWER(name) = LOWER(?)
                    LIMIT 1
                    """,
                    (
                        shop_id,
                        name,
                    ),
                )

            if existing:
                db_execute(
                    conn,
                    """
                    UPDATE artists
                    SET
                        name = ?,
                        email = ?,
                        phone = ?,
                        styles = ?,
                        services = ?,
                        active = ?
                    WHERE id = ?
                      AND shop_id = ?
                    """,
                    (
                        name,
                        email,
                        phone,
                        styles,
                        services,
                        active,
                        existing["id"],
                        shop_id,
                    ),
                )
                updated += 1
            else:
                artist_id = (
                    supplied_id
                    or f"artist_{uuid.uuid4().hex[:12]}"
                )

                id_conflict = db_fetchone(
                    conn,
                    """
                    SELECT id
                    FROM artists
                    WHERE id = ?
                    LIMIT 1
                    """,
                    (
                        artist_id,
                    ),
                )

                if id_conflict:
                    artist_id = f"artist_{uuid.uuid4().hex[:12]}"

                db_execute(
                    conn,
                    """
                    INSERT INTO artists(
                        id,
                        shop_id,
                        name,
                        email,
                        phone,
                        styles,
                        services,
                        active
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        artist_id,
                        shop_id,
                        name,
                        email,
                        phone,
                        styles,
                        services,
                        active,
                    ),
                )
                imported += 1

        except Exception as exc:
            skipped += 1
            errors.append(
                f"Row {row_number}: {exc}"
            )

    conn.commit()
    conn.close()

    event(
        "artists.imported",
        "shop",
        shop_id,
        {
            "imported": imported,
            "updated": updated,
            "skipped": skipped,
        },
    )

    return templates.TemplateResponse(
        request=request,
        name="import_result.html",
        context={
            "imported": imported,
            "updated": updated,
            "skipped": skipped,
            "errors": errors,
            "return_url": "/artists",
            "return_label": "Back to Artists",
        },
    )


# ============================================================
# CUSTOMER IMPORT
# ============================================================

@app.get(
    "/import/customers",
    response_class=HTMLResponse,
)
def customer_import_page(
    request: Request,
):
    user, redirect = login_required_redirect(
        request
    )

    if redirect:
        return redirect

    return templates.TemplateResponse(
        request=request,
        name="import_customers.html",
        context={
            "database_type": (
                "PostgreSQL"
                if USE_POSTGRES
                else "SQLite"
            ),
        },
    )


@app.post(
    "/import/customers",
    response_class=HTMLResponse,
)
async def import_customers(
    request: Request,
    file: UploadFile = File(...),
):
    user, redirect = login_required_redirect(
        request
    )

    if redirect:
        return redirect

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
        header.strip().lower()
        for header in reader.fieldnames
        if header
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

    shop_id = user["shop_id"]

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
                (key or "")
                .strip()
                .lower():
                (value or "")
                .strip()
                for (
                    key,
                    value,
                ) in raw_row.items()
            }

            name = row.get(
                "name",
                "",
            )

            phone = row.get(
                "phone",
                "",
            )

            if not name or not phone:
                skipped += 1

                errors.append(
                    f"Row {row_number}: "
                    "name and phone are required."
                )

                continue

            supplied_id = row.get(
                "id",
                "",
            )

            email = (
                row.get(
                    "email",
                    "",
                )
                or None
            )

            consent_raw = (
                row.get(
                    "communication_consent",
                    "0",
                )
                .strip()
                .lower()
            )

            communication_consent = (
                1
                if consent_raw
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

            appointment_count = normalize_int(
                row.get(
                    "appointment_count",
                    "0",
                )
            )

            completed_count = normalize_int(
                row.get(
                    "completed_count",
                    "0",
                )
            )

            cancellation_count = normalize_int(
                row.get(
                    "cancellation_count",
                    "0",
                )
            )

            no_show_count = normalize_int(
                row.get(
                    "no_show_count",
                    "0",
                )
            )

            average_spend = normalize_float(
                row.get(
                    "average_spend",
                    "0",
                )
            )

            existing = None

            if supplied_id:
                existing = db_fetchone(
                    conn,
                    """
                    SELECT *
                    FROM customers
                    WHERE id = ?
                    LIMIT 1
                    """,
                    (
                        supplied_id,
                    ),
                )

            if not existing:
                existing = db_fetchone(
                    conn,
                    """
                    SELECT *
                    FROM customers
                    WHERE shop_id = ?
                      AND phone = ?
                    LIMIT 1
                    """,
                    (
                        shop_id,
                        phone,
                    ),
                )

            timestamp = now_iso()

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
                        no_show_count = ?,
                        average_spend = ?,
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
                        no_show_count,
                        average_spend,
                        timestamp,
                        existing["id"],
                    ),
                )

                updated += 1

            else:
                customer_id = (
                    supplied_id
                    or
                    f"cust_{uuid.uuid4().hex[:12]}"
                )

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
                        communication_consent,
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

        except Exception as exc:
            if USE_POSTGRES:
                conn.rollback()

            skipped += 1

            errors.append(
                f"Row {row_number}: "
                f"{str(exc)}"
            )

    conn.commit()
    conn.close()

    return templates.TemplateResponse(
        request=request,
        name="import_result.html",
        context={
            "imported": imported,
            "updated": updated,
            "skipped": skipped,
            "errors": errors,
        },
    )


# ============================================================
# CREATE OPENING
# ============================================================

@app.post("/openings")
def create_opening(
    request: Request,
    artist_id: str = Form(...),
    date: str = Form(...),
    start_time: str = Form(...),
    service: str = Form(...),
    style: str = Form(""),
    price: float = Form(...),
):
    user, redirect = login_required_redirect(
        request
    )

    if redirect:
        return redirect

    conn = connect()

    artist = db_fetchone(
        conn,
        """
        SELECT *
        FROM artists
        WHERE id = ?
          AND shop_id = ?
          AND active = 1
        """,
        (
            artist_id,
            user["shop_id"],
        ),
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

    opening_expiration = (
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
            opening_expiration.isoformat(),
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
    user, redirect = login_required_redirect(
        request
    )

    if redirect:
        return redirect

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
          AND o.shop_id = ?
        """,
        (
            opening_id,
            user["shop_id"],
        ),
    )

    if not opening:
        conn.close()

        raise HTTPException(
            404,
            "Opening not found",
        )

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
        (
            opening_id,
        ),
    )

    conn.close()

    if active_offer:
        expires_at = parse_datetime(
            active_offer["expires_at"]
        )

        if (
            expires_at
            and
            datetime.now(timezone.utc) >= expires_at
        ):
            expire_offer_and_continue(
                active_offer["id"]
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
          AND o.shop_id = ?
        """,
        (
            opening_id,
            user["shop_id"],
        ),
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
        (
            opening_id,
        ),
    )

    conn.close()

    return templates.TemplateResponse(
        request=request,
        name="opening.html",
        context={
            "opening": opening,
            "offers": offers,
        },
    )


# ============================================================
# START / ADVANCE RECOVERY
# ============================================================

@app.post(
    "/openings/{opening_id}/recover"
)
def start_recovery(
    request: Request,
    opening_id: str,
):
    user, redirect = login_required_redirect(
        request
    )

    if redirect:
        return redirect

    if not user_owns_opening(
        user,
        opening_id,
    ):
        raise HTTPException(
            404,
            "Opening not found",
        )

    start_recovery_campaign(
        opening_id
    )

    return RedirectResponse(
        f"/openings/{opening_id}",
        status_code=303,
    )


@app.post(
    "/openings/{opening_id}/next"
)
def next_recovery_customer(
    request: Request,
    opening_id: str,
):
    user, redirect = login_required_redirect(
        request
    )

    if redirect:
        return redirect

    if not user_owns_opening(
        user,
        opening_id,
    ):
        raise HTTPException(
            404,
            "Opening not found",
        )

    advance_opening_queue(
        opening_id
    )

    return RedirectResponse(
        f"/openings/{opening_id}",
        status_code=303,
    )


@app.post(
    "/openings/{opening_id}/advance"
)
def advance_recovery(
    request: Request,
    opening_id: str,
):
    user, redirect = login_required_redirect(
        request
    )

    if redirect:
        return redirect

    if not user_owns_opening(
        user,
        opening_id,
    ):
        raise HTTPException(
            404,
            "Opening not found",
        )

    advance_opening_queue(
        opening_id
    )

    return RedirectResponse(
        f"/openings/{opening_id}",
        status_code=303,
    )


# ============================================================
# OFFER PAGE
# ============================================================

def get_offer_details(
    conn,
    offer_id,
):
    return db_fetchone(
        conn,
        """
        SELECT
            o.*,
            c.name AS customer_name,
            c.phone AS customer_phone,
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
        (
            offer_id,
        ),
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

    offer = get_offer_details(
        conn,
        offer_id,
    )

    if not offer:
        conn.close()

        raise HTTPException(
            404,
            "Offer not found",
        )

    if offer["status"] == "SENT":
        expires_at = parse_datetime(
            offer["expires_at"]
        )

        if (
            expires_at
            and
            datetime.now(timezone.utc) >= expires_at
        ):
            conn.close()

            expire_offer_and_continue(
                offer_id
            )

            conn = connect()

            offer = get_offer_details(
                conn,
                offer_id,
            )

    if (
        offer
        and
        not offer["opened_at"]
    ):
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
        request=request,
        name="offer.html",
        context={
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
            op.shop_id,
            op.artist_id,
            op.price
        FROM offers o
        JOIN openings op
            ON op.id = o.opening_id
        WHERE o.id = ?
        """,
        (
            offer_id,
        ),
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

    expiration = parse_datetime(
        offer["expires_at"]
    )

    if (
        expiration
        and
        datetime.now(timezone.utc) >= expiration
    ):
        opening_id = (
            offer["opening_id"]
        )

        conn.close()

        expire_offer_and_continue(
            offer_id
        )

        raise HTTPException(
            400,
            "This offer has expired and "
            "the next customer has been contacted.",
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

    timestamp = now_iso()

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
        (
            offer["opening_id"],
        ),
    )

    db_execute(
        conn,
        """
        UPDATE offers
        SET status = 'CANCELLED'
        WHERE opening_id = ?
          AND id != ?
          AND status IN (
              'PENDING',
              'SENT'
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
        (
            offer["shop_id"],
        ),
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

    send_recovery_email(
        offer["opening_id"]
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
        (
            offer_id,
        ),
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
            "This offer has already been processed.",
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

    opening_id = (
        offer["opening_id"]
    )

    conn.commit()
    conn.close()

    event(
        "offer.declined",
        "offer",
        offer_id,
        reason,
    )

    send_next_recovery_offer(
        opening_id
    )

    return RedirectResponse(
        f"/offer/{offer_id}",
        status_code=303,
    )


# ============================================================
# EXPIRE OFFER
# ============================================================

@app.post(
    "/offer/{offer_id}/expire"
)
def expire_offer(
    request: Request,
    offer_id: str,
):
    user, redirect = login_required_redirect(
        request
    )

    if redirect:
        return redirect

    if not user_owns_offer(
        user,
        offer_id,
    ):
        raise HTTPException(
            404,
            "Offer not found",
        )

    conn = connect()

    offer = db_fetchone(
        conn,
        """
        SELECT *
        FROM offers
        WHERE id = ?
        """,
        (
            offer_id,
        ),
    )

    if not offer:
        conn.close()

        raise HTTPException(
            404,
            "Offer not found",
        )

    opening_id = (
        offer["opening_id"]
    )

    conn.close()

    expire_offer_and_continue(
        offer_id
    )

    return RedirectResponse(
        f"/openings/{opening_id}",
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
            c.email AS customer_email,
            o.date,
            o.start_time,
            o.service,
            o.style,
            a.name AS artist_name
            ,s.name AS shop_name
        FROM bookings b
        JOIN customers c
            ON c.id = b.customer_id
        JOIN openings o
            ON o.id = b.opening_id
        JOIN artists a
            ON a.id = b.artist_id
        JOIN shops s
            ON s.id = o.shop_id
        WHERE b.id = ?
        """,
        (
            booking_id,
        ),
    )

    conn.close()

    if not booking:
        raise HTTPException(
            404,
            "Booking not found",
        )

    return templates.TemplateResponse(
        request=request,
        name="booking.html",
        context={
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
        (
            booking_id,
        ),
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
        (
            booking["opening_id"],
        ),
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
    request: Request,
    booking_id: str,
):
    user, redirect = login_required_redirect(
        request
    )

    if redirect:
        return redirect

    if not user_owns_booking(
        user,
        booking_id,
    ):
        raise HTTPException(
            404,
            "Booking not found",
        )

    conn = connect()

    booking = db_fetchone(
        conn,
        """
        SELECT *
        FROM bookings
        WHERE id = ?
        """,
        (
            booking_id,
        ),
    )

    if not booking:
        conn.close()

        raise HTTPException(
            404,
            "Booking not found",
        )

    if booking["status"] == "COMPLETED":
        conn.close()

        return RedirectResponse(
            "/",
            status_code=303,
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
        (
            booking["opening_id"],
        ),
    )

    customer = db_fetchone(
        conn,
        """
        SELECT *
        FROM customers
        WHERE id = ?
        """,
        (
            booking["customer_id"],
        ),
    )

    if customer:
        old_completed = (
            customer["completed_count"]
            or 0
        )

        old_average_spend = (
            customer["average_spend"]
            or 0
        )

        new_completed = (
            old_completed + 1
        )

        new_average_spend = (
            (
                old_average_spend
                * old_completed
            )
            + float(
                booking["amount"]
            )
        ) / new_completed

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
                new_completed,
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
            """
            SELECT 1 AS ok
            """,
        )

        shop_count = db_fetchone(
            conn,
            """
            SELECT COUNT(*) AS n
            FROM shops
            """,
        )

        customer_count = db_fetchone(
            conn,
            """
            SELECT COUNT(*) AS n
            FROM customers
            """,
        )

        conn.close()

        return {
            "status": "ok",
            "database": database_type,
            "database_status": "connected",
            "demo_mode": DEMO_MODE,
            "sequential_messaging": True,
            "shops": (
                shop_count["n"]
                if shop_count
                else 0
            ),
            "customers": (
                customer_count["n"]
                if customer_count
                else 0
            ),
            "version": "0.7.0",
        }

    except Exception as exc:
        return {
            "status": "error",
            "database": database_type,
            "database_status": "error",
            "error": str(exc),
            "demo_mode": DEMO_MODE,
            "sequential_messaging": True,
            "version": "0.7.0",
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
