"""Temporary no-charge simulator for Empty Chair 2.0 end-to-end testing."""
from fastapi.responses import RedirectResponse
import v2_app as core

_original_pay_page = core.pay_page


def _real_payment_available(artist):
    methods = set((artist.get("payment_methods") or "").split(","))
    square = bool(({"cashapp", "card"} & methods) and core.SQUARE_APP_ID and core.SQUARE_LOCATION_ID and core.SQUARE_ACCESS_TOKEN)
    venmo = bool("venmo" in methods and core.PAYPAL_CLIENT_ID and core.PAYPAL_CLIENT_SECRET)
    return square or venmo


def _test_page(token):
    offer = core.one("SELECT * FROM offers WHERE token=?", (token,))
    if not offer or offer["status"] != "HOLDING":
        return RedirectResponse(f"/o/{token}")
    opening = core.one("SELECT * FROM openings WHERE id=?", (offer["opening_id"],))
    return core.page("Payment", f'''<div class="center"><h1>LOCK IT IN.</h1><p class="big">{core.fmt_money(opening['deposit_cents'])}</p></div><div class="stack"><form method="post" action="/o/{token}/test-complete"><button type="submit">TEST PAYMENT</button></form></div><p class="dim center">TEST MODE // NO MONEY MOVES</p>''')


@core.app.post("/o/{token}/test-complete")
def test_complete(token):
    offer = core.one("SELECT * FROM offers WHERE token=?", (token,))
    if not offer or offer["status"] != "HOLDING":
        return RedirectResponse(f"/o/{token}", status_code=303)
    opening = core.one("SELECT * FROM openings WHERE id=?", (offer["opening_id"],))
    artist = core.one("SELECT * FROM artists WHERE id=?", (opening["artist_id"],))
    if _real_payment_available(artist):
        return RedirectResponse(f"/o/{token}/pay", status_code=303)
    core.event("payment.test", artist["id"], {"opening_id": opening["id"], "offer_id": offer["id"], "amount_cents": opening["deposit_cents"]})
    core.finalize_booking(offer, "test", None)
    return RedirectResponse(f"/o/{token}/yours", status_code=303)


def _pay_page_with_test(token):
    offer = core.one("SELECT * FROM offers WHERE token=?", (token,))
    if not offer or offer["status"] != "HOLDING":
        return RedirectResponse(f"/o/{token}")
    opening = core.one("SELECT * FROM openings WHERE id=?", (offer["opening_id"],))
    artist = core.one("SELECT * FROM artists WHERE id=?", (opening["artist_id"],))
    return _original_pay_page(token) if _real_payment_available(artist) else _test_page(token)


for route in core.app.routes:
    if getattr(route, "path", None) == "/o/{token}/pay" and "GET" in (getattr(route, "methods", set()) or set()):
        route.endpoint = _pay_page_with_test
        break

print("Empty Chair 2.0 test payment path enabled", flush=True)
