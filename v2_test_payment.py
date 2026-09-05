"""Explicit opt-in no-charge simulator for Empty Chair 2.0 testing."""
import os
from fastapi.responses import RedirectResponse
import v2_app as core

TEST_PAYMENT_ENABLED = os.getenv("EMPTY_CHAIR_TEST_PAYMENT_ENABLED", "false").lower() == "true"


def _real_payment_available(artist):
    methods = set((artist.get("payment_methods") or "").split(","))
    square = bool(({"cashapp", "card"} & methods) and core.SQUARE_APP_ID and core.SQUARE_LOCATION_ID and core.SQUARE_ACCESS_TOKEN)
    venmo = bool("venmo" in methods and core.PAYPAL_CLIENT_ID and core.PAYPAL_CLIENT_SECRET)
    return square or venmo


def _live_pay_page(token):
    offer = core.one("SELECT * FROM offers WHERE token=?", (token,))
    if not offer or offer["status"] != "HOLDING": return RedirectResponse(f"/o/{token}")
    opening = core.one("SELECT * FROM openings WHERE id=?", (offer["opening_id"],))
    artist = core.one("SELECT * FROM artists WHERE id=?", (opening["artist_id"],))
    methods = set((artist["payment_methods"] or "").split(",")); controls=[]; js=""; head=""
    if ({"cashapp", "card"} & methods) and core.SQUARE_APP_ID and core.SQUARE_LOCATION_ID and core.SQUARE_ACCESS_TOKEN:
        head=f'<script src="{core.SQUARE_JS}"></script>'
        if "cashapp" in methods: controls.append('<div id="cashapp"></div>')
        if "card" in methods: controls.append('<div id="card"></div><button id="card-pay" type="button">CARD</button>')
        cash=f'''const pr=payments.paymentRequest({{countryCode:'US',currencyCode:'USD',total:{{amount:amount.toFixed(2),label:'Deposit'}}}});const cap=await payments.cashAppPay(pr,{{redirectURL:location.href,referenceId:{core.json.dumps(offer['id'])}}});cap.addEventListener('ontokenization',e=>{{if(e.detail.tokenResult?.status==='OK')sendToken(e.detail.tokenResult.token)}});await cap.attach('#cashapp');''' if "cashapp" in methods else ""
        card='''const card=await payments.card();await card.attach('#card');document.getElementById('card-pay').onclick=async()=>{const result=await card.tokenize();if(result.status==='OK')sendToken(result.token);};''' if "card" in methods else ""
        js=f'''<script>(async()=>{{const payments=Square.payments({core.json.dumps(core.SQUARE_APP_ID)},{core.json.dumps(core.SQUARE_LOCATION_ID)});const amount={opening['deposit_cents']/100:.2f};async function sendToken(source){{const r=await fetch('/o/{token}/square',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{source_id:source}})}});const j=await r.json();if(j.redirect)location.href=j.redirect;else alert(j.error||'Payment did not land.');}}{cash}{card}}})().catch(e=>console.error(e));</script>'''
    if "venmo" in methods and core.PAYPAL_CLIENT_ID and core.PAYPAL_CLIENT_SECRET: controls.append(f'<a class="button" href="/o/{token}/venmo">VENMO</a>')
    if not controls:
        if TEST_PAYMENT_ENABLED: controls.append(f'<form method="post" action="/o/{token}/test-complete"><button type="submit">TEST PAYMENT</button></form><p class="dim center">TEST MODE // NO MONEY MOVES</p>')
        else: controls.append('<div class="error">PAYMENT CONNECTION REQUIRED.</div>')
    return core.page("Payment", f'''<div class="center"><h1>LOCK IT IN.</h1><p class="big">{core.fmt_money(opening['deposit_cents'])}</p></div><div class="stack">{"".join(controls)}</div><p class="dim center">applied to your tattoo.</p>''', script=js, head=head)

core.app.router.routes[:] = [route for route in core.app.router.routes if not (getattr(route,"path",None)=="/o/{token}/pay" and "GET" in (getattr(route,"methods",set()) or set()))]

@core.app.get("/o/{token}/pay")
def pay_page(token: str): return _live_pay_page(token)

@core.app.post("/o/{token}/test-complete")
def test_complete(token: str):
    offer=core.one("SELECT * FROM offers WHERE token=?",(token,))
    if not TEST_PAYMENT_ENABLED: return RedirectResponse(f"/o/{token}/pay",status_code=303)
    if not offer or offer["status"]!="HOLDING": return RedirectResponse(f"/o/{token}",status_code=303)
    opening=core.one("SELECT * FROM openings WHERE id=?",(offer["opening_id"],)); artist=core.one("SELECT * FROM artists WHERE id=?",(opening["artist_id"],))
    if _real_payment_available(artist): return RedirectResponse(f"/o/{token}/pay",status_code=303)
    core.event("payment.test",artist["id"],{"opening_id":opening["id"],"offer_id":offer["id"],"amount_cents":opening["deposit_cents"]}); core.finalize_booking(offer,"test",None)
    return RedirectResponse(f"/o/{token}/yours",status_code=303)

print(f"Empty Chair 2.0 test payment enabled={TEST_PAYMENT_ENABLED}",flush=True)
