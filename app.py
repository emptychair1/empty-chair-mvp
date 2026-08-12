from pathlib import Path
import re
import shutil
import textwrap
import os
import zipfile

src_path = Path("/mnt/data/Pasted text(1).txt")
out_dir = Path("/mnt/data/empty-chair-auth")
templates_dir = out_dir / "templates"
out_dir.mkdir(exist_ok=True)
templates_dir.mkdir(exist_ok=True)

src = src_path.read_text()

# ------------------------------------------------------------
# IMPORTS
# ------------------------------------------------------------
src = src.replace(
    "import os\nimport csv\nimport io\nimport sqlite3\nimport uuid\n",
    "import os\nimport csv\nimport io\nimport sqlite3\nimport uuid\nimport hashlib\nimport hmac\nimport json\nimport secrets\nimport urllib.error\nimport urllib.request\n",
)

src = src.replace(
    "from twilio.rest import Client\n",
    "from twilio.rest import Client\nfrom starlette.middleware.sessions import SessionMiddleware\n",
)

# ------------------------------------------------------------
# CONFIG
# ------------------------------------------------------------
config_anchor = "USE_POSTGRES = bool(DATABASE_URL)\n"
config_addition = r'''

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
'''
src = src.replace(config_anchor, config_anchor + config_addition)

# ------------------------------------------------------------
# APP MIDDLEWARE
# ------------------------------------------------------------
templates_anchor = """templates = Jinja2Templates(
    directory="templates"
)
"""
middleware_addition = r'''

app.add_middleware(
    SessionMiddleware,
    secret_key=SESSION_SECRET,
    same_site="lax",
    https_only=PUBLIC_BASE_URL.lower().startswith("https://"),
    max_age=60 * 60 * 24 * 30,
)
'''
src = src.replace(templates_anchor, templates_anchor + middleware_addition)

# ------------------------------------------------------------
# ADD AUTH TABLES TO init_db BEFORE COMMIT
# ------------------------------------------------------------
init_commit_anchor = """    conn.commit()
    conn.close()


# ============================================================
# GENERAL HELPERS
"""
auth_schema = r'''    db_execute(
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
'''
if init_commit_anchor not in src:
    raise RuntimeError("Could not locate init_db commit anchor")
src = src.replace(init_commit_anchor, auth_schema, 1)

# ------------------------------------------------------------
# AUTH / EMAIL HELPERS before MATCHING
# ------------------------------------------------------------
matching_anchor = """# ============================================================
# MATCHING
# ============================================================
"""
helpers = r'''
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
    to_email = normalize_email(
        to_email
    )

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

    payload = json.dumps(
        {
            "from": EMAIL_FROM,
            "to": [to_email],
            "subject": subject,
            "html": html,
        }
    ).encode("utf-8")

    request = urllib.request.Request(
        "https://api.resend.com/emails",
        data=payload,
        method="POST",
        headers={
            "Authorization": (
                f"Bearer {RESEND_API_KEY}"
            ),
            "Content-Type": "application/json",
        },
    )

    try:
        with urllib.request.urlopen(
            request,
            timeout=15,
        ) as response:
            return 200 <= response.status < 300
    except (
        urllib.error.HTTPError,
        urllib.error.URLError,
        TimeoutError,
    ) as exc:
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


'''
src = src.replace(matching_anchor, helpers + matching_anchor, 1)

# ------------------------------------------------------------
# AUTH ROUTES before DASHBOARD
# ------------------------------------------------------------
dashboard_anchor = """# ============================================================
# DASHBOARD
# ============================================================
"""
auth_routes = r'''
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
):
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


'''
src = src.replace(dashboard_anchor, auth_routes + dashboard_anchor, 1)

# ------------------------------------------------------------
# Replace dashboard
# ------------------------------------------------------------
def replace_block(text, start_marker, end_marker, replacement):
    s = text.index(start_marker)
    e = text.index(end_marker, s)
    return text[:s] + replacement + text[e:]

dashboard_start = """@app.get(
    "/",
    response_class=HTMLResponse,
)
def dashboard(
"""
demo_heading = """# ============================================================
# DEMO SETUP
# ============================================================
"""
dashboard_replacement = r'''@app.get(
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

    recovered_row = db_fetchone(
        conn,
        """
        SELECT
            COALESCE(
                SUM(b.amount),
                0
            ) AS total
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


'''
src = replace_block(src, dashboard_start, demo_heading, dashboard_replacement)

# ------------------------------------------------------------
# Disable global demo setup once auth exists (protected and harmless)
# ------------------------------------------------------------
demo_start = """@app.get("/demo/setup")"""
customer_heading = """# ============================================================
# CUSTOMER IMPORT
# ============================================================
"""
demo_replacement = r'''@app.get("/demo/setup")
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


'''
src = replace_block(src, demo_start, customer_heading, demo_replacement)

# ------------------------------------------------------------
# Customer import functions: protect + use current shop
# ------------------------------------------------------------
src = src.replace(
'''def customer_import_page(
    request: Request,
):
    return templates.TemplateResponse(
''',
'''def customer_import_page(
    request: Request,
):
    user, redirect = login_required_redirect(
        request
    )

    if redirect:
        return redirect

    return templates.TemplateResponse(
''',
1)

src = src.replace(
'''async def import_customers(
    request: Request,
    file: UploadFile = File(...),
):
    if not file.filename:
''',
'''async def import_customers(
    request: Request,
    file: UploadFile = File(...),
):
    user, redirect = login_required_redirect(
        request
    )

    if redirect:
        return redirect

    if not file.filename:
''',
1)

old_shop_lookup = '''    shop = db_fetchone(
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

        raise HTTPException(
            400,
            "No shop exists yet. "
            "Load the demo studio first.",
        )

    shop_id = shop["id"]
'''
src = src.replace(
    old_shop_lookup,
    '''    shop_id = user["shop_id"]\n''',
    1
)

# ------------------------------------------------------------
# Create opening: protect and scope artist
# ------------------------------------------------------------
src = src.replace(
'''def create_opening(
    artist_id: str = Form(...),
''',
'''def create_opening(
    request: Request,
    artist_id: str = Form(...),
''',
1)

src = src.replace(
'''    conn = connect()

    artist = db_fetchone(
        conn,
        """
        SELECT *
        FROM artists
        WHERE id = ?
          AND active = 1
        """,
        (
            artist_id,
        ),
    )
''',
'''    user, redirect = login_required_redirect(
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
''',
1)

# ------------------------------------------------------------
# Opening page: protect and scope
# ------------------------------------------------------------
opening_func_marker = '''def opening_page(
    request: Request,
    opening_id: str,
):
    conn = connect()
'''
src = src.replace(
    opening_func_marker,
'''def opening_page(
    request: Request,
    opening_id: str,
):
    user, redirect = login_required_redirect(
        request
    )

    if redirect:
        return redirect

    conn = connect()
''',
1)

# Replace both opening lookup WHEREs in opening_page only globally enough;
# this exact query occurs twice and is appropriate to scope both.
src = src.replace(
'''        WHERE o.id = ?
        """,
        (
            opening_id,
        ),
    )
''',
'''        WHERE o.id = ?
          AND o.shop_id = ?
        """,
        (
            opening_id,
            user["shop_id"],
        ),
    )
''',
2)

# ------------------------------------------------------------
# Start/advance recovery routes protection
# ------------------------------------------------------------
src = src.replace(
'''def start_recovery(
    opening_id: str,
):
    start_recovery_campaign(
''',
'''def start_recovery(
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
''',
1)

src = src.replace(
'''def next_recovery_customer(
    opening_id: str,
):
    advance_opening_queue(
''',
'''def next_recovery_customer(
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
''',
1)

src = src.replace(
'''def advance_recovery(
    opening_id: str,
):
    advance_opening_queue(
''',
'''def advance_recovery(
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
''',
1)

# ------------------------------------------------------------
# Expire offer is an admin control; protect it
# ------------------------------------------------------------
src = src.replace(
'''def expire_offer(
    offer_id: str,
):
    conn = connect()
''',
'''def expire_offer(
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
''',
1)

# ------------------------------------------------------------
# Complete booking is shop/admin control; protect it
# ------------------------------------------------------------
src = src.replace(
'''def complete_booking(
    booking_id: str,
):
    conn = connect()
''',
'''def complete_booking(
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
''',
1)

# ------------------------------------------------------------
# Send automatic "chair recovered" email after claim commit
# ------------------------------------------------------------
claim_event_anchor = '''    event(
        "booking.created",
        "booking",
        booking_id,
    )

    return RedirectResponse(
'''
claim_event_replacement = '''    event(
        "booking.created",
        "booking",
        booking_id,
    )

    send_recovery_email(
        offer["opening_id"]
    )

    return RedirectResponse(
'''
src = src.replace(
    claim_event_anchor,
    claim_event_replacement,
    1
)

# ------------------------------------------------------------
# Version bumps
# ------------------------------------------------------------
src = src.replace('version="0.6.0"', 'version="0.7.0"', 1)
src = src.replace('"version": "0.6.0"', '"version": "0.7.0"')

# ------------------------------------------------------------
# Write app.py
# ------------------------------------------------------------
app_path = out_dir / "app.py"
app_path.write_text(src)

# ------------------------------------------------------------
# Auth templates
# ------------------------------------------------------------
base_css = """
<style>
:root {
    --bg: #0e0f11;
    --panel: #17191d;
    --panel-2: #1f2227;
    --text: #f4f4f2;
    --muted: #a9adb5;
    --line: #2c3037;
    --accent: #f0c36a;
    --danger: #ff8c8c;
}
* { box-sizing: border-box; }
body {
    margin: 0;
    min-height: 100vh;
    display: grid;
    place-items: center;
    padding: 24px;
    background:
        radial-gradient(circle at top, #22252b 0, var(--bg) 42%);
    color: var(--text);
    font-family: Inter, ui-sans-serif, -apple-system, BlinkMacSystemFont,
        "Segoe UI", sans-serif;
}
.auth-shell {
    width: 100%;
    max-width: 430px;
}
.brand {
    text-align: center;
    margin-bottom: 22px;
}
.brand img {
    max-width: 210px;
    max-height: 90px;
    object-fit: contain;
}
.brand h1 {
    margin: 0;
    font-size: 30px;
    letter-spacing: -0.04em;
}
.card {
    background: rgba(23,25,29,.96);
    border: 1px solid var(--line);
    border-radius: 20px;
    padding: 28px;
    box-shadow: 0 24px 70px rgba(0,0,0,.35);
}
h2 {
    margin: 0 0 8px;
    font-size: 25px;
}
.sub {
    color: var(--muted);
    margin: 0 0 24px;
    line-height: 1.5;
}
label {
    display: block;
    font-size: 13px;
    font-weight: 700;
    margin: 15px 0 7px;
}
input {
    width: 100%;
    border: 1px solid var(--line);
    border-radius: 11px;
    padding: 13px 14px;
    background: var(--panel-2);
    color: var(--text);
    font: inherit;
    outline: none;
}
input:focus {
    border-color: var(--accent);
}
button {
    width: 100%;
    margin-top: 20px;
    border: 0;
    border-radius: 11px;
    padding: 13px 16px;
    background: var(--accent);
    color: #17130a;
    font: inherit;
    font-weight: 800;
    cursor: pointer;
}
.links {
    margin-top: 20px;
    text-align: center;
    color: var(--muted);
    font-size: 14px;
    line-height: 1.8;
}
a { color: var(--text); }
.error {
    background: rgba(255, 80, 80, .10);
    border: 1px solid rgba(255, 120, 120, .35);
    color: var(--danger);
    padding: 11px 12px;
    border-radius: 10px;
    margin: 14px 0;
    font-size: 14px;
}
.success {
    background: rgba(90, 220, 140, .10);
    border: 1px solid rgba(90, 220, 140, .35);
    padding: 11px 12px;
    border-radius: 10px;
    margin: 14px 0;
    font-size: 14px;
}
</style>
"""

def auth_doc(title, body):
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title} · Empty Chair</title>
{base_css}
</head>
<body>
<div class="auth-shell">
    <div class="brand">
        <img src="{{{{ url_for('static', path='/empty-chair-logo.png') }}}}"
             alt="Empty Chair">
    </div>
    <div class="card">
{body}
    </div>
</div>
</body>
</html>
"""

login_html = auth_doc("Log in", """
        <h2>Welcome back</h2>
        <p class="sub">Sign in to manage openings and recover empty chairs.</p>

        {% if error %}
        <div class="error">{{ error }}</div>
        {% endif %}

        <form method="post" action="/login">
            <input type="hidden" name="next" value="{{ next or '/' }}">

            <label for="email">Email</label>
            <input id="email" name="email" type="email"
                   autocomplete="email" required autofocus>

            <label for="password">Password</label>
            <input id="password" name="password" type="password"
                   autocomplete="current-password" required>

            <button type="submit">Log in</button>
        </form>

        <div class="links">
            <a href="/forgot-password">Forgot password?</a><br>
            New to Empty Chair? <a href="/signup">Create account</a>
        </div>
""")

signup_html = auth_doc("Create account", """
        <h2>Create your account</h2>
        <p class="sub">Set up your shop and start recovering cancellations.</p>

        {% if error %}
        <div class="error">{{ error }}</div>
        {% endif %}

        <form method="post" action="/signup">
            <label for="name">Your name</label>
            <input id="name" name="name" type="text"
                   autocomplete="name" required>

            <label for="shop_name">Shop name</label>
            <input id="shop_name" name="shop_name" type="text"
                   autocomplete="organization" required>

            <label for="email">Email</label>
            <input id="email" name="email" type="email"
                   autocomplete="email" required>

            <label for="password">Password</label>
            <input id="password" name="password" type="password"
                   autocomplete="new-password" minlength="8" required>

            <button type="submit">Create account</button>
        </form>

        <div class="links">
            Already have an account? <a href="/login">Log in</a>
        </div>
""")

forgot_html = auth_doc("Forgot password", """
        <h2>Reset your password</h2>
        <p class="sub">
            Enter your account email and we'll send you a reset link.
        </p>

        {% if sent %}
        <div class="success">
            If that email belongs to an account, a reset link has been sent.
        </div>
        {% endif %}

        {% if error %}
        <div class="error">{{ error }}</div>
        {% endif %}

        <form method="post" action="/forgot-password">
            <label for="email">Email</label>
            <input id="email" name="email" type="email"
                   autocomplete="email" required autofocus>

            <button type="submit">Send reset link</button>
        </form>

        <div class="links">
            <a href="/login">Back to login</a>
        </div>
""")

reset_html = auth_doc("Reset password", """
        <h2>Choose a new password</h2>

        {% if not valid %}
        <div class="error">
            This password reset link is invalid or has expired.
        </div>
        <div class="links">
            <a href="/forgot-password">Request another reset link</a>
        </div>
        {% else %}

            {% if error %}
            <div class="error">{{ error }}</div>
            {% endif %}

            <form method="post" action="/reset-password">
                <input type="hidden" name="token" value="{{ token }}">

                <label for="password">New password</label>
                <input id="password" name="password" type="password"
                       autocomplete="new-password" minlength="8" required>

                <label for="password_confirm">Confirm password</label>
                <input id="password_confirm" name="password_confirm"
                       type="password" autocomplete="new-password"
                       minlength="8" required>

                <button type="submit">Change password</button>
            </form>
        {% endif %}
""")

(templates_dir / "login.html").write_text(login_html)
(templates_dir / "signup.html").write_text(signup_html)
(templates_dir / "forgot_password.html").write_text(forgot_html)
(templates_dir / "reset_password.html").write_text(reset_html)

# ------------------------------------------------------------
# README setup
# ------------------------------------------------------------
setup_text = """EMPTY CHAIR AUTH UPDATE — v0.7.0

FILES
-----
app.py
templates/login.html
templates/signup.html
templates/forgot_password.html
templates/reset_password.html

KEEP YOUR EXISTING
------------------
templates/dashboard.html
templates/opening.html
templates/offer.html
templates/booking.html
templates/import_customers.html
templates/import_result.html
static/*
requirements.txt

RENDER ENVIRONMENT VARIABLES
----------------------------
EMPTY_CHAIR_SESSION_SECRET=<long random secret>
EMPTY_CHAIR_BASE_URL=https://YOUR-APP.onrender.com

For real email:
RESEND_API_KEY=<your Resend API key>
EMPTY_CHAIR_EMAIL_FROM=Empty Chair <you@your-verified-domain.com>

Existing variables still work:
DATABASE_URL
EMPTY_CHAIR_DB
EMPTY_CHAIR_DEMO_MODE
TWILIO_ACCOUNT_SID
TWILIO_AUTH_TOKEN
TWILIO_FROM_NUMBER

IMPORTANT
---------
Set EMPTY_CHAIR_SESSION_SECRET on Render before production use.

If EMPTY_CHAIR_DEMO_MODE=true and RESEND_API_KEY is not set,
emails print to the server log instead of being sent.

No new Python package is required for the email sender or password hashing.
SessionMiddleware comes from Starlette, which FastAPI already depends on.
"""
(out_dir / "SETUP.txt").write_text(setup_text)

# ------------------------------------------------------------
# Add optional dashboard logout snippet
# ------------------------------------------------------------
logout_snippet = """Add this anywhere appropriate in dashboard.html:

<form method="post" action="/logout">
    <button type="submit">Log out</button>
</form>

The dashboard now receives:
    user
    shop
    artists
    openings
    recovered
    completed
    total_openings
    customer_count
    demo_mode
"""
(out_dir / "DASHBOARD_LOGOUT_SNIPPET.txt").write_text(logout_snippet)

# ------------------------------------------------------------
# Basic syntax check
# ------------------------------------------------------------
import py_compile
py_compile.compile(str(app_path), doraise=True)

# zip
zip_path = Path("/mnt/data/empty-chair-auth-v0.7.0.zip")
with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
    for p in out_dir.rglob("*"):
        if p.is_file():
            z.write(p, p.relative_to(out_dir))

print(f"Created: {app_path}")
print(f"Created: {zip_path}")
print(f"app.py lines: {len(src.splitlines())}")
print("Syntax check: PASSED")
