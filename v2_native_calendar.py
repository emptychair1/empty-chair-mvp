"""Native iPhone EventKit bridge for Empty Chair 2.0.

The phone owns Apple Calendar access. The server receives snapshots, detects removed
appointments through the existing recovery engine, and queues replacement bookings for
the phone to write back through EventKit.
"""
from __future__ import annotations

import hashlib, json, secrets
from fastapi import Header, HTTPException, Request
import v2_app as core


def _bearer(authorization: str | None):
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(401,"missing device token")
    digest=hashlib.sha256(authorization.split(" ",1)[1].encode()).hexdigest()
    device=core.one("SELECT * FROM native_devices WHERE token_hash=?",(digest,))
    if not device:raise HTTPException(401,"invalid device token")
    return device

@core.app.on_event("startup")
def native_schema():
    d=core.DB()
    try:
        d.execute("""CREATE TABLE IF NOT EXISTS native_devices(id TEXT PRIMARY KEY,artist_id TEXT NOT NULL,token_hash TEXT NOT NULL UNIQUE,platform TEXT NOT NULL,calendar_id TEXT,created_at TEXT NOT NULL,last_seen_at TEXT NOT NULL)""")
        d.execute("""CREATE TABLE IF NOT EXISTS native_calendar_snapshot(artist_id TEXT NOT NULL,event_id TEXT NOT NULL,title TEXT,start_at TEXT NOT NULL,end_at TEXT NOT NULL,updated_at TEXT NOT NULL,PRIMARY KEY(artist_id,event_id))""")
        d.execute("""CREATE TABLE IF NOT EXISTS native_calendar_outbox(id TEXT PRIMARY KEY,artist_id TEXT NOT NULL,kind TEXT NOT NULL,payload TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'pending',created_at TEXT NOT NULL,acked_at TEXT)""")
        d.commit()
    finally:d.close()

@core.app.post("/native/device/register")
async def register_device(request:Request):
    artist=core.current_artist(request)
    if not artist:raise HTTPException(401,"sign in required")
    body=await request.json();calendar_id=str(body.get("calendar_id") or "")
    token=secrets.token_urlsafe(32);did=secrets.token_hex(16);now=core.utcnow()
    core.run("INSERT INTO native_devices(id,artist_id,token_hash,platform,calendar_id,created_at,last_seen_at) VALUES(?,?,?,?,?,?,?)",(did,artist["id"],hashlib.sha256(token.encode()).hexdigest(),"ios",calendar_id,now,now))
    core.run("INSERT INTO calendar_accounts(artist_id,provider,calendar_id,connected_at) VALUES(?,?,?,?) ON CONFLICT(artist_id) DO UPDATE SET provider=excluded.provider,calendar_id=excluded.calendar_id,connected_at=excluded.connected_at",(artist["id"],"apple_native",calendar_id,now))
    return {"device_token":token,"artist_id":artist["id"]}

@core.app.post("/native/calendar/sync")
async def sync_calendar(request:Request,authorization:str|None=Header(None)):
    device=_bearer(authorization);artist=core.one("SELECT * FROM artists WHERE id=?",(device["artist_id"],))
    if not artist:raise HTTPException(404,"artist missing")
    body=await request.json();events=body.get("events") or [];now=core.utcnow()
    incoming={str(e.get("id")):e for e in events if e.get("id") and e.get("start_at") and e.get("end_at")}
    previous={r["event_id"]:r for r in core.all("SELECT * FROM native_calendar_snapshot WHERE artist_id=?",(artist["id"],))}
    # First snapshot establishes baseline. Later missing events are real removals and use the
    # same cancellation -> recovery path as Google/legacy Apple polling.
    if previous:
        for event_id,row in previous.items():
            if event_id not in incoming:
                try:core.create_opening_from_appointment(artist,event_id,row.get("title") or "Tattoo",row["start_at"],row["end_at"])
                except Exception as exc:print(f"Native Apple cancellation failed {event_id}: {type(exc).__name__}: {exc}",flush=True)
    core.run("DELETE FROM native_calendar_snapshot WHERE artist_id=?",(artist["id"],))
    for event_id,e in incoming.items():
        core.run("INSERT INTO native_calendar_snapshot(artist_id,event_id,title,start_at,end_at,updated_at) VALUES(?,?,?,?,?,?)",(artist["id"],event_id,str(e.get("title") or "Tattoo"),str(e["start_at"]),str(e["end_at"]),now))
    core.run("UPDATE native_devices SET last_seen_at=?,calendar_id=? WHERE id=?",(now,str(body.get("calendar_id") or device.get("calendar_id") or ""),device["id"]))
    commands=core.all("SELECT id,kind,payload FROM native_calendar_outbox WHERE artist_id=? AND status='pending' ORDER BY created_at",(artist["id"],))
    return {"ok":True,"commands":[{"id":c["id"],"kind":c["kind"],"payload":json.loads(c["payload"])} for c in commands]}

@core.app.post("/native/calendar/ack/{command_id}")
def ack_calendar(command_id:str,authorization:str|None=Header(None)):
    device=_bearer(authorization)
    core.run("UPDATE native_calendar_outbox SET status='acked',acked_at=? WHERE id=? AND artist_id=?",(core.utcnow(),command_id,device["artist_id"]))
    return {"ok":True}


def queue_event_write(artist_id:str,title:str,start_at:str,end_at:str,notes:str=""):
    cid=secrets.token_hex(16)
    core.run("INSERT INTO native_calendar_outbox(id,artist_id,kind,payload,status,created_at) VALUES(?,?,?,?,?,?)",(cid,artist_id,"upsert_event",json.dumps({"title":title,"start_at":start_at,"end_at":end_at,"notes":notes},separators=(",",":")),"pending",core.utcnow()))
    return cid

print("Empty Chair 2.0 native Apple calendar bridge loaded",flush=True)
