"""Surface artist-side deposit failures without exposing payment plumbing to customers."""
from __future__ import annotations

import json
import urllib.error

from fastapi import Request
from fastapi.responses import JSONResponse

import v2_app as core
import v2_artist_payments as payments

ACCOUNT_CODES={"PAYMENT_SOURCE_NOT_ENABLED_FOR_TARGET","CARD_PROCESSING_NOT_ENABLED","INSUFFICIENT_PERMISSIONS","INVALID_LOCATION"}


def _drop_post():
    core.app.router.routes[:]=[
        r for r in core.app.router.routes
        if not (getattr(r,"path",None)=="/o/{token}/square" and "POST" in (getattr(r,"methods",set()) or set()))
    ]


def _alert(artist_id:str, reason:str):
    try:
        recent=core.one("SELECT id FROM events WHERE artist_id=? AND kind='alert.payment' AND created_at>=? LIMIT 1",(artist_id,(core.datetime.now(core.timezone.utc)-core.timedelta(hours=2)).isoformat()))
        if recent:return
    except Exception:pass
    artist=core.one("SELECT * FROM artists WHERE id=?",(artist_id,))
    accepted=bool(artist and core.send_sms(artist.get("phone"),f"EMPTY CHAIR // CHECK PAYMENT\n\nA deposit couldn't land because\nyour payment connection needs\nattention.\n\nFix it here:\n{core.BASE_URL}/settings/payments"))
    try:core.event("alert.payment" if accepted else "alert.payment.delivery_failed",artist_id,{"reason":reason})
    except Exception:pass


def _read_square_error(exc:urllib.error.HTTPError):
    raw=""
    try:raw=exc.read().decode("utf-8","replace")
    except Exception:pass
    code="";detail=""
    try:
        payload=json.loads(raw or "{}");first=(payload.get("errors") or [{}])[0];code=str(first.get("code") or "");detail=str(first.get("detail") or "")
    except Exception:pass
    if code=="PAYMENT_SOURCE_NOT_ENABLED_FOR_TARGET":msg="Cash App isn't enabled for this Square account yet."
    elif code=="CARD_PROCESSING_NOT_ENABLED":msg="This Square account isn't activated to process payments yet."
    elif code=="INSUFFICIENT_PERMISSIONS":msg="Square connected, but payment permission is not active for this account."
    elif code=="INVALID_LOCATION":msg="This Square location can't accept this payment yet."
    elif code=="PAYMENT_LIMIT_EXCEEDED":msg="Square declined this payment because the account's processing limit was reached."
    elif detail:msg=f"Square: {detail}"
    elif code:msg=f"Square payment failed: {code.replace('_',' ').title()}."
    else:msg="Square rejected the payment. Nothing was charged."
    return code,msg


_drop_post()

@core.app.post("/o/{token}/square")
async def hardened_square_pay(token:str,request:Request):
    offer=core.one("SELECT * FROM offers WHERE token=?",(token,))
    if not offer or offer["status"]!="HOLDING":return JSONResponse({"error":"Chair is no longer held."},status_code=409)
    opening=core.one("SELECT * FROM openings WHERE id=?",(offer["opening_id"],));acct=payments.square_account(opening["artist_id"])
    try:access=payments.square_token(acct)
    except Exception as exc:
        access="";core.event("payment.square.token_failed",opening["artist_id"],{"opening_id":opening["id"],"error":str(exc)[:500]})
    if not access or not acct or not acct.get("location_id"):
        _alert(opening["artist_id"],"connection_unavailable")
        return JSONResponse({"error":"Payment is temporarily unavailable. Your artist has been notified."},status_code=503)
    body=await request.json()
    try:
        data=core.http_json(f"{core.SQUARE_BASE}/v2/payments","POST",{"source_id":body["source_id"],"idempotency_key":offer["id"],"amount_money":{"amount":int(opening["deposit_cents"]),"currency":"USD"},"location_id":acct["location_id"],"reference_id":opening["id"],"note":f"Empty Chair deposit // {core.fmt_when(opening['starts_at'])}"},{"Authorization":f"Bearer {access}","Square-Version":"2026-08-19"})
        payment=data.get("payment") or {}
        if payment.get("status") not in ("COMPLETED","APPROVED"):raise RuntimeError("Square did not complete the payment")
        core.finalize_booking(offer,"square",payment.get("id"));return {"redirect":f"/o/{token}/yours"}
    except urllib.error.HTTPError as exc:
        code,message=_read_square_error(exc)
        try:core.event("payment.square.rejected",opening["artist_id"],{"opening_id":opening["id"],"http_status":getattr(exc,"code",None),"code":code,"message":message})
        except Exception:pass
        if code in ACCOUNT_CODES:_alert(opening["artist_id"],code)
        return JSONResponse({"error":message},status_code=400)
    except Exception as exc:
        try:core.event("payment.square.failed",opening["artist_id"],{"opening_id":opening["id"],"error":str(exc)[:500]})
        except Exception:pass
        return JSONResponse({"error":"Payment could not be completed. Nothing was charged."},status_code=400)

print("Empty Chair 2.0 payment failure hardening loaded",flush=True)
