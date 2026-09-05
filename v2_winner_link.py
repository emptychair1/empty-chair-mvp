"""Keep a winning customer's original Empty Chair link useful after booking."""
from fastapi.responses import RedirectResponse
import v2_app as core

# /o/{token} is registered by v2_app before extension modules load. Replace that GET
# route so a winning offer always resolves to its durable YOURS confirmation page.
_original_offer_page = core.offer_page


def offer_page_with_winner_redirect(token: str):
    offer = core.one("SELECT * FROM offers WHERE token=?", (token,))
    if offer and offer.get("status") == "YOURS":
        return RedirectResponse(f"/o/{token}/yours", status_code=303)
    return _original_offer_page(token)


for index, route in enumerate(list(core.app.routes)):
    if getattr(route, "path", None) == "/o/{token}" and "GET" in (getattr(route, "methods", set()) or set()):
        core.app.routes.pop(index)
        break

core.app.get("/o/{token}")(offer_page_with_winner_redirect)

print("Empty Chair 2.0 winner links stay YOURS", flush=True)
