from fastapi import Form, Request
from fastapi.responses import RedirectResponse

import app as core
from demand_engine import register_demand_engine
import consultation_mms_runtime  # noqa: F401
import concierge_sms  # noqa: F401
import digital_consultations_runtime  # noqa: F401
import consultations_experience  # noqa: F401
import consultation_quotes  # noqa: F401
import quote_deposit_runtime_fix  # noqa: F401
import consultation_post_payment  # noqa: F401
import consultation_revisions  # noqa: F401

app = core.app

# Demand Graph is registered here because this module is imported by the explicit
# production bootstrap after core.app and its database/auth helpers are ready.
register_demand_engine(
    app=app,
    templates=core.templates,
    connect=core.connect,
    db_execute=core.db_execute,
    db_fetchone=core.db_fetchone,
    db_fetchall=core.db_fetchall,
    login_required_redirect=core.login_required_redirect,
    now_iso=core.now_iso,
)


@app.post("/settings/test-sms")
def send_test_sms_delivery(
    request: Request,
    phone: str = Form(...),
):
    user, redirect = core.login_required_redirect(request)
    if redirect:
        return redirect

    phone = phone.strip()
    if not phone:
        return RedirectResponse(
            "/settings?test_sms=invalid_number",
            status_code=303,
        )

    if not all(
        [
            core.TWILIO_ACCOUNT_SID,
            core.TWILIO_AUTH_TOKEN,
            core.TWILIO_FROM_NUMBER,
        ]
    ):
        return RedirectResponse(
            "/settings?test_sms=not_configured",
            status_code=303,
        )

    try:
        client = core.Client(
            core.TWILIO_ACCOUNT_SID,
            core.TWILIO_AUTH_TOKEN,
        )
        client.messages.create(
            body=(
                "Empty Chair test: SMS delivery is working. "
                "Your studio is ready to send text offers."
            ),
            from_=core.TWILIO_FROM_NUMBER,
            to=phone,
        )
        core.event(
            "sms.test_sent",
            "shop",
            user["shop_id"],
            phone,
        )
        result = "sent"
    except Exception as exc:
        core.event(
            "sms.test_failed",
            "shop",
            user["shop_id"],
            str(exc),
        )
        result = "failed"

    return RedirectResponse(
        f"/settings?test_sms={result}",
        status_code=303,
    )
