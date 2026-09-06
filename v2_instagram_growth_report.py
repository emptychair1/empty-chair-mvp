"""Owner SMS snapshot for the autonomous Instagram engine."""
from __future__ import annotations
import os, threading, time
from datetime import datetime, timezone
import v2_app as core

OWNER_PHONE=os.getenv('EMPTY_CHAIR_OWNER_PHONE','').strip()
INTERVAL=86400

def snapshot():
 def n(q): return int((core.one(q) or {'n':0})['n'] or 0)
 leads=n("SELECT COUNT(*) AS n FROM growth_instagram_leads")
 replies=n("SELECT COUNT(*) AS n FROM growth_instagram_leads WHERE replied_at IS NOT NULL")
 clicks=n("SELECT COUNT(*) AS n FROM growth_instagram_leads WHERE clicked_at IS NOT NULL")
 trials=n("SELECT COUNT(*) AS n FROM growth_instagram_leads WHERE trial_at IS NOT NULL")
 paid=n("SELECT COUNT(*) AS n FROM growth_instagram_leads WHERE paid_at IS NOT NULL")
 total_paid=n("SELECT COUNT(*) AS n FROM artists WHERE LOWER(COALESCE(subscription_status,''))='active'")
 mrr=total_paid*97
 return f"EMPTY CHAIR // GROWTH\ncomments........{leads}\nDMs.............{replies}\nclicks..........{clicks}\ntrials..........{trials}\npaid............{paid}\nMRR.............${mrr:,}\n\nM1: ${mrr:,} / $1,000\nKEEP GOING."

def loop():
 while True:
  try:
   if OWNER_PHONE: core.send_sms(OWNER_PHONE,snapshot())
  except Exception as exc: print(f"Growth report failed: {exc}",flush=True)
  time.sleep(INTERVAL)

if core.WORKER_ENABLED: threading.Thread(target=loop,daemon=True,name='instagram-growth-report').start()
