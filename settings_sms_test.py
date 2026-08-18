from fastapi import Form, Request
from fastapi.responses import RedirectResponse

import app as core

app = core.app


@app.post("/settings/test-sms")
def test_sms_delivery(
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
