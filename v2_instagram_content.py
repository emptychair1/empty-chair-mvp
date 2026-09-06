"""Revenue-oriented Instagram content queue for Empty Chair."""
from __future__ import annotations
import hashlib, json, random, threading, time, uuid
from datetime import datetime, timezone
import v2_app as core

SCHEMA="""CREATE TABLE IF NOT EXISTS growth_content (id TEXT PRIMARY KEY,hook TEXT NOT NULL,body TEXT NOT NULL,caption TEXT NOT NULL,angle TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'READY',score REAL NOT NULL DEFAULT 1,created_at TEXT NOT NULL,published_at TEXT,media_id TEXT UNIQUE)"""
ANGLES=[
("pain","YOUR {v} APPOINTMENT JUST CANCELED.","A cancellation should not become your day off."),
("math","TWO {v} CANCELLATIONS A MONTH.","That is {y} a year disappearing from your calendar."),
("behavior","STILL POSTING 'LAST MINUTE OPENING'?","Your replacement client should already be waiting."),
("product","CANCELED -> FILLED.","Empty Chair finds a qualified client, takes the deposit, and puts them on your calendar."),
("proof","THE CHAIR WAS EMPTY. THEN IT WASN'T.","When they cancel, we fill the chair."),
]

def now(): return datetime.now(timezone.utc).isoformat()
def init():
 d=core.DB()
 try: d.execute(SCHEMA); d.commit()
 finally: d.close()

def seed(n=60):
 if int((core.one("SELECT COUNT(*) AS n FROM growth_content") or {"n":0})["n"]): return
 vals=[350,400,450,500,600,750]
 for i in range(n):
  angle,hook,body=ANGLES[i%len(ANGLES)]; v=random.choice(vals); money=f"${v}"; yearly=f"${v*24:,}"
  h=hook.format(v=money,y=yearly); b=body.format(v=money,y=yearly)
  caption=f"{h}\n\n{b}\n\nTATTOO ARTIST? COMMENT CHAIR.\n\nWHEN THEY CANCEL, WE FILL THE CHAIR."
  ident=hashlib.sha1(f"{angle}:{h}:{i}".encode()).hexdigest()
  core.run("INSERT INTO growth_content(id,hook,body,caption,angle,status,score,created_at) VALUES(?,?,?,?,?,?,?,?)",(ident,h,b,caption,angle,"READY",1,now()))

def next_content():
 return core.one("SELECT * FROM growth_content WHERE status='READY' ORDER BY score DESC,created_at ASC LIMIT 1")

def mark_published(content_id,media_id):
 core.run("UPDATE growth_content SET status='PUBLISHED',published_at=?,media_id=? WHERE id=?",(now(),media_id,content_id))
 core.event("growth.instagram_content_published",None,{"content_id":content_id,"media_id":media_id})

init(); seed()
