"""Native calendar bridge for Empty Chair 2.0.

The device owns calendar permission. iOS uses EventKit; Android uses Calendar Provider.
Both send snapshots to the same recovery engine and receive filled-chair write commands.
"""
from __future__ import annotations

import hashlib, json, secrets, uuid
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


def issue_device(artist_id:str,calendar_id:str="",platform:str="ios"):
    if platform not in ("ios","android"): platform="ios"
    token=secrets.token_urlsafe(32);did=secrets.token_hex(16);now=core.utcnow()
    core.run("INSERT INTO native_devices(id,artist_id,token_hash,platform,calendar_id,created_at,last_seen_at) VALUES(?,?,?,?,?,?,?)",(did,artist_id,hashlib.sha256(token.encode()).hexdigest(),platform,calendar_id,now,now))
    core.run("INSERT INTO calendar_accounts(artist_id,provider,calendar_id,connected_at) VALUES(?,?,?,?) ON CONFLICT(artist_id) DO UPDATE SET provider=excluded.provider,calendar_id=excluded.calendar_id,access_token=NULL,refresh_token=NULL,token_expires_at=NULL,apple_username=NULL,apple_password=NULL,apple_calendar_url=NULL,connected_at=excluded.connected_at",(artist_id,"native",calendar_id,now))
    return token

@core.app.post("/native/device/register")
async def register_device(request:Request):
    artist=core.current_artist(request)
    if not artist:raise HTTPException(401,"sign in required")
    body=await request.json();calendar_id=str(body.get("calendar_id") or "");platform=str(body.get("platform") or "ios").lower()
    return {"device_token":issue_device(artist["id"],calendar_id,platform),"artist_id":artist["id"]}


def _cancel_from_snapshot(artist:dict,event_id:str,row:dict):
    existing=core.one("SELECT * FROM appointments WHERE artist_id=? AND provider='native' AND remote_id=?",(artist["id"],event_id))
    if not existing:
        appt_id=str(uuid.uuid4())
        core.run("INSERT INTO appointments(id,artist_id,provider,remote_id,title,starts_at,ends_at,remote_status,active,snapshot_at) VALUES(?,?,?,?,?,?,?,'deleted',0,?)",(appt_id,artist["id"],"native",event_id,row.get("title") or "Tattoo",row["start_at"],row["end_at"],core.utcnow()))
        existing=core.one("SELECT * FROM appointments WHERE id=?",(appt_id,))
    elif existing.get("active"):
        core.run("UPDATE appointments SET active=0,remote_status='deleted',snapshot_at=? WHERE id=?",(core.utcnow(),existing["id"]))
    core.create_opening_from_appointment(existing)

@core.app.post("/native/calendar/sync")
async def sync_calendar(request:Request,authorization:str|None=Header(None)):
    device=_bearer(authorization);artist=core.one("SELECT * FROM artists WHERE id=?",(device["artist_id"],))
    if not artist:raise HTTPException(404,"artist missing")
    body=await request.json();events=body.get("events") or [];now=core.utcnow()
    incoming={str(e.get("id")):e for e in events if e.get("id") and e.get("start_at") and e.get("end_at")}
    previous={r["event_id"]:r for r in core.all_rows("SELECT * FROM native_calendar_snapshot WHERE artist_id=?",(artist["id"],))}
    if previous:
        for event_id,row in previous.items():
            if event_id not in incoming:
                try:_cancel_from_snapshot(artist,event_id,row)
                except Exception as exc:print(f"Native cancellation failed {event_id}: {type(exc).__name__}: {exc}",flush=True)
    core.run("DELETE FROM native_calendar_snapshot WHERE artist_id=?",(artist["id"],))
    for event_id,e in incoming.items():
        core.run("INSERT INTO native_calendar_snapshot(artist_id,event_id,title,start_at,end_at,updated_at) VALUES(?,?,?,?,?,?)",(artist["id"],event_id,str(e.get("title") or "Tattoo"),str(e["start_at"]),str(e["end_at"]),now))
        existing=core.one("SELECT * FROM appointments WHERE artist_id=? AND provider='native' AND remote_id=?",(artist["id"],event_id))
        if existing:core.run("UPDATE appointments SET title=?,starts_at=?,ends_at=?,remote_status='confirmed',active=1,snapshot_at=? WHERE id=?",(str(e.get("title") or "Tattoo"),str(e["start_at"]),str(e["end_at"]),now,existing["id"]))
        else:core.run("INSERT INTO appointments(id,artist_id,provider,remote_id,title,starts_at,ends_at,remote_status,active,snapshot_at) VALUES(?,?,?,?,?,?,?,'confirmed',1,?)",(str(uuid.uuid4()),artist["id"],"native",event_id,str(e.get("title") or "Tattoo"),str(e["start_at"]),str(e["end_at"]),now))
    calendar_id=str(body.get("calendar_id") or device.get("calendar_id") or "")
    core.run("UPDATE native_devices SET last_seen_at=?,calendar_id=? WHERE id=?",(now,calendar_id,device["id"]))
    core.run("UPDATE calendar_accounts SET provider='native',calendar_id=?,connected_at=? WHERE artist_id=?",(calendar_id,now,artist["id"]))
    commands=core.all_rows("SELECT id,kind,payload FROM native_calendar_outbox WHERE artist_id=? AND status='pending' ORDER BY created_at",(artist["id"],))
    return {"ok":True,"commands":[{"id":c["id"],"kind":c["kind"],"payload":json.loads(c["payload"])} for c in commands]}

@core.app.post("/native/calendar/ack/{command_id}")
def ack_calendar(command_id:str,authorization:str|None=Header(None)):
    device=_bearer(authorization)
    row=core.one("SELECT * FROM native_calendar_outbox WHERE id=? AND artist_id=?",(command_id,device["artist_id"]))
    if not row or row.get("status")=="acked":return {"ok":True}
    core.run("UPDATE native_calendar_outbox SET status='acked',acked_at=? WHERE id=? AND artist_id=?",(core.utcnow(),command_id,device["artist_id"]))
    try:
        payload=json.loads(row.get("payload") or "{}")
        booking_id=payload.get("booking_id");opening_id=payload.get("opening_id")
        if booking_id:core.run("UPDATE bookings SET remote_event_id=? WHERE id=?",(f"native:{command_id}",booking_id))
        artist=core.one("SELECT * FROM artists WHERE id=?",(device["artist_id"],));opening=core.one("SELECT * FROM openings WHERE id=?",(opening_id,)) if opening_id else None
        if artist and opening:
            core.send_sms(artist.get("phone"),"EMPTY CHAIR // CALENDAR FIXED ✓\n\n"+core.fmt_when(opening["starts_at"])+" is on your calendar.\n\nNothing else needed.")
            core.event("calendar.native_write_acked",artist["id"],{"opening_id":opening_id,"booking_id":booking_id,"command_id":command_id})
    except Exception as exc:print(f"Native calendar ack bookkeeping failed {command_id}: {type(exc).__name__}: {exc}",flush=True)
    return {"ok":True}


def queue_event_write(artist_id:str,title:str,start_at:str,end_at:str,notes:str="",booking_id:str|None=None,opening_id:str|None=None):
    cid=secrets.token_hex(16);payload={"title":title,"start_at":start_at,"end_at":end_at,"notes":notes}
    if booking_id:payload["booking_id"]=booking_id
    if opening_id:payload["opening_id"]=opening_id
    core.run("INSERT INTO native_calendar_outbox(id,artist_id,kind,payload,status,created_at) VALUES(?,?,?,?,?,?)",(cid,artist_id,"upsert_event",json.dumps(payload,separators=(",",":")),"pending",core.utcnow()));return cid

_original_apple_create_event=core.apple_create_event

def _native_aware_apple_create_event(acct,artist,opening,client):
    if acct and acct.get("provider") in ("native","apple_native"):
        return queue_event_write(artist["id"],f"{client['name']} // Tattoo",opening["starts_at"],opening["ends_at"],"Filled by Empty Chair",opening_id=opening["id"])
    return _original_apple_create_event(acct,artist,opening,client)

core.apple_create_event=_native_aware_apple_create_event
print("Empty Chair 2.0 native calendar bridge loaded // iOS + Android",flush=True)
