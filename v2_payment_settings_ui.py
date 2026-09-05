"""Payment connection controls for rare-use settings."""
from fastapi import Request
from fastapi.responses import RedirectResponse
import v2_app as core
import v2_artist_payments as payments

core.app.router.routes[:]=[r for r in core.app.router.routes if not (getattr(r,"path",None)=="/settings/payments" and "GET" in (getattr(r,"methods",set()) or set()))]

@core.app.get("/settings/payments")
def payment_settings(request:Request):
    artist=core.current_artist(request)
    if not artist:return RedirectResponse("/setup")
    selected=set((artist.get("payment_methods") or "").split(","));checked=lambda name:" checked" if name in selected else ""
    square=payments.square_account(artist["id"]);square_connected=bool(square and square.get("access_token") and square.get("location_id"));square_state="CONNECTED [✓]" if square_connected else "NOT CONNECTED"
    square_state_html=f'<span class="success">{square_state}</span>' if square_connected else f'<span>{square_state}</span>'
    square_action='<a class="button quiet" href="/settings/payments/square/connect">RECONNECT SQUARE</a>' if square_connected else '<a class="button" href="/settings/payments/square/connect">CONNECT SQUARE</a>'
    paypal_state="PLATFORM CONFIGURED" if core.PAYPAL_CLIENT_ID and core.PAYPAL_CLIENT_SECRET else "PARTNER CONNECTION PENDING"
    return core.page("Payment Settings",f'''<h1>PAYMENTS</h1><div class="status"><span>SQUARE</span>{square_state_html}</div>{square_action}<p class="dim">Square powers Cash App and card deposits. Deposits use your connected artist account.</p><div class="space"></div><div class="status"><span>VENMO</span><span>{paypal_state}</span></div><p class="dim">Venmo requires PayPal seller-partner onboarding before deposits can be routed to each artist.</p><div class="space"></div><h2>CUSTOMER OPTIONS</h2><form method="post" class="stack"><label><input type="checkbox" name="cashapp" value="1"{checked('cashapp')}> CASH APP</label><label><input type="checkbox" name="venmo" value="1"{checked('venmo')}> VENMO</label><label><input type="checkbox" name="card" value="1"{checked('card')}> CARD</label><button>SAVE</button></form><div class="space"></div><a class="button quiet" href="/settings">BACK</a>''')

print("Empty Chair 2.0 payment settings UI loaded",flush=True)
