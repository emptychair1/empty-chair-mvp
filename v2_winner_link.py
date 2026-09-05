"""Keep winning and held customer links useful throughout the recovery flow."""
from fastapi.responses import RedirectResponse
import v2_app as core

# /o/{token} and /o/{token}/take are registered by v2_app before extension modules load.
# Replace the customer GET routes so durable winners stay on YOURS and an offer that is
# already HOLDING resumes at payment instead of looping back to the open-chair screen.
_original_offer_page = core.offer_page
_original_take_page = core.take_page


def offer_page_with_winner_redirect(token: str):
    offer = core.one("SELECT * FROM offers WHERE token=?", (token,))
    if offer and offer.get("status") == "YOURS":
        return RedirectResponse(f"/o/{token}/yours", status_code=303)
    return _original_offer_page(token)


def take_page_with_hold_resume(token: str):
    offer = core.one("SELECT * FROM offers WHERE token=?", (token,))
    if offer and offer.get("status") == "HOLDING":
        return RedirectResponse(f"/o/{token}/pay", status_code=303)
    return _original_take_page(token)


def _drop_get(path: str):
    for index, route in enumerate(list(core.app.routes)):
        if getattr(route, "path", None) == path and "GET" in (getattr(route, "methods", set()) or set()):
            core.app.routes.pop(index)
            return


_drop_get("/o/{token}")
_drop_get("/o/{token}/take")

core.app.get("/o/{token}")(offer_page_with_winner_redirect)
core.app.get("/o/{token}/take")(take_page_with_hold_resume)

print("Empty Chair 2.0 winner links stay YOURS // held offers resume payment", flush=True)
