"""Square subscription billing for Empty Chair itself (not tattoo deposits).

The Empty Chair merchant account is connected once through Square OAuth and stored in the
app database. This avoids requiring a separate Square access token/location in Render.
"""
from __future__ import annotations
import base64, hashlib, hmac, json, os, urllib.error, urllib.parse, urllib.request, uuid
from datetime import datetime, timedelta, timezone
from fastapi import Request
from fastapi.responses import JSONResponse, RedirectResponse
import v2_app as core
import v2_entitlement as entitlement

SQUARE_CLIENT_SECRET=os.getenv("SQUARE_CLIENT_SECRET","").strip()
WEBHOOK_SIGNATURE_KEY=os.getenv("EMPTY_CHAIR_BILLING_SQUARE_WEBHOOK_SIGNATURE_KEY","").strip()
BASE_URL=os.getenv("EMPTY_CHAIR_BASE_URL","https://empty-chair-mvp.onrender.com").rstrip("/")
SQUARE_ENV=os.getenv("SQUARE_ENV","production").lower()
API="https://connect.squareupsandbox.com" if SQUARE_ENV=="sandbox" else "https://connect.squareup.com"
VERSION="2026-08-19"

# These are public Catalog identifiers, not secrets. The dashboard-created variation is
# RELATIVE pricing; billing creates a STATIC $97/month variation under the same plan once
# the Empty Chair Square merchant is connected.
PARENT_PLAN_ID=os.getenv("EMPTY_CHAIR_BILLING_SQUARE_PLAN_ID","AIUUS5HIFQFNOEJUCSGO5QAH").strip()
MONTHLY_PRICE_CENTS=9700


def ensure_schema():
    try:
        d=core.DB()
        d.execute("""CREATE TABLE IF NOT EXISTS platform_billing_account (
            id INTEGER PRIMARY KEY CHECK(id=1), merchant_id TEXT, location_id TEXT,
            access_token TEXT, refresh_token TEXT, token_expires_at TEXT,
            monthly_plan_variation_id TEXT, connected_at TEXT NOT NULL
        )""")
        d.commit();d.close()
    except Exception as exc:print(f"billing schema warning: {exc}",flush=True)

@core.app.on_event("startup")
def billing_schema_startup():ensure_schema()
ensure_schema()


def _account():
    try:return core.one("SELECT * FROM platform_billing_account WHERE id=1")
    except Exception:return None


def _raw_request(token,method,path,body=None):
    data=json.dumps(body).encode() if body is not None else None
    req=urllib.request.Request(API+path,data=data,headers={"Authorization":f"Bearer {token}","Square-Version":VERSION,"Content-Type":"application/json"},method=method)
    try:
        with urllib.request.urlopen(req,timeout=20) as r:
            raw=r.read().decode();return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        detail=e.read().decode(errors="replace")
        raise RuntimeError(f"Square billing rejected request ({e.code}): {detail[:700]}") from e


def _token(acct=None):
    acct=acct or _account()
    if not acct:return ""
    exp=acct.get("token_expires_at")
    try:
        if acct.get("access_token") and (not exp or datetime.fromisoformat(exp.replace("Z","+00:00"))>datetime.now(timezone.utc)+timedelta(days=1)):
            return acct["access_token"]
    except Exception:pass
    if not (acct.get("refresh_token") and SQUARE_CLIENT_SECRET):return acct.get("access_token") or ""
    data=core.http_json(f"{API}/oauth2/token","POST",{"client_id":core.SQUARE_APP_ID,"client_secret":SQUARE_CLIENT_SECRET,"grant_type":"refresh_token","refresh_token":acct["refresh_token"]},{"Square-Version":VERSION})
    token=data.get("access_token") or "";refresh=data.get("refresh_token") or acct["refresh_token"];expires=data.get("expires_at")
    core.run("UPDATE platform_billing_account SET access_token=?,refresh_token=?,token_expires_at=? WHERE id=1",(token,refresh,expires))
    return token


def _request(method,path,body=None):
    token=_token()
    if not token:raise RuntimeError("Empty Chair billing merchant is not connected")
    return _raw_request(token,method,path,body)


def _verify_signature(payload:bytes,signature:str,url:str)->bool:
    if not WEBHOOK_SIGNATURE_KEY or not signature:return False
    digest=hmac.new(WEBHOOK_SIGNATURE_KEY.encode(),url.encode()+payload,hashlib.sha256).digest()
    return hmac.compare_digest(base64.b64encode(digest).decode(),signature)


def _artist_by_subscription(subscription_id):
    return core.one("SELECT * FROM artists WHERE subscription_provider='square' AND subscription_id=?",(subscription_id,)) if subscription_id else None


def _apply_subscription(sub):
    sid=str(sub.get("id") or "")
    artist=_artist_by_subscription(sid)
    if not artist:return
    status=(sub.get("status") or "").upper();customer=sub.get("customer_id")
    if status=="ACTIVE":entitlement.activate(artist["id"],"square",customer,sid,None)
    elif status in {"CANCELED","DEACTIVATED","COMPLETED"}:entitlement.deactivate(artist["id"],status.lower())


def _ensure_static_monthly(token):
    # Only the merchant that owns the Empty Chair plan can pass this lookup. That makes the
    # one-time platform connection self-verifying without another Render admin secret.
    _raw_request(token,"GET",f"/v2/catalog/object/{urllib.parse.quote(PARENT_PLAN_ID)}")
    acct=_account()
    existing=(acct or {}).get("monthly_plan_variation_id")
    if existing:
        try:
            obj=_raw_request(token,"GET",f"/v2/catalog/object/{urllib.parse.quote(existing)}").get("object") or {}
            pricing=((((obj.get("subscription_plan_variation_data") or {}).get("phases") or [{}])[0]).get("pricing") or {})
            if pricing.get("type")=="STATIC":return existing
        except Exception:pass
    payload={
        "idempotency_key":str(uuid.uuid4()),
        "object":{
            "type":"SUBSCRIPTION_PLAN_VARIATION","id":"#empty-chair-monthly-97","present_at_all_locations":True,
            "subscription_plan_variation_data":{
                "name":"Empty Chair // $97 Monthly","subscription_plan_id":PARENT_PLAN_ID,
                "phases":[{"cadence":"MONTHLY","ordinal":0,"pricing":{"type":"STATIC","price":{"amount":MONTHLY_PRICE_CENTS,"currency":"USD"}}}]
            }
        }
    }
    result=_raw_request(token,"POST","/v2/catalog/object",payload)
    variation=(result.get("catalog_object") or {}).get("id")
    if not variation:raise RuntimeError("Square did not create the monthly billing variation")
    return variation


@core.app.get("/billing/platform/connect")
def platform_connect(request:Request):
    artist=core.current_artist(request)
    if not artist:return RedirectResponse("/setup")
    if _account():return RedirectResponse("/settings/subscription",303)
    if not (core.SQUARE_APP_ID and SQUARE_CLIENT_SECRET):
        return core.page("Billing setup","<h1>EMPTY CHAIR // CHECK PAYMENT</h1><p>Square OAuth is not configured.</p>")
    scopes=" ".join([
        "MERCHANT_PROFILE_READ","ITEMS_READ","ITEMS_WRITE","CUSTOMERS_READ","CUSTOMERS_WRITE",
        "PAYMENTS_READ","PAYMENTS_WRITE","SUBSCRIPTIONS_READ","SUBSCRIPTIONS_WRITE",
        "ORDERS_READ","ORDERS_WRITE","INVOICES_READ","INVOICES_WRITE"
    ])
    params={"client_id":core.SQUARE_APP_ID,"scope":scopes,"session":"false","state":core.sign("billing-platform:"+str(artist["id"]))}
    return RedirectResponse(f"{API}/oauth2/authorize?"+urllib.parse.urlencode(params))


def finish_platform_oauth(code,state,error=None):
    signed=core.unsign(state);aid=signed.split(":",1)[1] if signed and signed.startswith("billing-platform:") else None
    if not aid or error or not code:
        return core.page("Billing setup","<h1>EMPTY CHAIR // CHECK PAYMENT</h1><p>Square billing connection was not completed.</p><a class='button' href='/settings/subscription'>BACK</a>")
    try:
        data=core.http_json(f"{API}/oauth2/token","POST",{"client_id":core.SQUARE_APP_ID,"client_secret":SQUARE_CLIENT_SECRET,"code":code,"grant_type":"authorization_code"},{"Square-Version":VERSION})
        token=data.get("access_token") or "";merchant=data.get("merchant_id") or ""
        if not token:raise RuntimeError("Square did not return an access token")
        locs=_raw_request(token,"GET","/v2/locations").get("locations",[]);active=[x for x in locs if x.get("status")=="ACTIVE"]
        location=(active or locs or [{}])[0].get("id","")
        if not location:raise RuntimeError("Square account has no active location")
        # Save first so _ensure_static_monthly can persist/reuse the generated variation.
        core.run("INSERT INTO platform_billing_account(id,merchant_id,location_id,access_token,refresh_token,token_expires_at,monthly_plan_variation_id,connected_at) VALUES(1,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET merchant_id=excluded.merchant_id,location_id=excluded.location_id,access_token=excluded.access_token,refresh_token=excluded.refresh_token,token_expires_at=excluded.token_expires_at,connected_at=excluded.connected_at",(merchant,location,token,data.get("refresh_token"),data.get("expires_at"),None,core.utcnow()))
        variation=_ensure_static_monthly(token)
        core.run("UPDATE platform_billing_account SET monthly_plan_variation_id=? WHERE id=1",(variation,))
        core.event("billing.square.connected",aid,{"merchant_id":merchant,"location_id":location,"plan_variation_id":variation})
        response=RedirectResponse("/settings/subscription",303);core.set_session(response,aid);return response
    except Exception as exc:
        # A wrong Square merchant cannot see the known Empty Chair plan, so it cannot become
        # the platform billing destination.
        try:core.run("DELETE FROM platform_billing_account WHERE id=1")
        except Exception:pass
        print(f"Square platform billing OAuth failed: {type(exc).__name__}: {exc}",flush=True)
        response=core.page("Billing setup",f"<h1>EMPTY CHAIR // CHECK PAYMENT</h1><p>{str(exc)}</p><a class='button' href='/settings/subscription'>BACK</a>")
        core.set_session(response,aid);return response


def _create_customer(artist,email):
    result=_request("POST","/v2/customers",{"idempotency_key":str(uuid.uuid4()),"given_name":artist.get("name") or "Empty Chair Artist","phone_number":artist.get("phone") or None,"email_address":email,"reference_id":str(artist["id"])})
    return result["customer"]["id"]


def _create_card(artist,customer_id,source_id):
    result=_request("POST","/v2/cards",{"idempotency_key":str(uuid.uuid4()),"source_id":source_id,"card":{"customer_id":customer_id,"cardholder_name":artist.get("name") or "Empty Chair Artist","reference_id":str(artist["id"])}})
    return result["card"]["id"]


@core.app.get("/billing/subscribe/{cadence}")
def subscribe_page(request:Request,cadence:str):
    artist=core.current_artist(request)
    if not artist:return RedirectResponse("/setup")
    if cadence!="monthly":return RedirectResponse("/settings/subscription",303)
    acct=_account()
    if not acct:
        return core.page("Billing setup",'''<div class="center"><h1>EMPTY CHAIR // BILLING SETUP</h1><p class="dim">One-time Square connection for Empty Chair subscriptions.</p><a class="button" href="/billing/platform/connect">CONNECT EMPTY CHAIR BILLING</a></div>''',chair=True)
    token=_token(acct)
    if not token or not acct.get("location_id") or not acct.get("monthly_plan_variation_id"):
        return core.page("Billing unavailable",'<h1>EMPTY CHAIR // CHECK PAYMENT</h1><p>Square subscription billing needs attention.</p><a class="button" href="/settings/subscription">BACK</a>')
    head=f'<script src="{core.SQUARE_JS}"></script>'
    js=f'''<script>(async()=>{{
const payments=Square.payments({json.dumps(core.SQUARE_APP_ID)},{json.dumps(acct['location_id'])});
const card=await payments.card();await card.attach('#billing-card');
const button=document.getElementById('subscribe-now');
button.onclick=async()=>{{
 const email=document.getElementById('billing-email').value.trim();const consent=document.getElementById('billing-consent').checked;
 if(!email||!email.includes('@')){{alert('Enter a valid email for Square receipts.');return;}}
 if(!consent){{alert('Confirm recurring billing before continuing.');return;}}
 button.disabled=true;button.textContent='WORKING...';
 try{{const t=await card.tokenize();if(t.status!=='OK')throw new Error('Card could not be authorized.');
 const r=await fetch('/billing/subscribe/monthly',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{source_id:t.token,email:email,consent:true}})}});const j=await r.json();if(j.redirect)location.href=j.redirect;else throw new Error(j.error||'Subscription could not be started.');}}
 catch(e){{alert(e.message||'Subscription could not be started.');button.disabled=false;button.textContent='SUBSCRIBE // $97 MONTHLY';}}
}};
}})().catch(e=>{{console.error(e);alert('Square billing could not start.');}});</script>'''
    return core.page("Subscribe",'''<div class="center"><h1>EMPTY CHAIR // RE-ARM</h1><p class="big">$97 / MONTH</p><p class="dim">Cancel anytime.</p></div><div class="stack"><label>receipt email<input id="billing-email" type="email" autocomplete="email" placeholder="you@example.com"></label><div id="billing-card"></div><label><input id="billing-consent" type="checkbox"> I authorize Empty Chair to save this card and charge $97 monthly until canceled.</label><button id="subscribe-now" type="button">SUBSCRIBE // $97 MONTHLY</button></div>''',script=js,head=head,chair=True)


@core.app.post("/billing/subscribe/monthly")
async def subscribe_monthly(request:Request):
    artist=core.current_artist(request)
    if not artist:return JSONResponse({"error":"Sign in again."},status_code=401)
    acct=_account()
    if not acct:return JSONResponse({"error":"Empty Chair billing is not connected."},status_code=503)
    body=await request.json();email=str(body.get("email") or "").strip();source=str(body.get("source_id") or "").strip()
    if not body.get("consent") or not source or "@" not in email:return JSONResponse({"error":"Email, card, and recurring billing consent are required."},status_code=400)
    fresh=core.one("SELECT * FROM artists WHERE id=?",(artist["id"],))
    if entitlement.allowed(fresh) and entitlement.state(fresh)=="active":return {"redirect":"/billing/return"}
    try:
        customer_id=fresh.get("subscription_customer_id") if fresh.get("subscription_provider")=="square" else None
        if not customer_id:customer_id=_create_customer(fresh,email)
        card_id=_create_card(fresh,customer_id,source)
        result=_request("POST","/v2/subscriptions",{"idempotency_key":str(uuid.uuid4()),"location_id":acct["location_id"],"plan_variation_id":acct["monthly_plan_variation_id"],"customer_id":customer_id,"card_id":card_id,"source":{"name":"Empty Chair"}})
        sub=result.get("subscription") or {};sid=sub.get("id")
        if not sid:raise RuntimeError("Square did not return a subscription")
        core.run("UPDATE artists SET subscription_provider='square',subscription_customer_id=?,subscription_id=?,updated_at=? WHERE id=?",(customer_id,sid,core.utcnow(),artist["id"]))
        core.event("subscription.created",artist["id"],{"provider":"square","subscription_id":sid,"status":sub.get("status")})
        _apply_subscription(sub)
        return {"redirect":"/billing/return"}
    except Exception as exc:
        print(f"Square subscription failed for artist {artist['id']}: {type(exc).__name__}: {exc}",flush=True)
        return JSONResponse({"error":"Square could not start the subscription. Nothing was charged."},status_code=400)


@core.app.get("/billing/return")
def billing_return(request:Request):
    artist=core.current_artist(request)
    if not artist:return RedirectResponse("/setup")
    fresh=core.one("SELECT * FROM artists WHERE id=?",(artist["id"],))
    if entitlement.allowed(fresh) and entitlement.state(fresh)=="active":
        return core.page("Armed",'<div class="center"><h1 class="bright">EMPTY CHAIR // ARMED [✓]</h1><p>Subscription confirmed. Your chair is covered again.</p><a class="button" href="/">DONE</a></div>',chair=True)
    return core.page("Confirming payment",'<div class="center"><h1>EMPTY CHAIR // CONFIRMING PAYMENT</h1><p>Square is confirming your subscription.</p><a class="button" href="/billing/return">CHECK AGAIN</a></div>',chair=True)


@core.app.post("/webhooks/billing/square")
async def billing_webhook(request:Request):
    payload=await request.body();signature=request.headers.get("x-square-hmacsha256-signature","");url=f"{BASE_URL}/webhooks/billing/square"
    if not _verify_signature(payload,signature,url):return JSONResponse({"ok":False},status_code=403)
    event=json.loads(payload);typ=event.get("type") or ""
    if typ in {"subscription.created","subscription.updated"}:
        sub=(((event.get("data") or {}).get("object") or {}).get("subscription") or {});_apply_subscription(sub)
    return {"ok":True}


print("Empty Chair 2.0 Square subscription billing loaded // DB-backed platform OAuth",flush=True)
