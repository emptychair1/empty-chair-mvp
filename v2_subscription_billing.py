"""Stripe subscription billing for Empty Chair itself (not tattoo deposits)."""
from __future__ import annotations
import hashlib, hmac, json, os, time, urllib.error, urllib.parse, urllib.request
from fastapi import Request
from fastapi.responses import JSONResponse, RedirectResponse
import v2_app as core
import v2_entitlement as entitlement

SECRET=os.getenv("EMPTY_CHAIR_BILLING_STRIPE_SECRET_KEY",os.getenv("STRIPE_SECRET_KEY","")).strip()
WEBHOOK_SECRET=os.getenv("EMPTY_CHAIR_BILLING_STRIPE_WEBHOOK_SECRET","").strip()
MONTHLY_PRICE_ID=os.getenv("EMPTY_CHAIR_BILLING_MONTHLY_PRICE_ID","").strip()
YEARLY_PRICE_ID=os.getenv("EMPTY_CHAIR_BILLING_YEARLY_PRICE_ID","").strip()
BASE_URL=os.getenv("EMPTY_CHAIR_BASE_URL","https://empty-chair-mvp.onrender.com").rstrip("/")

def _post(path,fields):
    req=urllib.request.Request("https://api.stripe.com/v1"+path,data=urllib.parse.urlencode(fields).encode(),headers={"Authorization":f"Bearer {SECRET}","Content-Type":"application/x-www-form-urlencoded"},method="POST")
    try:
        with urllib.request.urlopen(req,timeout=20) as r:return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        body=e.read().decode(errors="replace");raise RuntimeError(f"Billing provider rejected request ({e.code}): {body[:400]}") from e

def _verify(payload,header):
    if not WEBHOOK_SECRET or not header:return False
    parts={}
    for item in header.split(","):
        if "=" in item:
            k,v=item.split("=",1);parts.setdefault(k,[]).append(v)
    try:t=int(parts["t"][0])
    except Exception:return False
    if abs(int(time.time())-t)>300:return False
    expected=hmac.new(WEBHOOK_SECRET.encode(),f"{t}.".encode()+payload,hashlib.sha256).hexdigest()
    return any(hmac.compare_digest(expected,v) for v in parts.get("v1",[]))

def _artist_from_metadata(obj):
    aid=str((obj.get("metadata") or {}).get("artist_id") or "")
    return core.one("SELECT * FROM artists WHERE id=?",(aid,)) if aid else None

def _apply_subscription(sub):
    artist=_artist_from_metadata(sub)
    if not artist:return
    status=(sub.get("status") or "").lower()
    customer=sub.get("customer");sid=sub.get("id")
    period=sub.get("current_period_end")
    period_end=None
    if period:
        from datetime import datetime,timezone
        period_end=datetime.fromtimestamp(int(period),timezone.utc).isoformat()
    if status in {"active","trialing"}:
        entitlement.activate(artist["id"],"stripe",customer,sid,period_end)
    elif status in {"past_due","unpaid","canceled","incomplete_expired"}:
        entitlement.deactivate(artist["id"],status)

@core.app.get("/billing/subscribe/{cadence}")
def subscribe(request:Request,cadence:str):
    artist=core.current_artist(request)
    if not artist:return RedirectResponse("/setup")
    price_id=MONTHLY_PRICE_ID if cadence=="monthly" else YEARLY_PRICE_ID if cadence=="yearly" else ""
    if not SECRET or not price_id:return core.page("Billing unavailable",'<h1>EMPTY CHAIR // CHECK PAYMENT</h1><p>Subscription billing is not configured yet.</p><a class="button" href="/settings/subscription">BACK</a>')
    session=_post("/checkout/sessions",{"mode":"subscription","line_items[0][price]":price_id,"line_items[0][quantity]":"1","success_url":f"{BASE_URL}/billing/return?session_id={{CHECKOUT_SESSION_ID}}","cancel_url":f"{BASE_URL}/settings/subscription","client_reference_id":artist["id"],"metadata[artist_id]":artist["id"],"subscription_data[metadata][artist_id]":artist["id"]})
    return RedirectResponse(session["url"],status_code=303)

@core.app.get("/billing/return")
def billing_return(request:Request,session_id:str=""):
    artist=core.current_artist(request)
    if not artist:return RedirectResponse("/setup")
    # Webhook is authoritative. Return page never grants access by itself.
    fresh=core.one("SELECT * FROM artists WHERE id=?",(artist["id"],))
    if entitlement.allowed(fresh):return core.page("Armed",'<div class="center"><h1 class="bright">EMPTY CHAIR // ARMED [✓]</h1><p>Payment confirmed. Your chair is covered again.</p><a class="button" href="/">DONE</a></div>',chair=True)
    return core.page("Confirming payment",'<div class="center"><h1>EMPTY CHAIR // CONFIRMING PAYMENT</h1><p>Your payment is being confirmed.</p><a class="button" href="/billing/return">CHECK AGAIN</a></div>',chair=True)

@core.app.post("/webhooks/billing/stripe")
async def billing_webhook(request:Request):
    payload=await request.body()
    if not _verify(payload,request.headers.get("stripe-signature","")):return JSONResponse({"ok":False},status_code=400)
    event=json.loads(payload);obj=(event.get("data") or {}).get("object") or {};typ=event.get("type") or ""
    if typ.startswith("customer.subscription."):_apply_subscription(obj)
    elif typ=="checkout.session.completed":
        aid=str((obj.get("metadata") or {}).get("artist_id") or obj.get("client_reference_id") or "")
        if aid and obj.get("subscription"):
            core.run("UPDATE artists SET subscription_provider='stripe',subscription_customer_id=?,subscription_id=?,updated_at=? WHERE id=?",(obj.get("customer"),obj.get("subscription"),core.utcnow(),aid))
            core.event("subscription.checkout.completed",aid,{"subscription_id":obj.get("subscription")})
    return {"ok":True}

print("Empty Chair 2.0 subscription billing loaded",flush=True)
