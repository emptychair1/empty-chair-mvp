"""Rare-use settings UI for the otherwise headless Empty Chair 2.0 product."""
from fastapi import Form, Request
from fastapi.responses import RedirectResponse
import html, os
import v2_app as core
import v2_entitlement as entitlement
MONTHLY_PRICE=os.getenv("EMPTY_CHAIR_MONTHLY_PRICE","").strip();YEARLY_PRICE=os.getenv("EMPTY_CHAIR_YEARLY_PRICE","").strip()
MANAGE_URL=os.getenv("EMPTY_CHAIR_MANAGE_SUBSCRIPTION_URL","").strip()

def _artist_or_setup(request):return core.current_artist(request)
def _price(value,fallback):return html.escape(value or fallback)

@core.app.get("/settings")
def settings_home(request:Request):
    artist=_artist_or_setup(request)
    if not artist:return RedirectResponse("/setup")
    acct=core.one("SELECT * FROM calendar_accounts WHERE artist_id=?",(artist["id"],));client_count=core.one("SELECT COUNT(*) AS n FROM clients WHERE artist_id=?",(artist["id"],))["n"]
    calendar_label=(acct.get("provider") or "not connected").upper() if acct else "NOT CONNECTED";methods=", ".join(m.upper() for m in (artist.get("payment_methods") or "").split(",") if m) or "NOT SET"
    return core.page("Settings",f'''<h1>SETTINGS</h1><p class="dim">Rare adjustments. Empty Chair stays out of your way.</p><div class="settings-list"><a class="settings-row" href="/settings/calendar"><span>CALENDAR<small>{html.escape(calendar_label)}</small></span><span>›</span></a><a class="settings-row" href="/settings/deposits"><span>DEPOSITS<small>{core.fmt_money(int(artist['deposit_cents']))} default // {core.fmt_money(int(artist['average_value_cents']))} avg</small></span><span>›</span></a><a class="settings-row" href="/settings/clients"><span>CLIENTS<small>{int(client_count)} ready</small></span><span>›</span></a><a class="settings-row" href="/settings/payments"><span>PAYMENT METHODS<small>{html.escape(methods)}</small></span><span>›</span></a><a class="settings-row" href="/settings/subscription"><span>SUBSCRIPTION<small>plan + billing</small></span><span>›</span></a><a class="settings-row" href="/settings/account"><span>ACCOUNT<small>{html.escape(artist['name'])}</small></span><span>›</span></a></div>''')

@core.app.get("/settings/calendar")
def calendar(request:Request):
    artist=_artist_or_setup(request)
    if not artist:return RedirectResponse("/setup")
    acct=core.one("SELECT * FROM calendar_accounts WHERE artist_id=?",(artist["id"],));provider=(acct.get("provider") or "calendar").upper() if acct else "NO CALENDAR";detail="CONNECTED [✓]" if acct else "NOT CONNECTED"
    return core.page("Calendar",f'<h1>CALENDAR</h1><p class="bright">{html.escape(provider)}</p><p>{detail}</p><a class="button" href="/setup/calendar">CHANGE / RECONNECT</a>')

@core.app.get("/settings/deposits")
def deposits(request:Request):
    a=_artist_or_setup(request)
    if not a:return RedirectResponse("/setup")
    return core.page("Deposits",f'''<h1>DEPOSITS</h1><form method="post" class="stack"><label>default deposit<input type="number" name="deposit" min="1" value="{int(a['deposit_cents'])//100}"></label><label>average appointment value<input type="number" name="average" min="1" value="{int(a['average_value_cents'])//100}"></label><button>SAVE</button></form>''')
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
    n=core.one("SELECT COUNT(*) AS n FROM clients WHERE artist_id=?",(a["id"],))["n"];return core.page("Clients",f'<h1>CLIENTS</h1><p class="big">{n}</p><p class="dim">ready for short-notice offers</p><a class="button" href="/setup/clients">ADD / IMPORT CLIENTS</a>')

@core.app.get("/settings/subscription")
def subscription(request:Request):
    a=_artist_or_setup(request)
    if not a:return RedirectResponse("/setup")
    a=core.one("SELECT * FROM artists WHERE id=?",(a["id"],));s=entitlement.state(a)
    if s=="active":
        manage=f'<a class="button" href="{html.escape(MANAGE_URL,quote=True)}">MANAGE SUBSCRIPTION</a>' if MANAGE_URL else '<p class="bright">SUBSCRIPTION ACTIVE [✓]</p>'
        return core.page("Subscription",f'<h1>EMPTY CHAIR // ARMED</h1><p class="bright">PAYMENT ACTIVE [✓]</p>{manage}<a class="button quiet" href="/settings">BACK</a>',chair=True)
    trial=entitlement.trial_copy(a) if s=="trial" else "TRIAL ENDED // CHAIR DISARMED"
    return core.page("Subscription",f'''<h1>SUBSCRIPTION</h1><p class="bright">{trial}</p><p class="dim">Subscription payment happens here inside Empty Chair.</p><div class="stack"><div class="error"><p>MONTHLY</p><p class="big">{_price(MONTHLY_PRICE,'PRICE NOT SET')}</p><a class="button" href="/billing/subscribe/monthly">CHOOSE MONTHLY</a></div><div class="error"><p>YEARLY</p><p class="big">{_price(YEARLY_PRICE,'PRICE NOT SET')}</p><a class="button" href="/billing/subscribe/yearly">CHOOSE YEARLY</a></div></div>''',chair=True)

@core.app.get("/settings/account")
def account(request:Request):
    a=_artist_or_setup(request)
    if not a:return RedirectResponse("/setup")
    return core.page("Account",f'''<h1>ACCOUNT</h1><div class="status"><span>name</span><span>{html.escape(a['name'])}</span></div><div class="status"><span>mobile</span><span>{html.escape(a['phone'])}</span></div><a class="button" href="/settings/subscription">SUBSCRIPTION</a>''')
print("Empty Chair 2.0 settings UI loaded",flush=True)
