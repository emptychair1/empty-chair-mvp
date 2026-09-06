"""Temporary isolated simulator for the post-trial artist experience.

Only URLs under /__test/day8 use the $1 founder test. Production subscription pricing and
routes remain untouched. Remove this module after the post-trial flow is proven.
"""
from datetime import datetime, timedelta, timezone
import json, secrets
from fastapi import Request
from fastapi.responses import JSONResponse, RedirectResponse
import v2_app as core
import v2_entitlement as entitlement
import v2_artist_payments as artist_payments


@core.app.get("/__test/day8")
def simulate_day8(request: Request):
    artist = core.current_artist(request)
    if not artist:
        return RedirectResponse("/", status_code=303)
    ended = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
    core.run(
        "UPDATE artists SET trial_ends_at=?,subscription_status='trialing',subscription_provider=NULL,subscription_customer_id=NULL,subscription_id=NULL,subscription_period_end=NULL,updated_at=? WHERE id=?",
        (ended, core.utcnow(), artist["id"]),
    )
    core.event("trial.test_day8", artist["id"], {"trial_ends_at": ended})
    return RedirectResponse("/__test/day8/paywall", status_code=303)


@core.app.get("/__test/day8/paywall")
def test_paywall(request: Request):
    artist = core.current_artist(request)
    if not artist:
        return RedirectResponse("/", status_code=303)
    fresh = core.one("SELECT * FROM artists WHERE id=?", (artist["id"],))
    if entitlement.allowed(fresh):
        return RedirectResponse("/", status_code=303)
    return core.page("Subscription Required", '''<div class="center"><h1>EMPTY CHAIR // PAYMENT REQUIRED</h1><p>Your 7-day trial has ended.</p><p class="bright">Your chair is no longer covered.</p><div class="space"></div><p class="big">$97 / MONTH</p><a class="button" href="/__test/day8/checkout">KEEP MY CHAIR COVERED</a><p class="dim">Cancel anytime. Recovery resumes as soon as payment is confirmed.</p></div>''', chair=True)


@core.app.get("/__test/day8/checkout")
def test_checkout(request: Request):
    artist = core.current_artist(request)
    if not artist:
        return RedirectResponse("/", status_code=303)
    acct = artist_payments.square_account(artist["id"])
    token = artist_payments.square_token(acct)
    if not (acct and token and acct.get("location_id") and core.SQUARE_APP_ID):
        return core.page("Test payment", "<h1>EMPTY CHAIR // CHECK PAYMENT</h1><p>Your existing Square deposit connection is unavailable.</p>", chair=True)
    head = f'<script src="{core.SQUARE_JS}"></script>'
    js = f'''<script>(async()=>{{
const payments=Square.payments({json.dumps(core.SQUARE_APP_ID)},{json.dumps(acct['location_id'])});
const card=await payments.card();await card.attach('#test-card');
const b=document.getElementById('test-pay');
b.onclick=async()=>{{b.disabled=true;b.textContent='WORKING...';try{{const t=await card.tokenize();if(t.status!=='OK')throw new Error('Card could not be authorized.');const r=await fetch('/__test/day8/charge',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{source_id:t.token}})}});const j=await r.json();if(j.redirect)location.href=j.redirect;else throw new Error(j.error||'Payment failed.');}}catch(e){{alert(e.message);b.disabled=false;b.textContent='TEST PAYMENT // $1';}}}};
}})().catch(e=>alert(e.message||'Square could not start.'));</script>'''
    return core.page("Subscribe", '''<div class="center"><h1>EMPTY CHAIR // RE-ARM</h1><p class="big">$97 / MONTH</p><p class="dim">Founder E2E: this test charges $1 today.</p></div><div class="stack"><div id="test-card"></div><button id="test-pay" type="button">TEST PAYMENT // $1</button></div>''', script=js, head=head, chair=True)


@core.app.post("/__test/day8/charge")
async def test_charge(request: Request):
    artist = core.current_artist(request)
    if not artist:
        return JSONResponse({"error": "Sign in again."}, status_code=401)
    fresh = core.one("SELECT * FROM artists WHERE id=?", (artist["id"],))
    if entitlement.allowed(fresh):
        return {"redirect": "/"}
    acct = artist_payments.square_account(artist["id"])
    access = artist_payments.square_token(acct)
    if not (acct and access and acct.get("location_id")):
        return JSONResponse({"error": "Square test connection is unavailable."}, status_code=503)
    body = await request.json(); source = str(body.get("source_id") or "")
    if not source:
        return JSONResponse({"error": "Card authorization is required."}, status_code=400)
    try:
        payment_id = "day8-" + secrets.token_hex(12)
        data = core.http_json(f"{core.SQUARE_BASE}/v2/payments", "POST", {
            "source_id": source,
            "idempotency_key": payment_id,
            "amount_money": {"amount": 100, "currency": "USD"},
            "location_id": acct["location_id"],
            "reference_id": artist["id"],
            "note": "Empty Chair founder Day-8 E2E test"
        }, {"Authorization": f"Bearer {access}", "Square-Version": "2026-08-19"})
        payment = data.get("payment") or {}
        if payment.get("status") not in ("COMPLETED", "APPROVED"):
            raise RuntimeError("Square did not complete the $1 test payment")
        entitlement.activate(artist["id"], "square_test", artist["id"], payment.get("id"), None)
        core.event("trial.test_day8.paid", artist["id"], {"amount_cents": 100, "payment_id": payment.get("id")})
        return {"redirect": "/__test/day8/success"}
    except Exception as exc:
        print(f"Day-8 $1 test failed: {type(exc).__name__}: {exc}", flush=True)
        return JSONResponse({"error": "The $1 test payment did not complete. Nothing was activated."}, status_code=400)


@core.app.get("/__test/day8/success")
def test_success(request: Request):
    artist = core.current_artist(request)
    if not artist:
        return RedirectResponse("/", status_code=303)
    fresh = core.one("SELECT * FROM artists WHERE id=?", (artist["id"],))
    if not entitlement.allowed(fresh):
        return RedirectResponse("/__test/day8/paywall", status_code=303)
    return core.page("Armed", '''<div class="center"><h1 class="bright">EMPTY CHAIR // ARMED ✓</h1><p>payment................[✓]</p><p>chair coverage..........[✓]</p><div class="space"></div><p>YOU CAN CLOSE THIS NOW.</p></div>''', chair=True)


print("Empty Chair 2.0 Day-8 simulator loaded // isolated $1 E2E", flush=True)
