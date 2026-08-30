"""One-time safe repair for tracked Concierge leads filed under the demo shop.

Only moves leads whose saved profile contains a campaign_id that resolves to an
active acquisition campaign owned by a different shop. General demo leads are
never touched.
"""
import json

import app as core

DEMO_SHOP_ID = "shop_live_demo"


def repair_misfiled_campaign_leads():
    conn = core.connect()
    moved = 0
    try:
        rows = core.db_fetchall(
            conn,
            "SELECT id,customer_id,profile_json FROM concierge_leads WHERE shop_id=? ORDER BY created_at DESC LIMIT 1000",
            (DEMO_SHOP_ID,),
        )
        for row in rows:
            try:
                profile = json.loads(row["profile_json"] or "{}")
            except Exception:
                continue
            campaign_id = str(profile.get("campaign_id") or "").strip()
            if not campaign_id:
                continue
            campaign = core.db_fetchone(
                conn,
                "SELECT shop_id FROM acquisition_campaigns WHERE id=? AND status='active' LIMIT 1",
                (campaign_id,),
            )
            if not campaign:
                continue
            target_shop = str(campaign["shop_id"] or "").strip()
            if not target_shop or target_shop == DEMO_SHOP_ID:
                continue
            customer = core.db_fetchone(
                conn,
                "SELECT id,shop_id FROM customers WHERE id=? LIMIT 1",
                (row["customer_id"],),
            )
            if not customer or str(customer["shop_id"] or "") != DEMO_SHOP_ID:
                continue
            core.db_execute(conn, "UPDATE customers SET shop_id=?,updated_at=? WHERE id=? AND shop_id=?", (target_shop, core.now_iso(), row["customer_id"], DEMO_SHOP_ID))
            core.db_execute(conn, "UPDATE concierge_leads SET shop_id=?,updated_at=? WHERE id=? AND shop_id=?", (target_shop, core.now_iso(), row["id"], DEMO_SHOP_ID))
            moved += 1
        conn.commit()
        if moved:
            print(f"Concierge campaign repair moved {moved} lead(s) to campaign owner shop.", flush=True)
    except Exception as exc:
        conn.rollback()
        print(f"Concierge campaign repair skipped: {type(exc).__name__}: {exc}", flush=True)
    finally:
        conn.close()


repair_misfiled_campaign_leads()
