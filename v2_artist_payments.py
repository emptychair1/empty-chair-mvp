"""Per-artist payment connections for Empty Chair 2.0.

Square OAuth routes deposits to the artist's own Square account. Venmo is intentionally
hidden from customer checkout until per-artist PayPal seller routing is production-ready.
"""
from __future__ import annotations
import json, os, urllib.parse, urllib.error
from datetime import datetime, timedelta, timezone
from fastapi import Request
from fastapi.responses import JSONResponse, RedirectResponse
import v2_app as core

SQUARE_CLIENT_SECRET=os.getenv("SQUARE_CLIENT_SECRET","").strip()
SQUARE_OAUTH_BASE="https://connect.squareupsandbox.com" if core.SQUARE_ENV=="sandbox" else "https://connect.squareup.com"

def ensure_schema():
    try:
        d=core.DB();d.execute("""CREATE TABLE IF NOT EXISTS artist_payment_accounts (artist_id TEXT NOT NULL,provider TEXT NOT NULL,merchant_id TEXT,location_id TEXT,access_token TEXT,refresh_token TEXT,token_expires_at TEXT,connected_at TEXT NOT NULL,PRIMARY KEY(artist_id,provider))""");d.commit();d.close()
    except Exception as exc:print(f"payment schema warning: {exc}",flush=True)

@core.app.on_event("startup")
def payment_schema_startup():ensure_schema()
ensure_schema()

def square_account(artist_id):
    try:return core.one("SELECT * FROM artist_payment_accounts WHERE artist_id=? AND provider='square'",(artist_id,))
    except Exception:return None

def square_token(acct):
    if not acct:return ""
    exp=acct.get("token_expires_at")
    try:
        if acct.get("access_token") and (not exp or datetime.fromisoformat(exp.replace("Z","+00:00"))>datetime.now(timezone.utc)+timedelta(days=1)):return acct["access_token"]
    except Exception:pass
    if not (acct.get("refresh_token") and SQUARE_CLIENT_SECRET):return acct.get("access_token") or ""
    data=core.http_json(f"{SQUARE_OAUTH_BASE}/oauth2/token","POST",{"client_id":core.SQUARE_APP_ID,"client_secret":SQUARE_CLIENT_SECRET,"grant_type":"refresh_token","refresh_token":acct["refresh_token"]},{"Square-Version":"2026-08-19"})
    token=data.get("access_token") or "";refresh=data.get("refresh_token") or acct["refresh_token"];expires=data.get("expires_at")
    core.run("UPDATE artist_payment_accounts SET access_token=?,refresh_token=?,token_expires_at=? WHERE artist_id=? AND provider='square'",(token,refresh,expires,acct["artist_id"]));return token

@core.app.get("/settings/payments/square/connect")
def square_connect(request:Request):
    artist=core.current_artist(request)
    if not artist:return RedirectResponse("/setup")
    if not (core.SQUARE_APP_ID and SQUARE_CLIENT_SECRET):return core.page("Square","<div class='error'>SQUARE CONNECTION IS NOT CONFIGURED YET.</div><a class='button' href='/settings/payments'>BACK</a>")
    params={"client_id":core.SQUARE_APP_ID,"scope":"MERCHANT_PROFILE_READ PAYMENTS_WRITE PAYMENTS_READ","session":"false","state":core.sign(artist["id"])}
    return RedirectResponse(f"{SQUARE_OAUTH_BASE}/oauth2/authorize?"+urllib.parse.urlencode(params))

@core.app.get("/settings/payments/square/callback")
def square_callback(code:str|None=None,state:str|None=None,error:str|None=None):
    aid=core.unsign(state)
    if not aid or error or not code:
        core.event("payment.square.oauth_failed",aid,{"stage":"callback","error":error or "invalid state/code"}) if aid else None
        return core.page("Square","<div class='error'>SQUARE CONNECTION WAS NOT COMPLETED.</div><a class='button' href='/settings/payments'>BACK</a>")
    try:
        data=core.http_json(f"{SQUARE_OAUTH_BASE}/oauth2/token","POST",{"client_id":core.SQUARE_APP_ID,"client_secret":SQUARE_CLIENT_SECRET,"code":code,"grant_type":"authorization_code"},{"Square-Version":"2026-08-19"})
        token=data.get("access_token") or "";merchant=data.get("merchant_id") or "";location=""
        if not token:raise RuntimeError("Square did not return an access token")
        locs=core.http_json(f"{core.SQUARE_BASE}/v2/locations",headers={"Authorization":f"Bearer {token}","Square-Version":"2026-08-19"}).get("locations",[])
        active=[x for x in locs if x.get("status")=="ACTIVE"]
        location=(active or locs or [{}])[0].get("id","")
        if not location:raise RuntimeError("Square account has no active location")
        core.run("INSERT INTO artist_payment_accounts(artist_id,provider,merchant_id,location_id,access_token,refresh_token,token_expires_at,connected_at) VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(artist_id,provider) DO UPDATE SET merchant_id=excluded.merchant_id,location_id=excluded.location_id,access_token=excluded.access_token,refresh_token=excluded.refresh_token,token_expires_at=excluded.token_expires_at,connected_at=excluded.connected_at",(aid,"square",merchant,location,token,data.get("refresh_token"),data.get("expires_at"),core.utcnow()))
        core.event("payment.square.connected",aid,{"merchant_id":merchant,"location_id":location})
        response=RedirectResponse("/settings/payments",status_code=303)
        core.set_session(response,aid)
        return response
    except Exception as exc:
        print(f"Square OAuth callback failed for artist {aid}: {type(exc).__name__}: {exc}",flush=True)
        try:core.event("payment.square.oauth_failed",aid,{"stage":"exchange","type":type(exc).__name__,"error":str(exc)[:500]})
        except Exception:pass
        response=core.page("Square","<div class='error'>SQUARE CONNECTION FAILED.</div><p class='dim'>Nothing was charged. Try connecting Square again.</p><a class='button' href='/settings/payments'>BACK</a>")
        core.set_session(response,aid)
        return response

def _replace_payment_route(route):
    path=getattr(route,"path",None)
    methods=getattr(route,"methods",set()) or set()
    return (path=="/o/{token}/pay" and "GET" in methods) or (path=="/o/{token}/square" and "POST" in methods)

core.app.router.routes[:]=[r for r in core.app.router.routes if not _replace_payment_route(r)]

@core.app.get("/o/{token}/pay")
def artist_pay_page(token:str):
    offer=core.one("SELECT * FROM offers WHERE token=?",(token,))
    if not offer or offer["status"]!="HOLDING":return RedirectResponse(f"/o/{token}")
    opening=core.one("SELECT * FROM openings WHERE id=?",(offer["opening_id"],));artist=core.one("SELECT * FROM artists WHERE id=?",(opening["artist_id"],));methods=set((artist.get("payment_methods") or "").split(","));acct=square_account(artist["id"]);square_ok=bool(acct and acct.get("location_id") and square_token(acct) and core.SQUARE_APP_ID);controls=[];head="";js=""
    if square_ok and ({"cashapp","card"}&methods):
        head=f'<script src="{core.SQUARE_JS}"></script>'
        if "cashapp" in methods:controls.append('<div id="cashapp"></div>')
        if "card" in methods:controls.append('<div id="card"></div><button id="card-pay" type="button">CARD</button>')
        cash=f'''const pr=payments.paymentRequest({{countryCode:'US',currencyCode:'USD',total:{{amount:amount.toFixed(2),label:'Deposit'}}}});const cap=await payments.cashAppPay(pr,{{redirectURL:location.href,referenceId:{json.dumps(offer['id'])}}});cap.addEventListener('ontokenization',e=>{{if(e.detail.error){{alert(e.detail.error.message||'Cash App could not authorize this payment.');return;}}if(e.detail.tokenResult?.status==='OK')sendToken(e.detail.tokenResult.token);else if(e.detail.tokenResult?.status==='Error')alert('Cash App could not authorize this payment.');}});await cap.attach('#cashapp');''' if "cashapp" in methods else ""
        card='''const card=await payments.card();await card.attach('#card');document.getElementById('card-pay').onclick=async()=>{const result=await card.tokenize();if(result.status==='OK')sendToken(result.token);};''' if "card" in methods else ""
        js=f'''<script>(async()=>{{const payments=Square.payments({json.dumps(core.SQUARE_APP_ID)},{json.dumps(acct['location_id'])});const amount={opening['deposit_cents']/100:.2f};async function sendToken(source){{const r=await fetch('/o/{token}/square',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{source_id:source}})}});let j={{}};try{{j=await r.json();}}catch(_e){{}}if(j.redirect)location.href=j.redirect;else alert(j.error||'Payment did not land.');}}{cash}{card}}})().catch(e=>{{console.error(e);alert(e?.message||'Payment could not start.');}});</script>'''
    if not controls:controls.append('<div class="error">PAYMENT CONNECTION REQUIRED.</div>')
    return core.page("Payment",f'''<div class="center"><h1>LOCK IT IN.</h1><p class="big">{core.fmt_money(opening['deposit_cents'])}</p></div><div class="stack">{"".join(controls)}</div><p class="dim center">applied to your tattoo.</p>''',script=js,head=head)

def _square_payment_error(exc:urllib.error.HTTPError):
    raw=""
    try:raw=exc.read().decode("utf-8","replace")
    except Exception:pass
    code="";detail=""
    try:
        payload=json.loads(raw or "{}")
        first=(payload.get("errors") or [{}])[0]
        code=str(first.get("code") or "")
        detail=str(first.get("detail") or "")
    except Exception:pass
    print(f"Square payment rejected: HTTP {getattr(exc,'code','?')} code={code or 'UNKNOWN'} detail={detail[:300]}",flush=True)
    if code=="PAYMENT_SOURCE_NOT_ENABLED_FOR_TARGET":return "Cash App isn't enabled for this Square account yet."
    if code=="CARD_PROCESSING_NOT_ENABLED":return "This Square account isn't activated to process payments yet."
    if code=="INSUFFICIENT_PERMISSIONS":return "Square connected, but payment permission is not active for this account."
    if code=="INVALID_LOCATION":return "This Square location can't accept this payment yet."
    if code=="PAYMENT_LIMIT_EXCEEDED":return "Square declined this payment because the account's processing limit was reached."
    if detail:return f"Square: {detail}"
    if code:return f"Square payment failed: {code.replace('_',' ').title()}."
    return "Square rejected the payment. Nothing was charged."

@core.app.post("/o/{token}/square")
async def artist_square_pay(token:str,request:Request):
    offer=core.one("SELECT * FROM offers WHERE token=?",(token,))
    if not offer or offer["status"]!="HOLDING":return JSONResponse({"error":"Chair is no longer held."},status_code=409)
    opening=core.one("SELECT * FROM openings WHERE id=?",(offer["opening_id"],));acct=square_account(opening["artist_id"]);access=square_token(acct);body=await request.json()
    if not access or not acct or not acct.get("location_id"):return JSONResponse({"error":"Artist payment connection is unavailable."},status_code=503)
    try:
        data=core.http_json(f"{core.SQUARE_BASE}/v2/payments","POST",{"source_id":body["source_id"],"idempotency_key":offer["id"],"amount_money":{"amount":int(opening["deposit_cents"]),"currency":"USD"},"location_id":acct["location_id"],"reference_id":opening["id"],"note":f"Empty Chair deposit // {core.fmt_when(opening['starts_at'])}"},{"Authorization":f"Bearer {access}","Square-Version":"2026-08-19"});payment=data.get("payment") or {}
        if payment.get("status") not in ("COMPLETED","APPROVED"):raise RuntimeError("Square did not complete the payment")
        core.finalize_booking(offer,"square",payment.get("id"));return {"redirect":f"/o/{token}/yours"}
    except urllib.error.HTTPError as exc:
        message=_square_payment_error(exc)
        try:core.event("payment.square.rejected",opening["artist_id"],{"opening_id":opening["id"],"http_status":getattr(exc,"code",None),"message":message})
        except Exception:pass
        return JSONResponse({"error":message},status_code=400)
    except Exception as exc:
        print(f"Square payment failed: {type(exc).__name__}: {exc}",flush=True)
        return JSONResponse({"error":"Payment could not be completed. Nothing was charged."},status_code=400)

print("Empty Chair 2.0 per-artist Square payments loaded // Venmo hidden",flush=True)
