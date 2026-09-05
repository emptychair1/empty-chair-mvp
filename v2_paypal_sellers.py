"""PayPal seller onboarding for per-artist Venmo deposits.

Uses PayPal Complete Payments Platform / Partner Referrals. Sandbox can be built and
exercised before PayPal grants live partner approval. Live calls require that approval.
"""
from __future__ import annotations
import os, urllib.parse
from fastapi import Request
from fastapi.responses import RedirectResponse
import v2_app as core

PARTNER_ID=os.getenv("PAYPAL_PARTNER_ID","").strip()
BN_CODE=os.getenv("PAYPAL_BN_CODE","").strip()


def ensure_schema():
    try:
        d=core.DB();d.execute("""CREATE TABLE IF NOT EXISTS artist_paypal_accounts (
            artist_id TEXT PRIMARY KEY,
            merchant_id TEXT,
            payments_receivable INTEGER NOT NULL DEFAULT 0,
            primary_email_confirmed INTEGER NOT NULL DEFAULT 0,
            onboarding_status TEXT NOT NULL DEFAULT 'PENDING',
            connected_at TEXT
        )""");d.commit();d.close()
    except Exception as exc: print(f"paypal seller schema warning: {exc}",flush=True)

@core.app.on_event("startup")
def paypal_schema_startup(): ensure_schema()
ensure_schema()


def account(artist_id):
    try:return core.one("SELECT * FROM artist_paypal_accounts WHERE artist_id=?",(artist_id,))
    except Exception:return None


def platform_token():
    return core.paypal_token()


def headers():
    h={"Authorization":f"Bearer {platform_token()}"}
    if PARTNER_ID:h["PayPal-Partner-Attribution-Id"]=BN_CODE or PARTNER_ID
    return h

@core.app.get("/settings/payments/paypal/connect")
def paypal_connect(request:Request):
    artist=core.current_artist(request)
    if not artist:return RedirectResponse("/setup")
    if not (core.PAYPAL_CLIENT_ID and core.PAYPAL_CLIENT_SECRET and PARTNER_ID):
        return core.page("Venmo","<div class='error'>PAYPAL PARTNER CONNECTION IS NOT CONFIGURED YET.</div><a class='button' href='/settings/payments'>BACK</a>")
    payload={
      "tracking_id":artist["id"],
      "operations":[{"operation":"API_INTEGRATION","api_integration_preference":{"rest_api_integration":{"integration_method":"PAYPAL","integration_type":"THIRD_PARTY","third_party_details":{"features":["PAYMENT","REFUND"]}}}}],
      "products":["EXPRESS_CHECKOUT"],
      "legal_consents":[{"type":"SHARE_DATA_CONSENT","granted":True}],
      "partner_config_override":{"return_url":f"{core.BASE_URL}/settings/payments/paypal/return","return_url_description":"Return to Empty Chair"}
    }
    try:data=core.http_json(f"{core.PAYPAL_BASE}/v2/customer/partner-referrals","POST",payload,headers())
    except Exception as exc:return core.page("Venmo",f"<div class='error'>PAYPAL ONBOARDING COULD NOT START.<br><br>{core.html.escape(str(exc))}</div><a class='button' href='/settings/payments'>BACK</a>")
    for link in data.get("links",[]):
        if link.get("rel") in ("action_url","self") and link.get("href"):
            if link.get("rel")=="action_url":return RedirectResponse(link["href"])
    return core.page("Venmo","<div class='error'>PAYPAL DID NOT RETURN AN ONBOARDING LINK.</div><a class='button' href='/settings/payments'>BACK</a>")

@core.app.get("/settings/payments/paypal/return")
def paypal_return(request:Request,merchantIdInPayPal:str|None=None,merchantId:str|None=None,**kwargs):
    artist=core.current_artist(request)
    if not artist:return RedirectResponse("/setup")
    merchant=(merchantIdInPayPal or merchantId or "").strip()
    if not merchant:return core.page("Venmo","<div class='error'>PAYPAL DID NOT RETURN A SELLER ID.</div><a class='button' href='/settings/payments'>BACK</a>")
    receivable=0;confirmed=0;status="CONNECTED"
    try:
        data=core.http_json(f"{core.PAYPAL_BASE}/v1/customer/partners/{urllib.parse.quote(PARTNER_ID)}/merchant-integrations/{urllib.parse.quote(merchant)}",headers=headers())
        receivable=1 if data.get("payments_receivable") else 0
        confirmed=1 if data.get("primary_email_confirmed") else 0
        if not receivable:status="ACTION_REQUIRED"
    except Exception:status="CONNECTED"
    core.run("INSERT INTO artist_paypal_accounts(artist_id,merchant_id,payments_receivable,primary_email_confirmed,onboarding_status,connected_at) VALUES(?,?,?,?,?,?) ON CONFLICT(artist_id) DO UPDATE SET merchant_id=excluded.merchant_id,payments_receivable=excluded.payments_receivable,primary_email_confirmed=excluded.primary_email_confirmed,onboarding_status=excluded.onboarding_status,connected_at=excluded.connected_at",(artist["id"],merchant,receivable,confirmed,status,core.utcnow()))
    core.event("payment.paypal.connected",artist["id"],{"merchant_id":merchant,"status":status})
    return RedirectResponse("/settings/payments",status_code=303)

print("Empty Chair 2.0 PayPal seller onboarding loaded",flush=True)
