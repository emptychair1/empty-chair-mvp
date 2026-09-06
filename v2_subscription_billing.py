"""Square subscription billing for Empty Chair itself (not tattoo deposits)."""
from __future__ import annotations
import hashlib, hmac, json, os, urllib.error, urllib.request, uuid
from fastapi import Request
from fastapi.responses import JSONResponse, RedirectResponse
import v2_app as core
import v2_entitlement as entitlement

TOKEN=os.getenv("EMPTY_CHAIR_BILLING_SQUARE_ACCESS_TOKEN",os.getenv("SQUARE_ACCESS_TOKEN","")).strip()
LOCATION_ID=os.getenv("EMPTY_CHAIR_BILLING_SQUARE_LOCATION_ID","").strip()
MONTHLY_PLAN_ID=os.getenv("EMPTY_CHAIR_BILLING_SQUARE_MONTHLY_PLAN_VARIATION_ID","").strip()
YEARLY_PLAN_ID=os.getenv("EMPTY_CHAIR_BILLING_SQUARE_YEARLY_PLAN_VARIATION_ID","").strip()
WEBHOOK_SIGNATURE_KEY=os.getenv("EMPTY_CHAIR_BILLING_SQUARE_WEBHOOK_SIGNATURE_KEY","").strip()
BASE_URL=os.getenv("EMPTY_CHAIR_BASE_URL","https://empty-chair-mvp.onrender.com").rstrip("/")
SQUARE_ENV=os.getenv("SQUARE_ENV","production").lower()
API="https://connect.squareupsandbox.com" if SQUARE_ENV=="sandbox" else "https://connect.squareup.com"
VERSION="2026-08-19"


def _request(method,path,body=None):
    data=json.dumps(body).encode() if body is not None else None
    req=urllib.request.Request(API+path,data=data,headers={"Authorization":f"Bearer {TOKEN}","Square-Version":VERSION,"Content-Type":"application/json"},method=method)
    try:
        with urllib.request.urlopen(req,timeout=20) as r:return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        detail=e.read().decode(errors="replace")
        raise RuntimeError(f"Square billing rejected request ({e.code}): {detail[:500]}") from e


def _verify_signature(payload:bytes,signature:str,url:str)->bool:
    if not WEBHOOK_SIGNATURE_KEY or not signature:return False
    # Square signs notification URL + raw request body with HMAC-SHA256/base64.
    import base64
    digest=hmac.new(WEBHOOK_SIGNATURE_KEY.encode(),url.encode()+payload,hashlib.sha256).digest()
    expected=base64.b64encode(digest).decode()
    return hmac.compare_digest(expected,signature)


def _artist_by_subscription(subscription_id):
    return core.one("SELECT * FROM artists WHERE subscription_provider='square' AND subscription_id=?",(subscription_id,)) if subscription_id else None


def _apply_subscription(sub):
    sid=str(sub.get("id") or "")
    artist=_artist_by_subscription(sid)
    if not artist:return
    status=(sub.get("status") or "").upper()
    customer=sub.get("customer_id")
    # ACTIVE is entitlement. Pending/trial remains governed by Empty Chair's existing 7-day trial.
    if status=="ACTIVE":
        entitlement.activate(artist["id"],"square",customer,sid,None)
    elif status in {"CANCELED","DEACTIVATED","COMPLETED"}:
        entitlement.deactivate(artist["id"],status.lower())


def _create_customer(artist):
    result=_request("POST","/v2/customers",{"idempotency_key":str(uuid.uuid4()),"given_name":artist.get("name") or "Empty Chair Artist","phone_number":artist.get("phone") or None,"reference_id":str(artist["id"])})
    return result["customer"]["id"]


@core.app.get("/billing/subscribe/{cadence}")
def subscribe(request:Request,cadence:str):
    artist=core.current_artist(request)
    if not artist:return RedirectResponse("/setup")
    plan_id=MONTHLY_PLAN_ID if cadence=="monthly" else YEARLY_PLAN_ID if cadence=="yearly" else ""
    if not TOKEN or not LOCATION_ID or not plan_id:
        return core.page("Billing unavailable",'<h1>EMPTY CHAIR // CHECK PAYMENT</h1><p>Square subscription billing is not configured yet.</p><a class="button" href="/settings/subscription">BACK</a>')
    # Square subscriptions require a Square customer. We create/reuse one for the Empty Chair artist.
    fresh=core.one("SELECT * FROM artists WHERE id=?",(artist["id"],))
    customer_id=fresh.get("subscription_customer_id") if fresh.get("subscription_provider")=="square" else None
    try:
        if not customer_id:customer_id=_create_customer(fresh)
        # Create a subscription without granting entitlement. Square's webhook is authoritative.
        # If no card is on file Square invoices the customer's valid email; production setup should
        # collect/store a card before this route is enabled for automatic recurring billing.
        result=_request("POST","/v2/subscriptions",{"idempotency_key":str(uuid.uuid4()),"location_id":LOCATION_ID,"plan_variation_id":plan_id,"customer_id":customer_id,"source":{"name":"Empty Chair"}})
        sub=result["subscription"];sid=sub["id"]
        core.run("UPDATE artists SET subscription_provider='square',subscription_customer_id=?,subscription_id=?,updated_at=? WHERE id=?",(customer_id,sid,core.utcnow(),artist["id"]))
        core.event("subscription.created",artist["id"],{"provider":"square","subscription_id":sid,"status":sub.get("status")})
        _apply_subscription(sub)
    except Exception as exc:
        return core.page("Billing problem",f'<h1>EMPTY CHAIR // CHECK PAYMENT</h1><p>{str(exc)}</p><a class="button" href="/settings/subscription">BACK</a>')
    return RedirectResponse("/billing/return",status_code=303)


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
    payload=await request.body();signature=request.headers.get("x-square-hmacsha256-signature","")
    url=f"{BASE_URL}/webhooks/billing/square"
    if not _verify_signature(payload,signature,url):return JSONResponse({"ok":False},status_code=403)
    event=json.loads(payload);typ=event.get("type") or ""
    if typ in {"subscription.created","subscription.updated"}:
        sub=(((event.get("data") or {}).get("object") or {}).get("subscription") or {})
        _apply_subscription(sub)
    return {"ok":True}


print("Empty Chair 2.0 Square subscription billing loaded",flush=True)
