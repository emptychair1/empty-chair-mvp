"""Artist-safe SaaS checkout bridge plus one founder-only real subscription proof."""
import json, uuid
from fastapi import Request
from fastapi.responses import JSONResponse, RedirectResponse
import v2_app as core
import v2_artist_payments as artist_payments
import v2_subscription_billing as billing
import v2_entitlement as entitlement


def _matches(path,method):
    def yes(route):
        methods=getattr(route,"methods",set()) or set()
        return getattr(route,"path",None)==path and method in methods
    return yes


def _adopt_existing_platform_merchant(artist):
    if billing._account():return True
    acct=artist_payments.square_account(artist["id"])
    token=artist_payments.square_token(acct) if acct else ""
    if not (acct and token and acct.get("location_id")):return False
    try:
        core.run("INSERT INTO platform_billing_account(id,merchant_id,location_id,access_token,refresh_token,token_expires_at,monthly_plan_variation_id,connected_at) VALUES(1,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET merchant_id=excluded.merchant_id,location_id=excluded.location_id,access_token=excluded.access_token,refresh_token=excluded.refresh_token,token_expires_at=excluded.token_expires_at,connected_at=excluded.connected_at",(acct.get("merchant_id"),acct.get("location_id"),token,acct.get("refresh_token"),acct.get("token_expires_at"),None,core.utcnow()))
        variation=billing._ensure_static_monthly(token)
        core.run("UPDATE platform_billing_account SET monthly_plan_variation_id=? WHERE id=1",(variation,))
        core.event("billing.square.adopted",artist["id"],{"merchant_id":acct.get("merchant_id"),"location_id":acct.get("location_id"),"plan_variation_id":variation})
        return True
    except Exception as exc:
        try:core.run("DELETE FROM platform_billing_account WHERE id=1")
        except Exception:pass
        print(f"Platform Square adoption failed: {type(exc).__name__}: {exc}",flush=True);return False


def _founder_test(artist):
    return (artist.get("subscription_provider") or "")=="square_test"


def _one_dollar_variation():
    acct=billing._account();token=billing._token(acct)
    payload={"idempotency_key":str(uuid.uuid4()),"object":{"type":"SUBSCRIPTION_PLAN_VARIATION","id":"#empty-chair-founder-proof-1","present_at_all_locations":True,"subscription_plan_variation_data":{"name":"Empty Chair // Founder $1 Proof","subscription_plan_id":billing.PARENT_PLAN_ID,"phases":[{"cadence":"MONTHLY","ordinal":0,"pricing":{"type":"STATIC","price":{"amount":100,"currency":"USD"}}}]}}}
    result=billing._raw_request(token,"POST","/v2/catalog/object",payload)
    variation=(result.get("catalog_object") or {}).get("id")
    if not variation:raise RuntimeError("Square did not create founder proof variation")
    return variation


# Replace both GET and POST. Normal artists still use the production billing implementation;
# only the already-marked square_test founder account can enter the $1 proof branch.
core.app.router.routes[:]=[r for r in core.app.router.routes if not _matches("/billing/subscribe/{cadence}","GET")(r) and not _matches("/billing/subscribe/monthly","POST")(r) and not _matches("/billing/platform/connect","GET")(r)]


@core.app.get("/billing/subscribe/{cadence}")
def subscribe_page(request:Request,cadence:str):
    artist=core.current_artist(request)
    if not artist:return RedirectResponse("/setup")
    if cadence!="monthly":return RedirectResponse("/settings/subscription",303)
    if not billing._account() and not _adopt_existing_platform_merchant(artist):
        return core.page("Billing unavailable",'<div class="center"><h1>EMPTY CHAIR // CHECK PAYMENT</h1><p>Subscription checkout is temporarily unavailable.</p><a class="button" href="/settings/subscription">BACK</a></div>',chair=True)
    if not _founder_test(artist):return billing.subscribe_page(request,"monthly")
    acct=billing._account();head=f'<script src="{core.SQUARE_JS}"></script>'
    js=f'''<script>(async()=>{{const payments=Square.payments({json.dumps(core.SQUARE_APP_ID)},{json.dumps(acct['location_id'])});const card=await payments.card();await card.attach('#billing-card');const b=document.getElementById('subscribe-now');b.onclick=async()=>{{const email=document.getElementById('billing-email').value.trim();const consent=document.getElementById('billing-consent').checked;if(!email||!email.includes('@')){{alert('Enter a valid email for Square receipts.');return;}}if(!consent){{alert('Confirm the $1 recurring founder test.');return;}}b.disabled=true;b.textContent='WORKING...';try{{const t=await card.tokenize();if(t.status!=='OK')throw new Error('Card could not be authorized.');const r=await fetch('/billing/subscribe/monthly',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{source_id:t.token,email:email,consent:true,founder_proof:true}})}});const j=await r.json();if(j.redirect)location.href=j.redirect;else throw new Error(j.error||'Subscription could not be started.');}}catch(e){{alert(e.message||'Subscription could not be started.');b.disabled=false;b.textContent='RUN $1 SUBSCRIPTION PROOF';}}}};}})();</script>'''
    body='''<div class="center"><h1>EMPTY CHAIR // FINAL BILLING PROOF</h1><p class="big">$1 / MONTH</p><p class="bright">FOUNDER TEST ONLY</p><p class="dim">This creates a real recurring Square subscription for $1. It will be removed after this proof.</p></div><div class="stack"><label>receipt email<input id="billing-email" type="email" autocomplete="email" placeholder="you@example.com"></label><div id="billing-card"></div><label><input id="billing-consent" type="checkbox"> I authorize this real $1/month recurring founder test.</label><button id="subscribe-now" type="button">RUN $1 SUBSCRIPTION PROOF</button></div>'''
    return core.page("Founder billing proof",body,script=js,head=head,chair=True)


@core.app.post("/billing/subscribe/monthly")
async def subscribe_monthly(request:Request):
    artist=core.current_artist(request)
    if not artist:return JSONResponse({"error":"Sign in again."},status_code=401)
    body=await request.json();fresh=core.one("SELECT * FROM artists WHERE id=?",(artist["id"],)) or artist
    if not (_founder_test(fresh) and body.get("founder_proof")):
        return await billing.subscribe_monthly(request)
    email=str(body.get("email") or "").strip();source=str(body.get("source_id") or "").strip()
    if not body.get("consent") or not source or "@" not in email:return JSONResponse({"error":"Email, card, and consent are required."},status_code=400)
    try:
        acct=billing._account();customer_id=billing._create_customer(fresh,email);card_id=billing._create_card(fresh,customer_id,source);variation=_one_dollar_variation()
        result=billing._request("POST","/v2/subscriptions",{"idempotency_key":str(uuid.uuid4()),"location_id":acct["location_id"],"plan_variation_id":variation,"customer_id":customer_id,"card_id":card_id,"source":{"name":"Empty Chair Founder Proof"}})
        sub=result.get("subscription") or {};sid=sub.get("id")
        if not sid:raise RuntimeError("Square did not return a subscription")
        core.run("UPDATE artists SET subscription_provider='square',subscription_customer_id=?,subscription_id=?,updated_at=? WHERE id=?",(customer_id,sid,core.utcnow(),artist["id"]))
        core.event("subscription.founder_proof",artist["id"],{"provider":"square","subscription_id":sid,"status":sub.get("status"),"amount_cents":100})
        billing._apply_subscription(sub)
        return {"redirect":"/billing/return"}
    except Exception as exc:
        print(f"Founder subscription proof failed: {type(exc).__name__}: {exc}",flush=True)
        return JSONResponse({"error":"Square could not start the $1 subscription. Nothing was charged."},status_code=400)


@core.app.get("/billing/platform/connect")
def platform_connect_hidden(request:Request):
    artist=core.current_artist(request)
    if not artist:return RedirectResponse("/setup")
    if _adopt_existing_platform_merchant(artist):return RedirectResponse("/billing/subscribe/monthly",303)
    return RedirectResponse("/settings/subscription",303)

print("Empty Chair 2.0 billing checkout loaded // founder $1 recurring proof armed",flush=True)
