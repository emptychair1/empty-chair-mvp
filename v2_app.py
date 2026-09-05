"""Empty Chair 2.0 — headless cancellation recovery for individual tattoo artists.

Render imports only this module through bootstrap.py. No legacy Empty Chair modules are
loaded in production.
"""
from __future__ import annotations

import base64
import csv
import hashlib
import hmac
import html
import io
import json
import os
import secrets
import sqlite3
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response

VERSION = "2.0.0"
BASE_URL = os.getenv("EMPTY_CHAIR_BASE_URL", "http://localhost:8000").rstrip("/")
DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
SQLITE_PATH = os.getenv("EMPTY_CHAIR_DB", "empty_chair_v2.db")
SESSION_SECRET = os.getenv("EMPTY_CHAIR_SESSION_SECRET", "change-me-in-production")
WORKER_ENABLED = os.getenv("EMPTY_CHAIR_WORKER_ENABLED", "true").lower() == "true"
WORKER_INTERVAL = max(15, int(os.getenv("EMPTY_CHAIR_WORKER_INTERVAL_SECONDS", "30")))
OFFER_MINUTES = max(5, int(os.getenv("EMPTY_CHAIR_OFFER_MINUTES", "15")))

TWILIO_SID = os.getenv("TWILIO_ACCOUNT_SID", "")
TWILIO_TOKEN = os.getenv("TWILIO_AUTH_TOKEN", "")
TWILIO_FROM = os.getenv("TWILIO_FROM_NUMBER", "")
RESEND_API_KEY = os.getenv("RESEND_API_KEY", "")
EMAIL_FROM = os.getenv("EMPTY_CHAIR_EMAIL_FROM", "Empty Chair <hello@tryemptychair.com>")
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET", "")
SQUARE_APP_ID = os.getenv("SQUARE_APPLICATION_ID", "")
SQUARE_LOCATION_ID = os.getenv("SQUARE_LOCATION_ID", "")
SQUARE_ACCESS_TOKEN = os.getenv("SQUARE_ACCESS_TOKEN", "")
SQUARE_ENV = os.getenv("SQUARE_ENV", "production").lower()
SQUARE_BASE = "https://connect.squareupsandbox.com" if SQUARE_ENV == "sandbox" else "https://connect.squareup.com"
SQUARE_JS = "https://sandbox.web.squarecdn.com/v1/square.js" if SQUARE_ENV == "sandbox" else "https://web.squarecdn.com/v1/square.js"
PAYPAL_CLIENT_ID = os.getenv("PAYPAL_CLIENT_ID", "")
PAYPAL_CLIENT_SECRET = os.getenv("PAYPAL_CLIENT_SECRET", "")
PAYPAL_ENV = os.getenv("PAYPAL_ENV", "production").lower()
PAYPAL_BASE = "https://api-m.sandbox.paypal.com" if PAYPAL_ENV == "sandbox" else "https://api-m.paypal.com"

AMBER, BRIGHT, DIM, OFF, BG = "#FFB000", "#FFD36A", "#805800", "#332300", "#0B0905"
app = FastAPI(title="Empty Chair", version=VERSION, docs_url=None, redoc_url=None)

CHAIR = r"""           ________
         /          \
        /            \
       |              |
       |              |
       |              |
    ___|              |___
   /   |              |   \
  |____|              |____|
       |______________|
        \____________/
             |  |
             |  |
           __|  |__
          |  |  |  |
          |__|__|__|
             |  |
        _____|__|_____
      /                \
     '------------------'"""


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


class DB:
    def __init__(self):
        self.pg = bool(DATABASE_URL)
        if self.pg:
            import psycopg2
            import psycopg2.extras
            self.raw = psycopg2.connect(DATABASE_URL)
            self.dict_cursor = psycopg2.extras.RealDictCursor
        else:
            self.raw = sqlite3.connect(SQLITE_PATH, check_same_thread=False)
            self.raw.row_factory = sqlite3.Row
            self.dict_cursor = None

    def execute(self, q: str, params: tuple[Any, ...] = ()):
        if self.pg:
            cur = self.raw.cursor(cursor_factory=self.dict_cursor)
            q = q.replace("?", "%s")
        else:
            cur = self.raw.cursor()
        cur.execute(q, params)
        return cur

    def commit(self): self.raw.commit()
    def close(self): self.raw.close()


SCHEMA = [
"""CREATE TABLE IF NOT EXISTS artists (id TEXT PRIMARY KEY,name TEXT NOT NULL,email TEXT NOT NULL,phone TEXT NOT NULL,verified INTEGER NOT NULL DEFAULT 0,setup_state TEXT NOT NULL DEFAULT 'IDENTITY',deposit_cents INTEGER NOT NULL DEFAULT 10000,average_value_cents INTEGER NOT NULL DEFAULT 45000,payment_methods TEXT NOT NULL DEFAULT 'cashapp,venmo,card',created_at TEXT NOT NULL,updated_at TEXT NOT NULL)""",
"""CREATE TABLE IF NOT EXISTS otp_codes (artist_id TEXT PRIMARY KEY,code_hash TEXT NOT NULL,expires_at TEXT NOT NULL)""",
"""CREATE TABLE IF NOT EXISTS calendar_accounts (artist_id TEXT PRIMARY KEY,provider TEXT NOT NULL,calendar_id TEXT,access_token TEXT,refresh_token TEXT,token_expires_at TEXT,apple_username TEXT,apple_password TEXT,apple_calendar_url TEXT,connected_at TEXT NOT NULL)""",
"""CREATE TABLE IF NOT EXISTS clients (id TEXT PRIMARY KEY,artist_id TEXT NOT NULL,name TEXT NOT NULL,phone TEXT,email TEXT,styles TEXT NOT NULL DEFAULT '',budget_cents INTEGER NOT NULL DEFAULT 0,short_notice INTEGER NOT NULL DEFAULT 1,completed_count INTEGER NOT NULL DEFAULT 0,no_show_count INTEGER NOT NULL DEFAULT 0,last_offered_at TEXT,opted_out INTEGER NOT NULL DEFAULT 0,created_at TEXT NOT NULL)""",
"""CREATE TABLE IF NOT EXISTS appointments (id TEXT PRIMARY KEY,artist_id TEXT NOT NULL,provider TEXT NOT NULL,remote_id TEXT NOT NULL,title TEXT,starts_at TEXT NOT NULL,ends_at TEXT NOT NULL,remote_status TEXT NOT NULL DEFAULT 'confirmed',active INTEGER NOT NULL DEFAULT 1,snapshot_at TEXT NOT NULL,UNIQUE(artist_id,provider,remote_id))""",
"""CREATE TABLE IF NOT EXISTS openings (id TEXT PRIMARY KEY,artist_id TEXT NOT NULL,source_appointment_id TEXT,starts_at TEXT NOT NULL,ends_at TEXT NOT NULL,title TEXT,value_cents INTEGER NOT NULL,deposit_cents INTEGER NOT NULL,status TEXT NOT NULL DEFAULT 'OPEN',created_at TEXT NOT NULL)""",
"""CREATE TABLE IF NOT EXISTS offers (id TEXT PRIMARY KEY,opening_id TEXT NOT NULL,client_id TEXT NOT NULL,token TEXT UNIQUE NOT NULL,rank INTEGER NOT NULL,status TEXT NOT NULL DEFAULT 'PENDING',sent_at TEXT,expires_at TEXT,created_at TEXT NOT NULL)""",
"""CREATE TABLE IF NOT EXISTS bookings (id TEXT PRIMARY KEY,opening_id TEXT UNIQUE NOT NULL,client_id TEXT NOT NULL,provider TEXT NOT NULL,payment_id TEXT,amount_cents INTEGER NOT NULL,remote_event_id TEXT,created_at TEXT NOT NULL)""",
"""CREATE TABLE IF NOT EXISTS events (id TEXT PRIMARY KEY,artist_id TEXT,kind TEXT NOT NULL,payload TEXT NOT NULL,created_at TEXT NOT NULL)""",
]


def init_db():
    d = DB()
    try:
        for stmt in SCHEMA: d.execute(stmt)
        d.commit()
    finally: d.close()


def one(q: str, params: tuple[Any, ...] = ()):
    d = DB()
    try:
        row = d.execute(q, params).fetchone()
        return dict(row) if row else None
    finally: d.close()


def all_rows(q: str, params: tuple[Any, ...] = ()):
    d = DB()
    try: return [dict(r) for r in d.execute(q, params).fetchall()]
    finally: d.close()


def run(q: str, params: tuple[Any, ...] = ()):
    d = DB()
    try:
        cur = d.execute(q, params); d.commit(); return cur.rowcount
    finally: d.close()


def event(kind: str, artist_id: str | None, payload: dict[str, Any]):
    run("INSERT INTO events(id,artist_id,kind,payload,created_at) VALUES(?,?,?,?,?)",(str(uuid.uuid4()), artist_id, kind, json.dumps(payload,separators=(",",":")), utcnow()))


def sign(value: str) -> str:
    sig = hmac.new(SESSION_SECRET.encode(), value.encode(), hashlib.sha256).hexdigest()
    return f"{value}.{sig}"


def unsign(value: str | None) -> str | None:
    if not value or "." not in value: return None
    raw, sig = value.rsplit(".",1)
    expected = hmac.new(SESSION_SECRET.encode(), raw.encode(), hashlib.sha256).hexdigest()
    return raw if hmac.compare_digest(sig, expected) else None


def current_artist(request: Request):
    aid = unsign(request.cookies.get("ec2"))
    return one("SELECT * FROM artists WHERE id=?",(aid,)) if aid else None


def set_session(response: Response, artist_id: str):
    response.set_cookie("ec2", sign(artist_id), httponly=True, secure=BASE_URL.startswith("https://"), samesite="lax", max_age=31536000)


def clean_phone(value: str) -> str:
    digits = "".join(c for c in value if c.isdigit())
    if len(digits)==10: return "+1"+digits
    if len(digits)==11 and digits[0]=="1": return "+"+digits
    return value.strip()


def normalize_iso(value: str) -> str:
    try: return datetime.fromisoformat(value.replace("Z","+00:00")).astimezone(timezone.utc).isoformat()
    except Exception: return value


def fmt_money(cents: int) -> str:
    return f"${cents/100:,.0f}" if cents%100==0 else f"${cents/100:,.2f}"


def fmt_when(iso: str) -> str:
    try: return datetime.fromisoformat(iso.replace("Z","+00:00")).astimezone().strftime("%a // %-I:%M %p")
    except Exception: return iso


def hours_between(start: str, end: str) -> str:
    try:
        a=datetime.fromisoformat(start.replace("Z","+00:00")); b=datetime.fromisoformat(end.replace("Z","+00:00"))
        return f"{max(.5,(b-a).total_seconds()/3600):g} hr"
    except Exception: return ""


def page(title: str, body: str, *, script: str="", chair: bool=False, head: str="") -> HTMLResponse:
    chair_html=f'<pre class="chair" aria-hidden="true">{html.escape(CHAIR)}</pre>' if chair else ""
    doc=f'''<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover"><meta name="theme-color" content="{BG}"><link rel="manifest" href="/manifest.webmanifest"><title>{html.escape(title)} // Empty Chair</title>{head}<style>:root{{--bg:{BG};--amber:{AMBER};--bright:{BRIGHT};--dim:{DIM};--off:{OFF}}}*{{box-sizing:border-box}}html,body{{margin:0;background:var(--bg);color:var(--amber);font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace}}body{{min-height:100svh;display:flex;justify-content:center}}main{{width:min(100%,540px);min-height:100svh;padding:28px 22px 44px}}header{{display:flex;justify-content:space-between;border-bottom:1px solid var(--off);padding-bottom:12px;margin-bottom:32px;font-size:12px;letter-spacing:.08em}}h1,h2,p{{font-weight:400}}h1{{font-size:22px;letter-spacing:.08em}}.bright{{color:var(--bright)}}.dim{{color:var(--dim)}}.chair{{font-size:clamp(9px,2.15vw,12px);line-height:1.05;margin:32px auto;text-align:left;width:max-content;color:var(--bright);overflow:visible}}.stack{{display:grid;gap:14px}}label{{font-size:12px;color:var(--dim)}}input,select,textarea{{width:100%;background:transparent;color:var(--bright);border:0;border-bottom:1px solid var(--dim);padding:12px 0;font:inherit;outline:none}}button,.button{{display:block;width:100%;padding:15px 12px;border:1px solid var(--amber);background:transparent;color:var(--bright);font:inherit;text-align:center;text-decoration:none;cursor:pointer}}button:hover,.button:hover{{background:var(--off)}}.quiet{{border-color:var(--off);color:var(--amber)}}.center{{text-align:center}}.space{{height:24px}}.status{{display:grid;grid-template-columns:1fr auto;gap:8px;padding:7px 0;border-bottom:1px dotted var(--off)}}.big{{font-size:30px;color:var(--bright)}}small{{color:var(--dim)}}a{{color:var(--bright)}}.error{{border:1px solid var(--amber);padding:14px;margin:14px 0}}</style></head><body><main><header><span>EMPTY CHAIR</span><span>2.0</span></header>{chair_html}{body}</main>{script}</body></html>'''
    return HTMLResponse(doc,headers={"Cache-Control":"no-store"})


def http_json(url: str, method: str="GET", payload: dict|None=None, headers: dict[str,str]|None=None, form: dict[str,str]|None=None) -> dict:
    hdr={"User-Agent":"EmptyChair/2.0"}; hdr.update(headers or {}); data=None
    if payload is not None: data=json.dumps(payload).encode(); hdr.setdefault("Content-Type","application/json")
    elif form is not None: data=urllib.parse.urlencode(form).encode(); hdr.setdefault("Content-Type","application/x-www-form-urlencoded")
    req=urllib.request.Request(url,data=data,headers=hdr,method=method)
    with urllib.request.urlopen(req,timeout=30) as resp:
        raw=resp.read().decode(); return json.loads(raw) if raw else {}


def send_sms(to: str|None, text: str):
    if not to: return
    if not (TWILIO_SID and TWILIO_TOKEN and TWILIO_FROM): print(f"[SMS disabled] {to}: {text}",flush=True); return
    auth=base64.b64encode(f"{TWILIO_SID}:{TWILIO_TOKEN}".encode()).decode()
    form=urllib.parse.urlencode({"To":to,"From":TWILIO_FROM,"Body":text}).encode()
    req=urllib.request.Request(f"https://api.twilio.com/2010-04-01/Accounts/{TWILIO_SID}/Messages.json",data=form,method="POST",headers={"Authorization":f"Basic {auth}","Content-Type":"application/x-www-form-urlencoded"})
    with urllib.request.urlopen(req,timeout=30): pass


def send_email(to: str|None, subject: str, text: str):
    if not to: return
    if not RESEND_API_KEY: print(f"[EMAIL disabled] {to}: {subject}",flush=True); return
    http_json("https://api.resend.com/emails","POST",{"from":EMAIL_FROM,"to":[to],"subject":subject,"text":text},{"Authorization":f"Bearer {RESEND_API_KEY}"})


def score_client(client: dict, opening: dict) -> int:
    score=50+min(20,int(client.get("completed_count") or 0)*4)-min(30,int(client.get("no_show_count") or 0)*10)
    if int(client.get("short_notice") or 0): score+=20
    title=(opening.get("title") or "").lower(); styles=(client.get("styles") or "").lower()
    if styles and any(s.strip() and s.strip() in title for s in styles.split(",")): score+=20
    budget=int(client.get("budget_cents") or 0)
    if budget and budget>=int(opening["value_cents"])*.6: score+=10
    last=client.get("last_offered_at")
    if last:
        try:
            age=datetime.now(timezone.utc)-datetime.fromisoformat(last.replace("Z","+00:00"))
            if age<timedelta(hours=24): score-=50
            elif age<timedelta(days=3): score-=20
        except Exception: pass
    return max(0,min(100,score))


def artist_sms_open(artist,opening,ready):
    send_sms(artist["phone"],f"EMPTY CHAIR // OPEN\n\n{fmt_when(opening['starts_at'])} canceled.\n\n{fmt_money(opening['value_cents'])} AT RISK\n\n{ready} matches ready.\n\nworking...")


def artist_sms_filled(artist,opening,client):
    send_sms(artist["phone"],f"EMPTY CHAIR // FILLED ✓\n\n{client['name']} took {fmt_when(opening['starts_at'])}.\n\ndeposit........{fmt_money(opening['deposit_cents'])} [✓]\ncalendar.................[✓]\n\n{fmt_money(opening['value_cents'])} SAVED")


def artist_sms_empty(artist,opening,tried):
    send_sms(artist["phone"],f"EMPTY CHAIR // EMPTY\n\n{fmt_when(opening['starts_at'])}\n\n{tried} clients tried.\nNo one committed in time.\n\n{fmt_money(opening['value_cents'])} remained open.\n\nWe'll keep learning.")


def client_offer_sms(artist,opening,offer):
    client=one("SELECT * FROM clients WHERE id=?",(offer["client_id"],)); url=f"{BASE_URL}/o/{offer['token']}"
    send_sms(client["phone"],f"EMPTY CHAIR // OPEN\n\n{artist['name']} has an opening.\n\n{fmt_when(opening['starts_at'])}\n{hours_between(opening['starts_at'],opening['ends_at'])}\n{fmt_money(opening['value_cents'])}\n\n+----------------------+\n|   TAKE THE CHAIR     |\n+----------------------+\n{url}\n\nheld for {OFFER_MINUTES} min.\n\nReply STOP to opt out.")


def prepare_offers(opening: dict) -> int:
    clients=all_rows("SELECT * FROM clients WHERE artist_id=? AND opted_out=0 AND phone IS NOT NULL",(opening["artist_id"],))
    ranked=sorted(clients,key=lambda c:score_client(c,opening),reverse=True)[:25]; d=DB()
    try:
        for idx,client in enumerate(ranked,1): d.execute("INSERT INTO offers(id,opening_id,client_id,token,rank,status,created_at) VALUES(?,?,?,?,?,'PENDING',?)",(str(uuid.uuid4()),opening["id"],client["id"],secrets.token_urlsafe(20),idx,utcnow()))
        d.commit()
    finally: d.close()
    return len(ranked)


def send_next_offer(opening_id: str):
    opening=one("SELECT * FROM openings WHERE id=?",(opening_id,))
    if not opening or opening["status"]!="OPEN": return
    if one("SELECT * FROM offers WHERE opening_id=? AND status IN ('SENT','HOLDING') ORDER BY rank LIMIT 1",(opening_id,)): return
    offer=one("SELECT * FROM offers WHERE opening_id=? AND status='PENDING' ORDER BY rank LIMIT 1",(opening_id,))
    if not offer:
        tried=one("SELECT COUNT(*) AS n FROM offers WHERE opening_id=? AND status IN ('SENT','EXPIRED','PASSED')",(opening_id,))["n"]
        run("UPDATE openings SET status='EMPTY' WHERE id=?",(opening_id,)); artist=one("SELECT * FROM artists WHERE id=?",(opening["artist_id"],)); artist_sms_empty(artist,opening,tried); event("opening.empty",opening["artist_id"],{"opening_id":opening_id,"tried":tried}); return
    expires=(datetime.now(timezone.utc)+timedelta(minutes=OFFER_MINUTES)).isoformat(); run("UPDATE offers SET status='SENT',sent_at=?,expires_at=? WHERE id=?",(utcnow(),expires,offer["id"])); run("UPDATE clients SET last_offered_at=? WHERE id=?",(utcnow(),offer["client_id"])); artist=one("SELECT * FROM artists WHERE id=?",(opening["artist_id"],)); offer=one("SELECT * FROM offers WHERE id=?",(offer["id"],)); client_offer_sms(artist,opening,offer); event("offer.sent",opening["artist_id"],{"opening_id":opening_id,"offer_id":offer["id"],"rank":offer["rank"]})


def create_opening_from_appointment(appt: dict):
    if one("SELECT * FROM openings WHERE source_appointment_id=?",(appt["id"],)): return
    artist=one("SELECT * FROM artists WHERE id=?",(appt["artist_id"],)); oid=str(uuid.uuid4())
    run("INSERT INTO openings(id,artist_id,source_appointment_id,starts_at,ends_at,title,value_cents,deposit_cents,status,created_at) VALUES(?,?,?,?,?,?,?,?, 'OPEN', ?)",(oid,artist["id"],appt["id"],appt["starts_at"],appt["ends_at"],appt.get("title"),artist["average_value_cents"],artist["deposit_cents"],utcnow()))
    opening=one("SELECT * FROM openings WHERE id=?",(oid,)); ready=prepare_offers(opening); artist_sms_open(artist,opening,ready); event("opening.open",artist["id"],{"opening_id":oid,"ready":ready}); send_next_offer(oid)


def google_access_token(acct: dict) -> str:
    token=acct.get("access_token") or ""; exp=acct.get("token_expires_at")
    if token and exp:
        try:
            if datetime.fromisoformat(exp.replace("Z","+00:00"))>datetime.now(timezone.utc)+timedelta(minutes=2): return token
        except Exception: pass
    if not acct.get("refresh_token"): return token
    data=http_json("https://oauth2.googleapis.com/token","POST",form={"client_id":GOOGLE_CLIENT_ID,"client_secret":GOOGLE_CLIENT_SECRET,"refresh_token":acct["refresh_token"],"grant_type":"refresh_token"}); token=data["access_token"]; expires=(datetime.now(timezone.utc)+timedelta(seconds=int(data.get("expires_in",3600)))).isoformat(); run("UPDATE calendar_accounts SET access_token=?,token_expires_at=? WHERE artist_id=?",(token,expires,acct["artist_id"])); return token


def google_events(acct: dict) -> list[dict]:
    token=google_access_token(acct)
    if not token: return []
    now=datetime.now(timezone.utc); params={"singleEvents":"true","showDeleted":"true","maxResults":"2500","timeMin":(now-timedelta(days=1)).isoformat().replace("+00:00","Z"),"timeMax":(now+timedelta(days=60)).isoformat().replace("+00:00","Z")}; url=f"https://www.googleapis.com/calendar/v3/calendars/{urllib.parse.quote(acct['calendar_id'] or 'primary',safe='')}/events?{urllib.parse.urlencode(params)}"; data=http_json(url,headers={"Authorization":f"Bearer {token}"}); out=[]
    for item in data.get("items",[]):
        start=(item.get("start") or {}).get("dateTime"); end=(item.get("end") or {}).get("dateTime")
        if start and end: out.append({"id":item["id"],"title":item.get("summary","Tattoo appointment"),"start":normalize_iso(start),"end":normalize_iso(end),"status":item.get("status","confirmed")})
    return out


def parse_ics_events(text: str) -> list[dict]:
    lines=text.replace("\r\n ","").replace("\r\n\t","").replace("\r","").split("\n"); events=[]; cur=None
    for line in lines:
        if line=="BEGIN:VEVENT": cur={}
        elif line=="END:VEVENT" and cur is not None:
            if cur.get("id") and cur.get("start") and cur.get("end"): events.append(cur)
            cur=None
        elif cur is not None and ":" in line:
            key,val=line.split(":",1); key=key.split(";",1)[0]
            if key=="UID": cur["id"]=val
            elif key=="SUMMARY": cur["title"]=val.replace("\\,",",").replace("\\n"," ")
            elif key=="STATUS": cur["status"]=val.lower()
            elif key in ("DTSTART","DTEND"):
                try:
                    dt=datetime.strptime(val,"%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc) if val.endswith("Z") else datetime.strptime(val[:15],"%Y%m%dT%H%M%S").astimezone(); cur["start" if key=="DTSTART" else "end"]=dt.astimezone(timezone.utc).isoformat()
                except Exception: pass
    return events


def caldav_request(url: str,username: str,password: str,body: str,depth: str="0") -> ET.Element:
    auth=base64.b64encode(f"{username}:{password}".encode()).decode(); req=urllib.request.Request(url,data=body.encode(),method="PROPFIND",headers={"Authorization":f"Basic {auth}","Depth":depth,"Content-Type":"application/xml; charset=utf-8"})
    with urllib.request.urlopen(req,timeout=30) as resp: return ET.fromstring(resp.read())


def apple_discover_calendars(username: str,password: str) -> list[tuple[str,str]]:
    root=caldav_request("https://caldav.icloud.com/",username,password,'<?xml version="1.0" encoding="utf-8"?><d:propfind xmlns:d="DAV:"><d:prop><d:current-user-principal/></d:prop></d:propfind>'); href=root.find(".//{DAV:}current-user-principal/{DAV:}href")
    if href is None or not href.text: raise RuntimeError("Apple did not return a CalDAV principal.")
    principal=urllib.parse.urljoin("https://caldav.icloud.com/",href.text); root=caldav_request(principal,username,password,'<?xml version="1.0" encoding="utf-8"?><d:propfind xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav"><d:prop><c:calendar-home-set/></d:prop></d:propfind>'); home=root.find(".//{urn:ietf:params:xml:ns:caldav}calendar-home-set/{DAV:}href")
    if home is None or not home.text: raise RuntimeError("Apple did not return a calendar home.")
    home_url=urllib.parse.urljoin(principal,home.text); root=caldav_request(home_url,username,password,'<?xml version="1.0" encoding="utf-8"?><d:propfind xmlns:d="DAV:"><d:prop><d:displayname/><d:resourcetype/></d:prop></d:propfind>',"1"); calendars=[]
    for response in root.findall(".//{DAV:}response"):
        href_el=response.find("{DAV:}href"); rtype=response.find(".//{DAV:}resourcetype")
        if href_el is None or not href_el.text or rtype is None or rtype.find("{urn:ietf:params:xml:ns:caldav}calendar") is None: continue
        name_el=response.find(".//{DAV:}displayname"); calendars.append(((name_el.text or "Calendar") if name_el is not None else "Calendar",urllib.parse.urljoin(home_url,href_el.text)))
    if not calendars: raise RuntimeError("No Apple calendars found.")
    return calendars


def apple_events(acct: dict) -> list[dict]:
    url=acct.get("apple_calendar_url") or ""
    if not url: return []
    auth=base64.b64encode(f"{acct.get('apple_username','')}:{acct.get('apple_password','')}".encode()).decode(); start=(datetime.now(timezone.utc)-timedelta(days=1)).strftime("%Y%m%dT%H%M%SZ"); end=(datetime.now(timezone.utc)+timedelta(days=60)).strftime("%Y%m%dT%H%M%SZ"); body=f'''<?xml version="1.0" encoding="utf-8"?><c:calendar-query xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav"><d:prop><d:getetag/><c:calendar-data/></d:prop><c:filter><c:comp-filter name="VCALENDAR"><c:comp-filter name="VEVENT"><c:time-range start="{start}" end="{end}"/></c:comp-filter></c:comp-filter></c:filter></c:calendar-query>'''.encode(); req=urllib.request.Request(url,data=body,method="REPORT",headers={"Authorization":f"Basic {auth}","Depth":"1","Content-Type":"application/xml; charset=utf-8"})
    with urllib.request.urlopen(req,timeout=30) as resp: root=ET.fromstring(resp.read())
    out=[]
    for node in root.findall(".//{urn:ietf:params:xml:ns:caldav}calendar-data"): out.extend(parse_ics_events(node.text or ""))
    return out


def notify_problem_once(artist_id: str,kind: str,text: str,hours: int=12):
    recent=one("SELECT * FROM events WHERE artist_id=? AND kind=? ORDER BY created_at DESC LIMIT 1",(artist_id,kind))
    if recent:
        try:
            if datetime.now(timezone.utc)-datetime.fromisoformat(recent["created_at"])<timedelta(hours=hours): return
        except Exception: pass
    artist=one("SELECT * FROM artists WHERE id=?",(artist_id,)); send_sms(artist.get("phone"),text); event(kind,artist_id,{})


def send_digests_if_due(artist: dict):
    now=datetime.now().astimezone(); aid=artist["id"]; week=f"{now.isocalendar().year}-W{now.isocalendar().week:02d}"; kind=f"digest.weekly.{week}"
    if now.weekday()==0 and now.hour>=8 and not one("SELECT * FROM events WHERE artist_id=? AND kind=? LIMIT 1",(aid,kind)):
        since=(datetime.now(timezone.utc)-timedelta(days=7)).isoformat(); stats=one("SELECT COUNT(*) AS cancellations,SUM(CASE WHEN status='FILLED' THEN 1 ELSE 0 END) AS fills,COALESCE(SUM(CASE WHEN status='FILLED' THEN value_cents ELSE 0 END),0) AS recovered FROM openings WHERE artist_id=? AND created_at>=?",(aid,since)); c=int(stats["cancellations"] or 0); f=int(stats["fills"] or 0); r=int(stats["recovered"] or 0); pct=round(100*f/c) if c else 0; body=f"EMPTY CHAIR // WEEK\n\nrecovered........{fmt_money(r)}\ncancellations....{c}\nfills............{f}\nrecovery.........{pct}%\n\nnothing to do."; send_email(artist.get("email"),f"Empty Chair // weekly // {fmt_money(r)} recovered",body); event(kind,aid,stats)
    m=now.strftime("%Y-%m"); kind=f"digest.monthly.{m}"
    if now.day==1 and now.hour>=8 and not one("SELECT * FROM events WHERE artist_id=? AND kind=? LIMIT 1",(aid,kind)):
        first=datetime(now.year,now.month,1,tzinfo=now.tzinfo).astimezone(timezone.utc); prev=(first-timedelta(days=1)).replace(day=1); stats=one("SELECT COUNT(*) AS cancellations,SUM(CASE WHEN status='FILLED' THEN 1 ELSE 0 END) AS fills,COALESCE(SUM(CASE WHEN status='FILLED' THEN value_cents ELSE 0 END),0) AS recovered FROM openings WHERE artist_id=? AND created_at>=? AND created_at<?",(aid,prev.isoformat(),first.isoformat())); c=int(stats["cancellations"] or 0); f=int(stats["fills"] or 0); r=int(stats["recovered"] or 0); pct=round(100*f/c) if c else 0; body=f"EMPTY CHAIR // MONTH\n\nrecovered value..{fmt_money(r)}\ncancellations....{c}\nfills............{f}\nrecovery.........{pct}%\n\nYour cancellation protection receipt."; send_email(artist.get("email"),f"Empty Chair // monthly receipt // {fmt_money(r)} recovered",body); event(kind,aid,stats)


def poll_calendar(artist_id: str):
    acct=one("SELECT * FROM calendar_accounts WHERE artist_id=?",(artist_id,))
    if not acct: return
    try: current=google_events(acct) if acct["provider"]=="google" else apple_events(acct)
    except Exception as exc: event("calendar.error",artist_id,{"error":str(exc)[:500]}); notify_problem_once(artist_id,"alert.calendar",f"EMPTY CHAIR // CHECK CALENDAR\n\nWe lost access to your\ntattoo calendar.\n\nYour chair isn't covered\nuntil we reconnect.\n\n{BASE_URL}/setup/calendar"); return
    seen=set()
    for item in current:
        seen.add(item["id"]); existing=one("SELECT * FROM appointments WHERE artist_id=? AND provider=? AND remote_id=?",(artist_id,acct["provider"],item["id"]))
        if existing:
            if item["status"]=="cancelled" and existing["active"]: run("UPDATE appointments SET active=0,remote_status='cancelled',snapshot_at=? WHERE id=?",(utcnow(),existing["id"])); create_opening_from_appointment(existing)
            else:
                was_inactive=not bool(existing["active"]); run("UPDATE appointments SET title=?,starts_at=?,ends_at=?,remote_status=?,active=?,snapshot_at=? WHERE id=?",(item["title"],item["start"],item["end"],item["status"],0 if item["status"]=="cancelled" else 1,utcnow(),existing["id"]))
                if was_inactive and item["status"]!="cancelled":
                    reopened=one("SELECT * FROM openings WHERE source_appointment_id=? AND status='OPEN'",(existing["id"],))
                    if reopened: run("UPDATE openings SET status='CLOSED' WHERE id=?",(reopened["id"],)); run("UPDATE offers SET status='CLOSED' WHERE opening_id=? AND status IN ('PENDING','SENT','HOLDING')",(reopened["id"],)); artist=one("SELECT * FROM artists WHERE id=?",(artist_id,)); send_sms(artist["phone"],f"EMPTY CHAIR // CLOSED\n\nYour original {fmt_when(reopened['starts_at'])}\nappointment is back.\n\nRecovery stopped.\n\nNothing else needed."); event("opening.closed",artist_id,{"opening_id":reopened["id"]})
        elif item["status"]!="cancelled": run("INSERT INTO appointments(id,artist_id,provider,remote_id,title,starts_at,ends_at,remote_status,active,snapshot_at) VALUES(?,?,?,?,?,?,?,?,1,?)",(str(uuid.uuid4()),artist_id,acct["provider"],item["id"],item["title"],item["start"],item["end"],item["status"],utcnow()))
    low=(datetime.now(timezone.utc)-timedelta(days=1)).isoformat(); high=(datetime.now(timezone.utc)+timedelta(days=60)).isoformat(); previous=all_rows("SELECT * FROM appointments WHERE artist_id=? AND provider=? AND active=1 AND starts_at>=? AND starts_at<=?",(artist_id,acct["provider"],low,high))
    for appt in previous:
        if appt["remote_id"] not in seen: run("UPDATE appointments SET active=0,remote_status='deleted',snapshot_at=? WHERE id=?",(utcnow(),appt["id"])); create_opening_from_appointment(appt)


def expire_offers():
    for offer in all_rows("SELECT * FROM offers WHERE status='SENT' AND expires_at IS NOT NULL AND expires_at<?",(utcnow(),)): run("UPDATE offers SET status='EXPIRED' WHERE id=?",(offer["id"],)); send_next_offer(offer["opening_id"])


def worker_tick():
    expire_offers()
    for artist in all_rows("SELECT * FROM artists WHERE setup_state='ARMED'"): poll_calendar(artist["id"]); send_digests_if_due(artist)


_worker_stop=threading.Event(); _worker_thread:threading.Thread|None=None

def worker_loop():
    while not _worker_stop.is_set():
        try: worker_tick()
        except Exception as exc: print(f"Empty Chair worker error: {exc}",flush=True)
        _worker_stop.wait(WORKER_INTERVAL)


@app.on_event("startup")
def startup():
    global _worker_thread
    init_db()
    if WORKER_ENABLED and (_worker_thread is None or not _worker_thread.is_alive()): _worker_stop.clear(); _worker_thread=threading.Thread(target=worker_loop,name="empty-chair-v2-worker",daemon=True); _worker_thread.start()
    print(f"Empty Chair {VERSION} loaded: worker={WORKER_ENABLED}, db={'postgres' if DATABASE_URL else 'sqlite'}",flush=True)

@app.on_event("shutdown")
def shutdown(): _worker_stop.set()

@app.get("/healthz")
def health(): return {"ok":True,"product":"empty-chair","version":VERSION}

@app.get("/manifest.webmanifest")
def manifest(): return JSONResponse({"name":"Empty Chair","short_name":"Empty Chair","start_url":"/","display":"standalone","background_color":BG,"theme_color":BG,"icons":[{"src":"/icon.svg","sizes":"any","type":"image/svg+xml","purpose":"any maskable"}]},media_type="application/manifest+json")

@app.get("/icon.svg")
def icon():
    svg=f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1024 1024"><rect width="1024" height="1024" fill="{BG}"/><g fill="none" stroke="{AMBER}" stroke-width="24" stroke-linecap="square" stroke-linejoin="miter"><rect x="340" y="150" width="344" height="110" rx="35"/><path d="M300 280h424c55 0 92 57 92 118v115M300 280c-55 0-92 57-92 118v115"/><path d="M330 300v260M694 300v260"/><rect x="185" y="505" width="145" height="70"/><rect x="694" y="505" width="145" height="70"/><path d="M235 575v150h85M789 575v150h-85"/><rect x="300" y="575" width="424" height="150" rx="36"/><path d="M410 725v160M614 725v160M410 785h204"/><path d="M455 775h-55v42h55M569 775h55v42h-55"/><path d="M350 885h324l105 65H245z"/><path d="M300 950h424"/></g></svg>'''; return Response(svg,media_type="image/svg+xml",headers={"Cache-Control":"public,max-age=86400"})

@app.get("/")
def landing(request: Request):
    artist=current_artist(request)
    if artist:
        if artist["setup_state"]=="ARMED": return page("ARMED",'''<div class="center"><h1 class="bright">ARMED.</h1><div class="space"></div><p>calendar................[✓]</p><p>deposits................[✓]</p><p>clients..................[✓]</p><div class="space"></div><p>YOU CAN CLOSE THIS NOW.</p></div>''',chair=True)
        return RedirectResponse("/setup")
    return page("Don't leave it empty",'''<div class="center"><h1>DON'T LEAVE IT EMPTY.</h1><p class="dim">When they cancel, we fill the chair.</p><div class="space"></div><a class="button" href="/setup">START SETUP</a></div>''',chair=True)

@app.get("/setup")
def setup(request: Request):
    artist=current_artist(request)
    if not artist: return page("Setup",'''<h1>WHO ARE YOU?</h1><form method="post" action="/setup/identity" class="stack"><label>name<input name="name" autocomplete="name" required></label><label>email<input type="email" name="email" autocomplete="email" required></label><label>mobile<input name="phone" autocomplete="tel" required></label><button>CONTINUE</button></form>''')
    return RedirectResponse({"VERIFY":"/setup/verify","CALENDAR":"/setup/calendar","PAYMENT":"/setup/payment","CLIENTS":"/setup/clients","ARMED":"/"}.get(artist["setup_state"],"/setup"))

@app.post("/setup/identity")
def identity(name:str=Form(...),email:str=Form(...),phone:str=Form(...)):
    aid=str(uuid.uuid4()); now=utcnow(); phone=clean_phone(phone); run("INSERT INTO artists(id,name,email,phone,verified,setup_state,created_at,updated_at) VALUES(?,?,?,?,0,'VERIFY',?,?)",(aid,name.strip(),email.strip(),phone,now,now)); code=f"{secrets.randbelow(1000000):06d}"; digest=hashlib.sha256((code+SESSION_SECRET).encode()).hexdigest(); exp=(datetime.now(timezone.utc)+timedelta(minutes=10)).isoformat(); run("INSERT INTO otp_codes(artist_id,code_hash,expires_at) VALUES(?,?,?)",(aid,digest,exp)); send_sms(phone,f"EMPTY CHAIR // VERIFY\n\n{code}\n\nCode expires in 10 min."); response=RedirectResponse("/setup/verify",status_code=303); set_session(response,aid); return response

@app.get("/setup/verify")
def verify_page(request:Request):
    artist=current_artist(request)
    if not artist:return RedirectResponse("/setup")
    return page("Verify",f'''<h1>CHECK YOUR PHONE.</h1><p class="dim">code sent to ***{html.escape(artist['phone'][-4:])}</p><form method="post" class="stack"><label>6-digit code<input name="code" inputmode="numeric" maxlength="6" required autofocus></label><button>VERIFY</button></form>''')

@app.post("/setup/verify")
def verify_post(request:Request,code:str=Form(...)):
    artist=current_artist(request)
    if not artist:return RedirectResponse("/setup")
    otp=one("SELECT * FROM otp_codes WHERE artist_id=?",(artist["id"],)); valid=False
    if otp:
        digest=hashlib.sha256((code.strip()+SESSION_SECRET).encode()).hexdigest()
        try: valid=hmac.compare_digest(digest,otp["code_hash"]) and datetime.fromisoformat(otp["expires_at"])>datetime.now(timezone.utc)
        except Exception: pass
    if not valid:return page("Verify",'''<div class="error">THAT CODE DIDN'T WORK.</div><a class="button" href="/setup/verify">TRY AGAIN</a>''')
    run("UPDATE artists SET verified=1,setup_state='CALENDAR',updated_at=? WHERE id=?",(utcnow(),artist["id"])); return RedirectResponse("/setup/calendar",status_code=303)

@app.get("/setup/calendar")
def calendar_setup(request:Request):
    artist=current_artist(request)
    if not artist:return RedirectResponse("/setup")
    acct=one("SELECT * FROM calendar_accounts WHERE artist_id=?",(artist["id"],))
    if acct and (acct["provider"]=="google" or acct.get("apple_calendar_url")): return page("Calendar",f'''<div class="center"><h1 class="bright">CALENDAR CONNECTED [✓]</h1><p>{html.escape(acct['provider'].upper())}</p><a class="button" href="/setup/payment">NEXT</a></div>''')
    google='<a class="button" href="/auth/google/start">[ G ] GOOGLE CALENDAR</a>' if GOOGLE_CLIENT_ID else '<div class="button quiet">[ G ] GOOGLE // NEEDS CONFIG</div>'
    return page("Calendar",f'''<h1>WHERE DO YOUR APPOINTMENTS LIVE?</h1><div class="stack">{google}<a class="button" href="/setup/apple">[ A ] APPLE CALENDAR</a></div>''')

@app.get("/auth/google/start")
def google_start(request:Request):
    artist=current_artist(request)
    if not artist:return RedirectResponse("/setup")
    params={"client_id":GOOGLE_CLIENT_ID,"redirect_uri":f"{BASE_URL}/auth/google/callback","response_type":"code","access_type":"offline","prompt":"consent","scope":"openid email https://www.googleapis.com/auth/calendar","state":sign(artist["id"])}; return RedirectResponse("https://accounts.google.com/o/oauth2/v2/auth?"+urllib.parse.urlencode(params))

@app.get("/auth/google/callback")
def google_callback(code:str,state:str):
    aid=unsign(state); artist=one("SELECT * FROM artists WHERE id=?",(aid,)) if aid else None
    if not artist:return page("Calendar","<div class='error'>CALENDAR CONNECTION FAILED.</div>")
    data=http_json("https://oauth2.googleapis.com/token","POST",form={"code":code,"client_id":GOOGLE_CLIENT_ID,"client_secret":GOOGLE_CLIENT_SECRET,"redirect_uri":f"{BASE_URL}/auth/google/callback","grant_type":"authorization_code"}); expires=(datetime.now(timezone.utc)+timedelta(seconds=int(data.get("expires_in",3600)))).isoformat(); run("INSERT INTO calendar_accounts(artist_id,provider,calendar_id,access_token,refresh_token,token_expires_at,connected_at) VALUES(?,?,?,?,?,?,?) ON CONFLICT(artist_id) DO UPDATE SET provider=excluded.provider,calendar_id=excluded.calendar_id,access_token=excluded.access_token,refresh_token=excluded.refresh_token,token_expires_at=excluded.token_expires_at,connected_at=excluded.connected_at",(aid,"google","primary",data.get("access_token"),data.get("refresh_token"),expires,utcnow())); run("UPDATE artists SET setup_state='PAYMENT',updated_at=? WHERE id=?",(utcnow(),aid)); response=RedirectResponse("/setup/calendar",status_code=303); set_session(response,aid); return response

@app.get("/setup/apple")
def apple_setup(request:Request):
    if not current_artist(request):return RedirectResponse("/setup")
    return page("Apple Calendar",'''<h1>APPLE CALENDAR</h1><p class="dim">Apple requires an app-specific password. Empty Chair uses it only to watch and write your tattoo calendar.</p><form method="post" class="stack"><label>Apple ID<input type="email" name="username" required></label><label>app-specific password<input type="password" name="password" required></label><button>FIND MY CALENDARS</button></form>''')

@app.post("/setup/apple")
def apple_post(request:Request,username:str=Form(...),password:str=Form(...)):
    artist=current_artist(request)
    if not artist:return RedirectResponse("/setup")
    run("INSERT INTO calendar_accounts(artist_id,provider,calendar_id,apple_username,apple_password,apple_calendar_url,connected_at) VALUES(?,?,?,?,?,?,?) ON CONFLICT(artist_id) DO UPDATE SET provider=excluded.provider,calendar_id=excluded.calendar_id,apple_username=excluded.apple_username,apple_password=excluded.apple_password,apple_calendar_url=excluded.apple_calendar_url,connected_at=excluded.connected_at",(artist["id"],"apple","",username.strip(),password.strip(),"",utcnow())); return RedirectResponse("/setup/apple/select",status_code=303)

@app.get("/setup/apple/select")
def apple_select(request:Request):
    artist=current_artist(request)
    if not artist:return RedirectResponse("/setup")
    acct=one("SELECT * FROM calendar_accounts WHERE artist_id=?",(artist["id"],))
    try: calendars=apple_discover_calendars(acct["apple_username"],acct["apple_password"])
    except Exception as exc:return page("Apple Calendar",f'''<div class="error">APPLE CALENDAR COULDN'T CONNECT.<br><br>{html.escape(str(exc))}</div><a class="button" href="/setup/apple">TRY AGAIN</a><div class="space"></div><form method="post" action="/setup/apple/manual" class="stack"><label>advanced // CalDAV calendar URL<input type="url" name="calendar_url" required></label><button>USE THIS CALENDAR</button></form>''')
    options="".join(f'<label><input type="radio" name="calendar_url" value="{html.escape(url,quote=True)}" required> {html.escape(name)}</label>' for name,url in calendars); return page("Apple Calendar",f'''<h1>WHICH ONE HOLDS TATTOOS?</h1><form method="post" class="stack">{options}<button>USE THIS CALENDAR</button></form>''')

@app.post("/setup/apple/select")
def apple_select_post(request:Request,calendar_url:str=Form(...)):
    artist=current_artist(request)
    if not artist:return RedirectResponse("/setup")
    run("UPDATE calendar_accounts SET calendar_id='selected',apple_calendar_url=?,connected_at=? WHERE artist_id=?",(calendar_url,utcnow(),artist["id"])); run("UPDATE artists SET setup_state='PAYMENT',updated_at=? WHERE id=?",(utcnow(),artist["id"])); return RedirectResponse("/setup/calendar",status_code=303)

@app.post("/setup/apple/manual")
def apple_manual(request:Request,calendar_url:str=Form(...)): return apple_select_post(request,calendar_url)

@app.get("/setup/payment")
def payment_setup(request:Request):
    artist=current_artist(request)
    if not artist:return RedirectResponse("/setup")
    return page("Deposits",f'''<h1>HOW SHOULD CLIENTS LOCK IN?</h1><form method="post" class="stack"><label>default deposit<input type="number" name="deposit" min="1" step="1" value="{artist['deposit_cents']//100}" required></label><label>average appointment value<input type="number" name="average" min="1" step="1" value="{artist['average_value_cents']//100}" required></label><label><input type="checkbox" name="cashapp" value="1" checked> CASH APP</label><label><input type="checkbox" name="venmo" value="1" checked> VENMO</label><label><input type="checkbox" name="card" value="1" checked> CARD</label><button>CONTINUE</button></form>''')

@app.post("/setup/payment")
def payment_post(request:Request,deposit:int=Form(...),average:int=Form(...),cashapp:str|None=Form(None),venmo:str|None=Form(None),card:str|None=Form(None)):
    artist=current_artist(request)
    if not artist:return RedirectResponse("/setup")
    methods=[n for n,v in (("cashapp",cashapp),("venmo",venmo),("card",card)) if v] or ["card"]; run("UPDATE artists SET deposit_cents=?,average_value_cents=?,payment_methods=?,setup_state='CLIENTS',updated_at=? WHERE id=?",(deposit*100,average*100,",".join(methods),utcnow(),artist["id"])); return RedirectResponse("/setup/clients",status_code=303)

@app.get("/setup/clients")
def clients_page(request:Request):
    artist=current_artist(request)
    if not artist:return RedirectResponse("/setup")
    count=one("SELECT COUNT(*) AS n FROM clients WHERE artist_id=?",(artist["id"],))["n"]; return page("Clients",f'''<h1>WHO CAN WE CALL?</h1><p class="big">{count}</p><p class="dim">clients ready</p><form method="post" action="/setup/clients/upload" enctype="multipart/form-data" class="stack"><label>UPLOAD CLIENTS // CSV<input type="file" name="file" accept=".csv,text/csv" required></label><small>columns: name, phone, email, styles, budget, short_notice, completed_count, no_show_count</small><button>IMPORT</button></form><div class="space"></div><a class="button" href="/setup/armed">ARM EMPTY CHAIR</a>''')

@app.post("/setup/clients/upload")
async def clients_upload(request:Request,file:UploadFile=File(...)):
    artist=current_artist(request)
    if not artist:return RedirectResponse("/setup")
    reader=csv.DictReader(io.StringIO((await file.read()).decode("utf-8-sig",errors="replace"))); n=0
    for row in reader:
        name=(row.get("name") or "").strip(); phone=clean_phone(row.get("phone") or "")
        if not name or not phone:continue
        budget_raw="".join(c for c in (row.get("budget") or "") if c.isdigit() or c=="."); budget=int(float(budget_raw or 0)*100); run("INSERT INTO clients(id,artist_id,name,phone,email,styles,budget_cents,short_notice,completed_count,no_show_count,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",(str(uuid.uuid4()),artist["id"],name,phone,(row.get("email") or "").strip(),(row.get("styles") or "").strip(),budget,0 if str(row.get("short_notice","1")).lower() in ("0","false","no") else 1,int(row.get("completed_count") or 0),int(row.get("no_show_count") or 0),utcnow())); n+=1
    event("clients.imported",artist["id"],{"count":n}); return RedirectResponse("/setup/clients",status_code=303)

@app.get("/setup/armed")
def armed(request:Request):
    artist=current_artist(request)
    if not artist:return RedirectResponse("/setup")
    acct=one("SELECT * FROM calendar_accounts WHERE artist_id=?",(artist["id"],)); count=one("SELECT COUNT(*) AS n FROM clients WHERE artist_id=?",(artist["id"],))["n"]
    if not acct:return RedirectResponse("/setup/calendar")
    if count==0:return page("Clients","<div class='error'>ADD AT LEAST ONE CLIENT BEFORE ARMING.</div><a class='button' href='/setup/clients'>BACK</a>")
    run("UPDATE artists SET setup_state='ARMED',updated_at=? WHERE id=?",(utcnow(),artist["id"]));
    try: poll_calendar(artist["id"])
    except Exception: pass
    return RedirectResponse("/",status_code=303)

@app.get("/o/{token}")
def offer_page(token:str):
    offer=one("SELECT * FROM offers WHERE token=?",(token,))
    if not offer:return page("Gone","<h1>EMPTY CHAIR // GONE</h1><p>That chair is no longer available.</p>")
    opening=one("SELECT * FROM openings WHERE id=?",(offer["opening_id"],)); artist=one("SELECT * FROM artists WHERE id=?",(opening["artist_id"],))
    if offer["status"] not in ("SENT","HOLDING") or opening["status"]!="OPEN":return page("Taken","<h1>EMPTY CHAIR // TAKEN</h1><p>Someone beat you to it.</p>")
    return page("Open",f'''<div class="center"><h1>{html.escape(artist['name'].upper())}<br>HAS AN OPENING.</h1><div class="space"></div><p class="big">{html.escape(fmt_when(opening['starts_at']))}</p><p>{html.escape(hours_between(opening['starts_at'],opening['ends_at']))}</p><p>{fmt_money(opening['value_cents'])}</p><div class="space"></div><p class="dim">DEPOSIT</p><p class="big">{fmt_money(opening['deposit_cents'])}</p><a class="button" href="/o/{token}/take">TAKE THE CHAIR</a></div>''')

@app.get("/o/{token}/take")
def take_page(token:str):
    offer=one("SELECT * FROM offers WHERE token=?",(token,))
    if not offer or offer["status"]!="SENT":return RedirectResponse(f"/o/{token}")
    opening=one("SELECT * FROM openings WHERE id=?",(offer["opening_id"],)); return page("Take",f'''<div class="center"><h1>CAN YOU MAKE IT?</h1><p class="big">{html.escape(fmt_when(opening['starts_at']))}</p><form method="post"><button>YES</button></form><div class="space"></div><form method="post" action="/o/{token}/pass"><button class="quiet">NO</button></form></div>''')

@app.post("/o/{token}/take")
def take_post(token:str):
    offer=one("SELECT * FROM offers WHERE token=?",(token,))
    if not offer or offer["status"]!="SENT":return RedirectResponse(f"/o/{token}",status_code=303)
    run("UPDATE offers SET status='HOLDING' WHERE id=?",(offer["id"],)); return RedirectResponse(f"/o/{token}/pay",status_code=303)

@app.post("/o/{token}/pass")
def pass_offer(token:str):
    offer=one("SELECT * FROM offers WHERE token=?",(token,))
    if offer and offer["status"] in ("SENT","HOLDING"):run("UPDATE offers SET status='PASSED' WHERE id=?",(offer["id"],));send_next_offer(offer["opening_id"])
    return page("Passed","<h1>EMPTY CHAIR // PASSED</h1><p>Got it. We'll give the chair to someone else.</p>")

@app.get("/o/{token}/pay")
def pay_page(token:str):
    offer=one("SELECT * FROM offers WHERE token=?",(token,))
    if not offer or offer["status"]!="HOLDING":return RedirectResponse(f"/o/{token}")
    opening=one("SELECT * FROM openings WHERE id=?",(offer["opening_id"],)); artist=one("SELECT * FROM artists WHERE id=?",(opening["artist_id"],)); methods=set((artist["payment_methods"] or "").split(",")); controls=[]; js=""; head=""
    if ("cashapp" in methods or "card" in methods) and SQUARE_APP_ID and SQUARE_LOCATION_ID and SQUARE_ACCESS_TOKEN:
        head=f'<script src="{SQUARE_JS}"></script>'
        if "cashapp" in methods:controls.append('<div id="cashapp"></div>')
        if "card" in methods:controls.append('<div id="card"></div><button id="card-pay" type="button">CARD</button>')
        cash=f'''const pr=payments.paymentRequest({{countryCode:'US',currencyCode:'USD',total:{{amount:amount.toFixed(2),label:'Deposit'}}}});const cap=await payments.cashAppPay(pr,{{redirectURL:location.href,referenceId:{json.dumps(offer['id'])}}});cap.addEventListener('ontokenization',e=>{{if(e.detail.tokenResult?.status==='OK')sendToken(e.detail.tokenResult.token)}});await cap.attach('#cashapp');''' if "cashapp" in methods else ""
        card=f'''const card=await payments.card();await card.attach('#card');document.getElementById('card-pay').onclick=async()=>{{const result=await card.tokenize();if(result.status==='OK')sendToken(result.token);}};''' if "card" in methods else ""
        js=f'''<script>(async()=>{{const payments=Square.payments({json.dumps(SQUARE_APP_ID)},{json.dumps(SQUARE_LOCATION_ID)});const amount={opening['deposit_cents']/100:.2f};async function sendToken(source){{const r=await fetch('/o/{token}/square',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{source_id:source}})}});const j=await r.json();if(j.redirect)location.href=j.redirect;else alert(j.error||'Payment did not land.');}}{cash}{card}}})().catch(e=>console.error(e));</script>'''
    if "venmo" in methods and PAYPAL_CLIENT_ID and PAYPAL_CLIENT_SECRET:controls.append(f'<a class="button" href="/o/{token}/venmo">VENMO</a>')
    if not controls:controls.append('<div class="error">PAYMENT CONNECTION REQUIRED.</div>')
    return page("Payment",f'''<div class="center"><h1>LOCK IT IN.</h1><p class="big">{fmt_money(opening['deposit_cents'])}</p></div><div class="stack">{"".join(controls)}</div><p class="dim center">applied to your tattoo.</p>''',script=js,head=head)

@app.post("/o/{token}/square")
async def square_pay(token:str,request:Request):
    offer=one("SELECT * FROM offers WHERE token=?",(token,))
    if not offer or offer["status"]!="HOLDING":return JSONResponse({"error":"Chair is no longer held."},status_code=409)
    opening=one("SELECT * FROM openings WHERE id=?",(offer["opening_id"],)); body=await request.json()
    try:
        data=http_json(f"{SQUARE_BASE}/v2/payments","POST",{"source_id":body["source_id"],"idempotency_key":offer["id"],"amount_money":{"amount":int(opening["deposit_cents"]),"currency":"USD"},"location_id":SQUARE_LOCATION_ID,"reference_id":opening["id"],"note":f"Empty Chair deposit // {fmt_when(opening['starts_at'])}"},{"Authorization":f"Bearer {SQUARE_ACCESS_TOKEN}","Square-Version":"2026-08-20"}); payment=data.get("payment") or {}
        if payment.get("status") not in ("COMPLETED","APPROVED"):raise RuntimeError("Square did not complete the payment")
        finalize_booking(offer,"square",payment.get("id")); return {"redirect":f"/o/{token}/yours"}
    except Exception as exc:return JSONResponse({"error":str(exc)},status_code=400)


def paypal_token() -> str:
    auth=base64.b64encode(f"{PAYPAL_CLIENT_ID}:{PAYPAL_CLIENT_SECRET}".encode()).decode(); return http_json(f"{PAYPAL_BASE}/v1/oauth2/token","POST",headers={"Authorization":f"Basic {auth}"},form={"grant_type":"client_credentials"})["access_token"]

@app.get("/o/{token}/venmo")
def venmo_start(token:str):
    offer=one("SELECT * FROM offers WHERE token=?",(token,))
    if not offer or offer["status"]!="HOLDING":return RedirectResponse(f"/o/{token}")
    opening=one("SELECT * FROM openings WHERE id=?",(offer["opening_id"],)); client=one("SELECT * FROM clients WHERE id=?",(offer["client_id"],)); payload={"intent":"CAPTURE","purchase_units":[{"reference_id":opening["id"],"amount":{"currency_code":"USD","value":f"{opening['deposit_cents']/100:.2f}"}}],"payment_source":{"venmo":{"experience_context":{"brand_name":"EMPTY CHAIR","shipping_preference":"NO_SHIPPING","user_action":"PAY_NOW","return_url":f"{BASE_URL}/o/{token}/venmo/return","cancel_url":f"{BASE_URL}/o/{token}/pay"}}}}
    if client.get("email"):payload["payment_source"]["venmo"]["email_address"]=client["email"]
    data=http_json(f"{PAYPAL_BASE}/v2/checkout/orders","POST",payload,{"Authorization":f"Bearer {paypal_token()}","PayPal-Request-Id":offer["id"]}); run("UPDATE offers SET sent_at=? WHERE id=?",(data.get("id"),offer["id"]))
    for link in data.get("links",[]):
        if link.get("rel") in ("payer-action","payer_action","approve"):return RedirectResponse(link["href"])
    return page("Payment","<div class='error'>VENMO COULD NOT OPEN.</div>")

@app.get("/o/{token}/venmo/return")
def venmo_return(token:str):
    offer=one("SELECT * FROM offers WHERE token=?",(token,))
    if not offer or offer["status"]!="HOLDING":return RedirectResponse(f"/o/{token}")
    order_id=offer.get("sent_at")
    if not order_id:return page("Payment","<div class='error'>VENMO ORDER MISSING.</div>")
    data=http_json(f"{PAYPAL_BASE}/v2/checkout/orders/{urllib.parse.quote(order_id)}/capture","POST",{}, {"Authorization":f"Bearer {paypal_token()}","PayPal-Request-Id":offer["id"]+"-capture"})
    if data.get("status")!="COMPLETED":return page("Payment","<div class='error'>VENMO PAYMENT DID NOT LAND.</div>")
    finalize_booking(offer,"venmo",order_id); return RedirectResponse(f"/o/{token}/yours",status_code=303)


def google_create_event(acct,artist,opening,client):
    payload={"summary":f"{client['name']} // Tattoo","description":"Filled by Empty Chair","start":{"dateTime":opening["starts_at"]},"end":{"dateTime":opening["ends_at"]}}
    if client.get("email"):payload["attendees"]=[{"email":client["email"]}]
    return http_json(f"https://www.googleapis.com/calendar/v3/calendars/{urllib.parse.quote(acct['calendar_id'] or 'primary',safe='')}/events","POST",payload,{"Authorization":f"Bearer {google_access_token(acct)}"}).get("id")


def apple_create_event(acct,artist,opening,client):
    uid=str(uuid.uuid4()); dt=lambda s:datetime.fromisoformat(s.replace("Z","+00:00")).astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ"); ics=f"BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:-//Empty Chair//2.0//EN\r\nBEGIN:VEVENT\r\nUID:{uid}\r\nDTSTAMP:{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}\r\nDTSTART:{dt(opening['starts_at'])}\r\nDTEND:{dt(opening['ends_at'])}\r\nSUMMARY:{client['name']} // Tattoo\r\nDESCRIPTION:Filled by Empty Chair\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n".encode(); url=acct["apple_calendar_url"].rstrip("/")+"/"+uid+".ics"; auth=base64.b64encode(f"{acct['apple_username']}:{acct['apple_password']}".encode()).decode(); req=urllib.request.Request(url,data=ics,method="PUT",headers={"Authorization":f"Basic {auth}","Content-Type":"text/calendar; charset=utf-8","If-None-Match":"*"})
    with urllib.request.urlopen(req,timeout=30):pass
    return uid


def finalize_booking(offer:dict,provider:str,payment_id:str|None):
    opening=one("SELECT * FROM openings WHERE id=?",(offer["opening_id"],))
    if not opening or opening["status"]!="OPEN":return
    client=one("SELECT * FROM clients WHERE id=?",(offer["client_id"],)); artist=one("SELECT * FROM artists WHERE id=?",(opening["artist_id"],)); acct=one("SELECT * FROM calendar_accounts WHERE artist_id=?",(artist["id"],)); remote=None
    try:remote=google_create_event(acct,artist,opening,client) if acct["provider"]=="google" else apple_create_event(acct,artist,opening,client)
    except Exception as exc:event("calendar.write_error",artist["id"],{"opening_id":opening["id"],"error":str(exc)[:500]})
    run("UPDATE offers SET status='YOURS' WHERE id=?",(offer["id"],)); run("UPDATE offers SET status='TAKEN' WHERE opening_id=? AND id<>? AND status IN ('PENDING','SENT','HOLDING')",(opening["id"],offer["id"])); run("UPDATE openings SET status='FILLED' WHERE id=?",(opening["id"],)); run("INSERT INTO bookings(id,opening_id,client_id,provider,payment_id,amount_cents,remote_event_id,created_at) VALUES(?,?,?,?,?,?,?,?)",(str(uuid.uuid4()),opening["id"],client["id"],provider,payment_id,opening["deposit_cents"],remote,utcnow())); artist_sms_filled(artist,opening,client); text=f"EMPTY CHAIR // YOURS\n\n+----------------------+\n|     TAKE A SEAT.     |\n+----------------------+\n\n{artist['name']}\n{fmt_when(opening['starts_at'])}\n\ndeposit..........{fmt_money(opening['deposit_cents'])} [✓]\nappointment...........[✓]\n\nYou're booked."; send_sms(client.get("phone"),text); send_email(client.get("email"),f"You got the chair // {artist['name']} // {fmt_when(opening['starts_at'])}",text+"\n\n"+CHAIR+"\n\nTAKE A SEAT."); event("opening.filled",artist["id"],{"opening_id":opening["id"],"client_id":client["id"],"payment_provider":provider})

@app.get("/o/{token}/yours")
def yours(token:str):
    offer=one("SELECT * FROM offers WHERE token=?",(token,))
    if not offer or offer["status"]!="YOURS":return RedirectResponse(f"/o/{token}")
    opening=one("SELECT * FROM openings WHERE id=?",(offer["opening_id"],)); artist=one("SELECT * FROM artists WHERE id=?",(opening["artist_id"],)); return page("Yours",f'''<div class="center"><h1>EMPTY CHAIR // YOURS</h1></div><div class="center"><h1 class="bright">TAKE A SEAT.</h1><p>{html.escape(artist['name'].upper())}</p><p class="big">{html.escape(fmt_when(opening['starts_at']))}</p><div class="status"><span>deposit</span><span>{fmt_money(opening['deposit_cents'])} [✓]</span></div><div class="status"><span>appointment</span><span>[✓]</span></div></div>''',chair=True)

@app.post("/twilio/inbound")
def twilio_inbound(From:str=Form(""),Body:str=Form("")):
    if Body.strip().upper()=="STOP":run("UPDATE clients SET opted_out=1 WHERE phone=?",(clean_phone(From),))
    return Response("<Response></Response>",media_type="application/xml")

@app.get("/internal/tick")
def internal_tick(request:Request):
    if not current_artist(request):return JSONResponse({"error":"unauthorized"},status_code=401)
    worker_tick(); return {"ok":True}

init_db()
