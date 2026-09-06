"""Rare-use settings UI for the otherwise headless Empty Chair 2.0 product."""
from fastapi import Form, Request
from fastapi.responses import RedirectResponse
import html, os
import v2_app as core
import v2_entitlement as entitlement
MANAGE_URL=os.getenv("EMPTY_CHAIR_MANAGE_SUBSCRIPTION_URL","").strip()

def _artist_or_setup(request):return core.current_artist(request)

def _count_clients(artist_id):
    try:
        row=core.one("SELECT COUNT(*) AS n FROM clients WHERE artist_id=?",(artist_id,))
        return int((row or {}).get("n") or 0)
    except Exception:return 0

def _calendar_account(artist_id):
    try:return core.one("SELECT * FROM calendar_accounts WHERE artist_id=?",(artist_id,))
    except Exception:return None

@core.app.get("/settings")
def settings_home(request:Request):
    artist=_artist_or_setup(request)
    if not artist:return RedirectResponse("/setup")
    acct=_calendar_account(artist["id"]);client_count=_count_clients(artist["id"])
    calendar_label=(acct.get("provider") or "not connected").upper() if acct else "NOT CONNECTED";methods=", ".join(m.upper() for m in (artist.get("payment_methods") or "").split(",") if m) or "NOT SET"
    return core.page("Settings",f'''<h1>SETTINGS</h1><p class="dim">Rare adjustments. Empty Chair stays out of your way.</p><div class="settings-list"><a class="settings-row" href="/settings/calendar"><span>CALENDAR<small>{html.escape(calendar_label)}</small></span><span>›</span></a><a class="settings-row" href="/settings/deposits"><span>DEPOSITS<small>{core.fmt_money(int(artist.get('deposit_cents') or 0))} default // {core.fmt_money(int(artist.get('average_value_cents') or 0))} avg</small></span><span>›</span></a><a class="settings-row" href="/settings/clients"><span>CLIENTS<small>{client_count} ready</small></span><span>›</span></a><a class="settings-row" href="/settings/payments"><span>PAYMENT METHODS<small>{html.escape(methods)}</small></span><span>›</span></a><a class="settings-row" href="/settings/subscription"><span>SUBSCRIPTION<small>$97 monthly</small></span><span>›</span></a><a class="settings-row" href="/settings/account"><span>ACCOUNT<small>{html.escape(artist.get('name') or '')}</small></span><span>›</span></a></div>''')

@core.app.get("/settings/calendar")
def calendar(request:Request):
    artist=_artist_or_setup(request)
    if not artist:return RedirectResponse("/setup")
    acct=_calendar_account(artist["id"]);provider=(acct.get("provider") or "calendar").upper() if acct else "NO CALENDAR";detail="CONNECTED [✓]" if acct else "NOT CONNECTED"
    return core.page("Calendar",f'<h1>CALENDAR</h1><p class="bright">{html.escape(provider)}</p><p>{detail}</p><a class="button" href="/setup/calendar">CHANGE / RECONNECT</a>')

@core.app.get("/settings/deposits")
def deposits(request:Request):
    a=_artist_or_setup(request)
    if not a:return RedirectResponse("/setup")
    return core.page("Deposits",f'''<h1>DEPOSITS</h1><form method="post" class="stack"><label>default deposit<input type="number" name="deposit" min="1" value="{int(a.get('deposit_cents') or 0)//100}"></label><label>average appointment value<input type="number" name="average" min="1" value="{int(a.get('average_value_cents') or 0)//100}"></label><button>SAVE</button></form>''')
@core.app.post("/settings/deposits")
def deposits_save(request:Request,deposit:int=Form(...),average:int=Form(...)):
    a=_artist_or_setup(request)
    if not a:return RedirectResponse("/setup")
    core.run("UPDATE artists SET deposit_cents=?,average_value_cents=?,updated_at=? WHERE id=?",(deposit*100,average*100,core.utcnow(),a["id"]));return RedirectResponse("/settings",303)

@core.app.get("/settings/payments")
def payments(request:Request):
    a=_artist_or_setup(request)
    if not a:return RedirectResponse("/setup")
    selected=set((a.get("payment_methods") or "").split(","));checked=lambda n:" checked" if n in selected else ""
    return core.page("Payment Settings",f'''<h1>PAYMENT METHODS</h1><form method="post" class="stack"><label><input type="checkbox" name="cashapp" value="1"{checked('cashapp')}> CASH APP</label><label><input type="checkbox" name="venmo" value="1"{checked('venmo')}> VENMO</label><label><input type="checkbox" name="card" value="1"{checked('card')}> CARD</label><button>SAVE</button></form>''')
@core.app.post("/settings/payments")
def payments_save(request:Request,cashapp:str|None=Form(None),venmo:str|None=Form(None),card:str|None=Form(None)):
    a=_artist_or_setup(request)
    if not a:return RedirectResponse("/setup")
    methods=[n for n,v in (("cashapp",cashapp),("venmo",venmo),("card",card)) if v] or ["card"];core.run("UPDATE artists SET payment_methods=?,updated_at=? WHERE id=?",(",".join(methods),core.utcnow(),a["id"]));return RedirectResponse("/settings",303)

@core.app.get("/settings/clients")
def clients(request:Request):
    a=_artist_or_setup(request)
    if not a:return RedirectResponse("/setup")
    n=_count_clients(a["id"]);return core.page("Clients",f'<h1>CLIENTS</h1><p class="big">{n}</p><p class="dim">ready for short-notice offers</p><a class="button" href="/setup/clients">ADD / IMPORT CLIENTS</a>')

@core.app.get("/settings/subscription")
def subscription(request:Request):
    a=_artist_or_setup(request)
    if not a:return RedirectResponse("/setup")
    a=core.one("SELECT * FROM artists WHERE id=?",(a["id"],)) or a;s=entitlement.state(a)
    # The completed $1 founder E2E marked this account square_test/active. That proves
    # entitlement but is not a real recurring subscription, so keep the production checkout
    # reachable until an actual Square subscription replaces it.
    founder_test=(a.get("subscription_provider") or "")=="square_test"
    if s=="active" and not founder_test:
        manage=f'<a class="button" href="{html.escape(MANAGE_URL,quote=True)}">MANAGE SUBSCRIPTION</a>' if MANAGE_URL else '<p class="bright">SUBSCRIPTION ACTIVE [✓]</p>'
        return core.page("Subscription",f'<h1>EMPTY CHAIR // ARMED</h1><p class="bright">PAYMENT ACTIVE [✓]</p><p>$97 / MONTH</p>{manage}<a class="button quiet" href="/settings">BACK</a>',chair=True)
    if founder_test:
        return core.page("Subscription",'''<div class="center"><h1>EMPTY CHAIR // BILLING TEST</h1><p class="bright">DAY-8 RE-ARM PROVEN [✓]</p><p class="big">$97 / MONTH</p><p class="dim">Final production subscription proof.</p><a class="button" href="/billing/subscribe/monthly">KEEP MY CHAIR COVERED</a></div>''',chair=True)
    trial=entitlement.trial_copy(a) if s=="trial" else "TRIAL ENDED // CHAIR DISARMED"
    return core.page("Subscription",f'''<div class="center"><h1>EMPTY CHAIR // {trial}</h1><p class="big">$97 / MONTH</p><p class="dim">Cancel anytime.</p><a class="button" href="/billing/subscribe/monthly">KEEP MY CHAIR COVERED</a></div>''',chair=True)

@core.app.get("/settings/account")
def account(request:Request):
    a=_artist_or_setup(request)
    if not a:return RedirectResponse("/setup")
    return core.page("Account",f'''<h1>ACCOUNT</h1><div class="status"><span>name</span><span>{html.escape(a.get('name') or '')}</span></div><div class="status"><span>mobile</span><span>{html.escape(a.get('phone') or '')}</span></div><a class="button" href="/settings/subscription">SUBSCRIPTION</a>''')
print("Empty Chair 2.0 settings UI loaded // one $97 monthly plan",flush=True)
