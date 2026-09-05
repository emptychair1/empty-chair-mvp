"""Rare-use settings UI for the otherwise headless Empty Chair 2.0 product."""
from fastapi import Form, Request
from fastapi.responses import RedirectResponse
import html
import os
import v2_app as core

MONTHLY_PRICE = os.getenv("EMPTY_CHAIR_MONTHLY_PRICE", "").strip()
YEARLY_PRICE = os.getenv("EMPTY_CHAIR_YEARLY_PRICE", "").strip()
MONTHLY_URL = os.getenv("EMPTY_CHAIR_SUBSCRIBE_MONTHLY_URL", "").strip()
YEARLY_URL = os.getenv("EMPTY_CHAIR_SUBSCRIBE_YEARLY_URL", "").strip()
MANAGE_URL = os.getenv("EMPTY_CHAIR_MANAGE_SUBSCRIPTION_URL", "").strip()
CANCEL_URL = os.getenv("EMPTY_CHAIR_CANCEL_SUBSCRIPTION_URL", "").strip()


def _artist_or_setup(request: Request):
    return core.current_artist(request)


def _price(value: str, fallback: str) -> str:
    return html.escape(value or fallback)


def _subscription_button(label: str, url: str) -> str:
    if url:
        return f'<a class="button" href="{html.escape(url, quote=True)}">{html.escape(label)}</a>'
    return f'<div class="button quiet">{html.escape(label)} // BILLING NOT CONNECTED</div>'


@core.app.get("/settings")
def settings_home(request: Request):
    artist = _artist_or_setup(request)
    if not artist: return RedirectResponse("/setup")
    acct = core.one("SELECT * FROM calendar_accounts WHERE artist_id=?", (artist["id"],))
    client_count = core.one("SELECT COUNT(*) AS n FROM clients WHERE artist_id=?", (artist["id"],))["n"]
    calendar_label = (acct.get("provider") or "not connected").upper() if acct else "NOT CONNECTED"
    methods = ", ".join(m.upper() for m in (artist.get("payment_methods") or "").split(",") if m) or "NOT SET"
    return core.page("Settings", f'''<h1>SETTINGS</h1><p class="dim">Rare adjustments. Empty Chair stays out of your way.</p><div class="settings-list"><a class="settings-row" href="/settings/calendar"><span>CALENDAR<small>{html.escape(calendar_label)}</small></span><span>›</span></a><a class="settings-row" href="/settings/deposits"><span>DEPOSITS<small>{core.fmt_money(int(artist['deposit_cents']))} default // {core.fmt_money(int(artist['average_value_cents']))} avg</small></span><span>›</span></a><a class="settings-row" href="/settings/clients"><span>CLIENTS<small>{int(client_count)} ready</small></span><span>›</span></a><a class="settings-row" href="/settings/payments"><span>PAYMENT METHODS<small>{html.escape(methods)}</small></span><span>›</span></a><a class="settings-row" href="/settings/subscription"><span>SUBSCRIPTION<small>plan + billing</small></span><span>›</span></a><a class="settings-row" href="/settings/account"><span>ACCOUNT<small>{html.escape(artist['name'])}</small></span><span>›</span></a></div><div class="space"></div><a class="button quiet" href="/">DONE</a>''')


@core.app.get("/settings/calendar")
def settings_calendar(request: Request):
    artist = _artist_or_setup(request)
    if not artist: return RedirectResponse("/setup")
    acct = core.one("SELECT * FROM calendar_accounts WHERE artist_id=?", (artist["id"],))
    provider = (acct.get("provider") or "calendar").upper() if acct else "NO CALENDAR"
    detail = "CONNECTED [✓]" if acct else "NOT CONNECTED"
    return core.page("Calendar Settings", f'''<h1>CALENDAR</h1><p class="bright">{html.escape(provider)}</p><p>{detail}</p><p class="dim">Your existing calendar remains the source of truth.</p><div class="stack"><a class="button" href="/setup/calendar">CHANGE / RECONNECT</a><a class="button quiet" href="/settings">BACK</a></div>''')


@core.app.get("/settings/deposits")
def settings_deposits(request: Request):
    artist = _artist_or_setup(request)
    if not artist: return RedirectResponse("/setup")
    return core.page("Deposit Settings", f'''<h1>DEPOSITS</h1><form method="post" class="stack"><label>default deposit<input type="number" name="deposit" min="1" step="1" value="{int(artist['deposit_cents'])//100}" required></label><label>average appointment value<input type="number" name="average" min="1" step="1" value="{int(artist['average_value_cents'])//100}" required></label><button>SAVE</button></form><div class="space"></div><a class="button quiet" href="/settings">BACK</a>''')


@core.app.post("/settings/deposits")
def settings_deposits_save(request: Request, deposit: int = Form(...), average: int = Form(...)):
    artist = _artist_or_setup(request)
    if not artist: return RedirectResponse("/setup")
    core.run("UPDATE artists SET deposit_cents=?,average_value_cents=?,updated_at=? WHERE id=?", (deposit * 100, average * 100, core.utcnow(), artist["id"]))
    core.event("settings.deposits.updated", artist["id"], {"deposit_cents": deposit * 100, "average_value_cents": average * 100})
    return RedirectResponse("/settings", status_code=303)


@core.app.get("/settings/payments")
def settings_payments(request: Request):
    artist = _artist_or_setup(request)
    if not artist: return RedirectResponse("/setup")
    selected = set((artist.get("payment_methods") or "").split(","))
    checked = lambda name: " checked" if name in selected else ""
    return core.page("Payment Settings", f'''<h1>PAYMENT METHODS</h1><p class="dim">Choose what customers may use when payment connections are available.</p><form method="post" class="stack"><label><input type="checkbox" name="cashapp" value="1"{checked('cashapp')}> CASH APP</label><label><input type="checkbox" name="venmo" value="1"{checked('venmo')}> VENMO</label><label><input type="checkbox" name="card" value="1"{checked('card')}> CARD</label><button>SAVE</button></form><div class="space"></div><a class="button quiet" href="/settings">BACK</a>''')


@core.app.post("/settings/payments")
def settings_payments_save(request: Request, cashapp: str | None = Form(None), venmo: str | None = Form(None), card: str | None = Form(None)):
    artist = _artist_or_setup(request)
    if not artist: return RedirectResponse("/setup")
    methods = [name for name, value in (("cashapp", cashapp), ("venmo", venmo), ("card", card)) if value] or ["card"]
    core.run("UPDATE artists SET payment_methods=?,updated_at=? WHERE id=?", (",".join(methods), core.utcnow(), artist["id"]))
    core.event("settings.payment_methods.updated", artist["id"], {"methods": methods})
    return RedirectResponse("/settings", status_code=303)


@core.app.get("/settings/clients")
def settings_clients(request: Request):
    artist = _artist_or_setup(request)
    if not artist: return RedirectResponse("/setup")
    count = core.one("SELECT COUNT(*) AS n FROM clients WHERE artist_id=?", (artist["id"],))["n"]
    return core.page("Client Settings", f'''<h1>CLIENTS</h1><p class="big">{int(count)}</p><p class="dim">ready for short-notice offers</p><div class="stack"><a class="button" href="/setup/clients">ADD / IMPORT CLIENTS</a><a class="button quiet" href="/settings">BACK</a></div>''')


@core.app.get("/settings/subscription")
def settings_subscription(request: Request):
    artist = _artist_or_setup(request)
    if not artist: return RedirectResponse("/setup")
    manage = f'<a class="button quiet" href="{html.escape(MANAGE_URL, quote=True)}">MANAGE SUBSCRIPTION</a>' if MANAGE_URL else ''
    cancel = f'<a class="button quiet" href="{html.escape(CANCEL_URL, quote=True)}">CANCEL SUBSCRIPTION</a>' if CANCEL_URL else '<div class="button quiet">CANCEL SUBSCRIPTION // BILLING NOT CONNECTED</div>'
    return core.page("Subscription", f'''<h1>SUBSCRIPTION</h1><p class="dim">Keep Empty Chair armed. Choose the billing cadence that fits you.</p><div class="stack"><div class="error"><p>MONTHLY</p><p class="big">{_price(MONTHLY_PRICE, 'PRICE NOT SET')}</p><p class="dim">cancel anytime</p>{_subscription_button('CHOOSE MONTHLY', MONTHLY_URL)}</div><div class="error"><p>YEARLY</p><p class="big">{_price(YEARLY_PRICE, 'PRICE NOT SET')}</p><p class="dim">one annual payment</p>{_subscription_button('CHOOSE YEARLY', YEARLY_URL)}</div>{manage}{cancel}<a class="button quiet" href="/settings">BACK</a></div>''')


@core.app.get("/settings/account")
def settings_account(request: Request):
    artist = _artist_or_setup(request)
    if not artist: return RedirectResponse("/setup")
    return core.page("Account Settings", f'''<h1>ACCOUNT</h1><div class="status"><span>name</span><span>{html.escape(artist['name'])}</span></div><div class="status"><span>mobile</span><span>{html.escape(artist['phone'])}</span></div><div class="status"><span>status</span><span>{html.escape(artist['setup_state'])}</span></div><div class="space"></div><a class="button" href="/settings/subscription">SUBSCRIPTION</a><p class="dim">Phone is the communication channel for Empty Chair.</p><a class="button quiet" href="/settings">BACK</a>''')

print("Empty Chair 2.0 settings UI loaded", flush=True)
