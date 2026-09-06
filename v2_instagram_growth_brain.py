"""Revenue feedback loop for Instagram acquisition."""
from __future__ import annotations
import json, threading, time
import v2_app as core
import v2_instagram_growth as growth

INTERVAL=1800

def learn():
    rows=core.all_rows("""SELECT c.id,c.score,c.media_id,
      COUNT(l.id) AS leads,
      SUM(CASE WHEN l.clicked_at IS NOT NULL THEN 1 ELSE 0 END) AS clicks,
      SUM(CASE WHEN l.trial_at IS NOT NULL THEN 1 ELSE 0 END) AS trials,
      SUM(CASE WHEN l.paid_at IS NOT NULL THEN 1 ELSE 0 END) AS paid
      FROM growth_content c LEFT JOIN growth_instagram_leads l ON l.media_id=c.media_id
      WHERE c.status='PUBLISHED' GROUP BY c.id,c.score,c.media_id""")
    for r in rows:
        leads=int(r.get('leads') or 0); clicks=int(r.get('clicks') or 0); trials=int(r.get('trials') or 0); paid=int(r.get('paid') or 0)
        # Revenue dominates; trial/click/lead are progressively weaker evidence.
        score=1 + leads*.2 + clicks*.5 + trials*2 + paid*20
        core.run("UPDATE growth_content SET score=? WHERE id=?",(score,r['id']))

def loop():
    while True:
        try:
            growth.reconcile(); learn()
        except Exception as exc: print(f"IG growth brain failed: {exc}",flush=True)
        time.sleep(INTERVAL)

if core.WORKER_ENABLED:
    threading.Thread(target=loop,daemon=True,name='instagram-growth-brain').start()
