"""Native authentication for Empty Chair iPhone.

One-time SMS verification links an existing artist account to the phone. The resulting
opaque device token is stored on-device and Face ID protects subsequent app opens.
"""
from __future__ import annotations

import hashlib, secrets
from datetime import datetime, timedelta, timezone
from fastapi import HTTPException, Request
import v2_app as core
import v2_native_calendar as native_calendar

@core.app.on_event("startup")
def native_auth_schema():
    d=core.DB()
    try:
        d.execute("""CREATE TABLE IF NOT EXISTS native_auth_challenges(id TEXT PRIMARY KEY,artist_id TEXT NOT NULL,code_hash TEXT NOT NULL,expires_at TEXT NOT NULL,used INTEGER NOT NULL DEFAULT 0,created_at TEXT NOT NULL)""")
        d.commit()
    finally:d.close()

@core.app.post("/native/auth/start")
async def native_auth_start(request:Request):
    body=await request.json();phone=core.clean_phone(str(body.get("phone") or ""));name=str(body.get("name") or "Tattoo Artist").strip() or "Tattoo Artist"
    if not phone:raise HTTPException(400,"mobile required")
    artist=core.one("SELECT * FROM artists WHERE phone=? ORDER BY created_at LIMIT 1",(phone,))
    if not artist:
        raise HTTPException(404,"No Empty Chair account uses that mobile number yet.")
    code=f"{secrets.randbelow(1000000):06d}";challenge=secrets.token_urlsafe(24);expires=(datetime.now(timezone.utc)+timedelta(minutes=10)).isoformat()
    digest=hashlib.sha256((challenge+":"+code+":"+core.SESSION_SECRET).encode()).hexdigest()
    core.run("INSERT INTO native_auth_challenges(id,artist_id,code_hash,expires_at,used,created_at) VALUES(?,?,?,?,0,?)",(challenge,artist["id"],digest,expires,core.utcnow()))
    core.send_sms(phone,f"EMPTY CHAIR // VERIFY\n\n{code}\n\nCode expires in 10 min.")
    return {"challenge_id":challenge,"last4":phone[-4:]}

@core.app.post("/native/auth/verify")
async def native_auth_verify(request:Request):
    body=await request.json();challenge=str(body.get("challenge_id") or "");code=str(body.get("code") or "").strip();calendar_id=str(body.get("calendar_id") or "")
    row=core.one("SELECT * FROM native_auth_challenges WHERE id=?",(challenge,))
    if not row or int(row.get("used") or 0):raise HTTPException(400,"verification expired")
    try:valid=datetime.fromisoformat(row["expires_at"].replace("Z","+00:00"))>datetime.now(timezone.utc)
    except Exception:valid=False
    digest=hashlib.sha256((challenge+":"+code+":"+core.SESSION_SECRET).encode()).hexdigest()
    if not valid or not secrets.compare_digest(digest,row["code_hash"]):raise HTTPException(400,"that code didn't work")
    core.run("UPDATE native_auth_challenges SET used=1 WHERE id=?",(challenge,))
    token=native_calendar.issue_device(row["artist_id"],calendar_id)
    artist=core.one("SELECT * FROM artists WHERE id=?",(row["artist_id"],))
    return {"device_token":token,"artist_id":row["artist_id"],"artist_name":(artist or {}).get("name") or "Tattoo Artist"}

print("Empty Chair 2.0 native auth loaded // SMS once, Face ID after",flush=True)
