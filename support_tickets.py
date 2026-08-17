import html
import json
import os
import urllib.error
import urllib.parse
import urllib.request
import uuid

from fastapi import Form, HTTPException, Request
from fastapi.responses import HTMLResponse


TRELLO_API_URL = "https://api.trello.com/1/cards"
ALLOWED_CATEGORIES = {
    "Account",
    "Billing",
    "Calendar",
    "Deliveries",
    "Bookings",
    "Bug",
    "Feature request",
    "Other",
}
ALLOWED_PRIORITIES = {
    "Low",
    "Normal",
    "High",
    "Urgent",
}


def trello_is_configured():
    return all(
        (
            os.getenv("TRELLO_API_KEY"),
            os.getenv("TRELLO_API_TOKEN"),
            os.getenv("TRELLO_SUPPORT_LIST_ID"),
        )
    )


def create_trello_card(ticket, user, shop):
    if not trello_is_configured():
        return None

    title = (
        f"[{ticket['priority']}] {ticket['subject']} "
        f"— {shop['name']}"
    )

    description = "\n".join(
        (
            f"Empty Chair ticket: {ticket['id']}",
            f"Category: {ticket['category']}",
            f"Priority: {ticket['priority']}",
            f"Studio: {shop['name']} ({shop['id']})",
            f"Submitted by: {user['name']} <{user['email']}>",
            "",
            ticket["description"],
        )
    )

    payload = urllib.parse.urlencode(
        {
            "key": os.environ["TRELLO_API_KEY"],
            "token": os.environ["TRELLO_API_TOKEN"],
            "idList": os.environ["TRELLO_SUPPORT_LIST_ID"],
            "name": title[:16384],
            "desc": description,
            "pos": "top",
        }
    ).encode("utf-8")

    request = urllib.request.Request(
        TRELLO_API_URL,
        data=payload,
        method="POST",
        headers={
            "Accept": "application/json",
            "Content-Type": "application/x-www-form-urlencoded",
        },
    )

    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            result = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(
            f"Trello rejected the ticket ({exc.code}): {detail[:300]}"
        ) from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(
            f"Trello could not be reached: {exc.reason}"
        ) from exc

    card_id = result.get("id")
    card_url = result.get("url")

    if not card_id:
        raise RuntimeError("Trello returned an invalid card response.")

    return {
        "id": card_id,
        "url": card_url,
    }


def register_support_routes(
    app,
    templates,
    connect,
    db_execute,
    db_fetchone,
    db_fetchall,
    get_current_user,
    login_required_redirect,
    now_iso,
    send_email,
):
    @app.on_event("startup")
    def initialize_support_tickets():
        conn = connect()

        db_execute(
            conn,
            """
            CREATE TABLE IF NOT EXISTS support_tickets (
                id TEXT PRIMARY KEY,
                shop_id TEXT NOT NULL,
                user_id TEXT NOT NULL,
                subject TEXT NOT NULL,
                category TEXT NOT NULL,
                priority TEXT NOT NULL,
                description TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'SUBMITTED',
                trello_card_id TEXT,
                trello_card_url TEXT,
                trello_error TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(shop_id) REFERENCES shops(id),
                FOREIGN KEY(user_id) REFERENCES users(id)
            )
            """,
        )

        db_execute(
            conn,
            """
            CREATE INDEX IF NOT EXISTS idx_support_tickets_shop
            ON support_tickets(shop_id, created_at)
            """,
        )

        conn.commit()
        conn.close()

    def load_support_page(request, user, submitted=None, error=None):
        conn = connect()

        shop = db_fetchone(
            conn,
            """
            SELECT *
            FROM shops
            WHERE id = ?
            LIMIT 1
            """,
            (user["shop_id"],),
        )

        tickets = db_fetchall(
            conn,
            """
            SELECT *
            FROM support_tickets
            WHERE shop_id = ?
            ORDER BY created_at DESC
            LIMIT 25
            """,
            (user["shop_id"],),
        )

        conn.close()

        return templates.TemplateResponse(
            request=request,
            name="support.html",
            context={
                "user": user,
                "shop": shop,
                "tickets": tickets,
                "submitted": submitted,
                "error": error,
                "email_configured": bool(os.getenv("RESEND_API_KEY")),
                "categories": sorted(ALLOWED_CATEGORIES),
                "priorities": ("Normal", "High", "Urgent", "Low"),
            },
        )

    @app.get(
        "/support",
        response_class=HTMLResponse,
    )
    def support_page(request: Request):
        user, redirect = login_required_redirect(request)

        if redirect:
            return redirect

        return load_support_page(request, user)

    @app.post(
        "/support",
        response_class=HTMLResponse,
    )
    def submit_support_ticket(
        request: Request,
        subject: str = Form(...),
        category: str = Form("Other"),
        priority: str = Form("Normal"),
        description: str = Form(...),
    ):
        user, redirect = login_required_redirect(request)

        if redirect:
            return redirect

        subject = subject.strip()
        description = description.strip()

        if category not in ALLOWED_CATEGORIES:
            category = "Other"

        if priority not in ALLOWED_PRIORITIES:
            priority = "Normal"

        if len(subject) < 3 or len(subject) > 160:
            return load_support_page(
                request,
                user,
                error="Subject must be between 3 and 160 characters.",
            )

        if len(description) < 10 or len(description) > 10000:
            return load_support_page(
                request,
                user,
                error="Description must be between 10 and 10,000 characters.",
            )

        conn = connect()

        shop = db_fetchone(
            conn,
            """
            SELECT *
            FROM shops
            WHERE id = ?
            LIMIT 1
            """,
            (user["shop_id"],),
        )

        if not shop:
            conn.close()
            raise HTTPException(404, "Studio not found.")

        ticket_id = f"ticket_{uuid.uuid4().hex[:12]}"
        timestamp = now_iso()

        ticket = {
            "id": ticket_id,
            "subject": subject,
            "category": category,
            "priority": priority,
            "description": description,
        }

        db_execute(
            conn,
            """
            INSERT INTO support_tickets(
                id,
                shop_id,
                user_id,
                subject,
                category,
                priority,
                description,
                status,
                created_at,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                ticket_id,
                user["shop_id"],
                user["id"],
                subject,
                category,
                priority,
                description,
                "SUBMITTED",
                timestamp,
                timestamp,
            ),
        )

        conn.commit()
        conn.close()

        support_email = os.getenv(
            "EMPTY_CHAIR_SUPPORT_EMAIL",
            "daniels.joshua100@gmail.com",
        ).strip()

        safe_ticket_id = html.escape(ticket_id)
        safe_shop_name = html.escape(str(shop["name"]))
        safe_shop_id = html.escape(str(shop["id"]))
        safe_user_name = html.escape(str(user["name"]))
        safe_user_email = html.escape(str(user["email"]))
        safe_category = html.escape(category)
        safe_priority = html.escape(priority)
        safe_subject = html.escape(subject)
        safe_description = html.escape(description).replace(
            "\n",
            "<br>",
        )

        email_html = f"""
        <h2>New Empty Chair support ticket</h2>
        <p><strong>Ticket:</strong> {safe_ticket_id}</p>
        <p><strong>Studio:</strong> {safe_shop_name} ({safe_shop_id})</p>
        <p><strong>Submitted by:</strong> {safe_user_name} &lt;{safe_user_email}&gt;</p>
        <p><strong>Category:</strong> {safe_category}</p>
        <p><strong>Priority:</strong> {safe_priority}</p>
        <p><strong>Subject:</strong> {safe_subject}</p>
        <hr>
        <p>{safe_description}</p>
        """

        email_sent = send_email(
            support_email,
            f"[{priority}] Empty Chair support: {subject}",
            email_html,
        )

        status = (
            "EMAIL_SENT"
            if email_sent
            else "EMAIL_FAILED"
        )
        delivery_error = (
            None
            if email_sent
            else "Support notification email could not be sent."
        )

        conn = connect()

        db_execute(
            conn,
            """
            UPDATE support_tickets
            SET
                status = ?,
                trello_card_id = ?,
                trello_card_url = ?,
                trello_error = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (
                status,
                None,
                None,
                delivery_error,
                now_iso(),
                ticket_id,
            ),
        )

        conn.commit()
        conn.close()

        return load_support_page(
            request,
            user,
            submitted={
                "id": ticket_id,
                "status": status,
                "trello_card_url": None,
            },
        )
