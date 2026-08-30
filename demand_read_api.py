"""Read-only production data API for Demand Engine diagnostics.

This module exposes a narrowly-scoped, shop-bound snapshot for remote inspection.
It does not accept arbitrary SQL and it does not expose phone/email contact fields.
"""
import hmac
import json
import os

from fastapi import Request
from fastapi.responses import JSONResponse

import app as core
import concierge_leads
import demand_acquisition

READ_API_KEY = os.getenv("EMPTY_CHAIR_READ_API_KEY", "").strip()
READ_SHOP_ID = os.getenv("EMPTY_CHAIR_READ_SHOP_ID", "").strip()


def _authorized(request: Request) -> bool:
    if not READ_API_KEY:
        return False

    supplied = ""
    auth = (request.headers.get("authorization") or "").strip()
    if auth.lower().startswith("bearer "):
        supplied = auth[7:].strip()
    if not supplied:
        supplied = (request.query_params.get("key") or "").strip()

    if not supplied:
        return False
    try:
        return hmac.compare_digest(supplied, READ_API_KEY)
    except Exception:
        return False


def _safe_profile(raw):
    try:
        profile = json.loads(raw or "{}")
    except Exception:
        profile = {}
    allowed = {
        "project",
        "placement",
        "size",
        "styles",
        "budget",
        "timing",
        "short_notice",
        "travel",
        "artist_vibe",
        "acquisition_mode",
        "market",
    }
    return {k: profile.get(k) for k in allowed if profile.get(k) not in (None, "")}


def _initial(name):
    value = str(name or "").strip()
    return (value[:1].upper() + ".") if value else "Lead"


@core.app.get("/api/admin/demand-data")
def demand_data_snapshot(request: Request, limit: int = 50):
    if not READ_API_KEY or not READ_SHOP_ID:
        return JSONResponse(
            {"error": "read api not configured"},
            status_code=503,
            headers={"Cache-Control": "no-store"},
        )
    if not _authorized(request):
        return JSONResponse(
            {"error": "unauthorized"},
            status_code=401,
            headers={"Cache-Control": "no-store"},
        )

    safe_limit = max(1, min(int(limit or 50), 250))
    conn = core.connect()
    try:
        concierge_leads._ensure_table(conn)
        demand_acquisition._ensure_tables(conn)
        demand_acquisition._ensure_lead_attribution_columns(conn)

        shop = core.db_fetchone(
            conn,
            "SELECT id,name FROM shops WHERE id=? LIMIT 1",
            (READ_SHOP_ID,),
        )
        if not shop:
            return JSONResponse(
                {"error": "configured shop not found"},
                status_code=404,
                headers={"Cache-Control": "no-store"},
            )

        campaigns = core.db_fetchall(
            conn,
            """
            SELECT c.id,c.name,c.channel,c.hook,c.status,c.created_at,
                   i.artist_name,i.studio_name,
                   (SELECT COUNT(*) FROM acquisition_visits v WHERE v.campaign_id=c.id) AS visits,
                   (SELECT COUNT(*) FROM concierge_leads l WHERE l.shop_id=c.shop_id AND l.campaign_id=c.id) AS leads
            FROM acquisition_campaigns c
            LEFT JOIN acquisition_identities i ON i.id=c.identity_id
            WHERE c.shop_id=?
            ORDER BY c.created_at DESC
            """,
            (READ_SHOP_ID,),
        )

        leads = core.db_fetchall(
            conn,
            """
            SELECT l.id,l.source,l.profile_json,l.m4_confidence,l.offer_opt_in,
                   l.created_at,l.updated_at,l.campaign_id,l.acquisition_source,
                   l.acquisition_identity_id,c.name AS customer_name,
                   ac.name AS campaign_name,ac.channel AS campaign_channel,
                   ai.artist_name,ai.studio_name
            FROM concierge_leads l
            LEFT JOIN customers c ON c.id=l.customer_id AND c.shop_id=l.shop_id
            LEFT JOIN acquisition_campaigns ac ON ac.id=l.campaign_id
            LEFT JOIN acquisition_identities ai ON ai.id=l.acquisition_identity_id
            WHERE l.shop_id=?
            ORDER BY l.created_at DESC
            LIMIT ?
            """,
            (READ_SHOP_ID, safe_limit),
        )

        campaign_rows = []
        for row in campaigns:
            item = dict(row)
            visits = int(item.get("visits") or 0)
            leads_count = int(item.get("leads") or 0)
            item["visits"] = visits
            item["leads"] = leads_count
            item["conversion_percent"] = round((leads_count * 100.0 / visits), 1) if visits else None
            campaign_rows.append(item)

        lead_rows = []
        for row in leads:
            item = dict(row)
            lead_rows.append(
                {
                    "id": item.get("id"),
                    "name": _initial(item.get("customer_name")),
                    "created_at": item.get("created_at"),
                    "updated_at": item.get("updated_at"),
                    "source": item.get("acquisition_source") or item.get("source") or "concierge",
                    "campaign_id": item.get("campaign_id"),
                    "campaign_name": item.get("campaign_name"),
                    "campaign_channel": item.get("campaign_channel"),
                    "artist_name": item.get("artist_name"),
                    "studio_name": item.get("studio_name"),
                    "offer_opt_in": bool(item.get("offer_opt_in")),
                    "m4_confidence": int(item.get("m4_confidence") or 0),
                    "profile": _safe_profile(item.get("profile_json")),
                }
            )

        metrics = {
            "active_campaigns": sum(1 for c in campaign_rows if c.get("status") == "active"),
            "visits": sum(int(c.get("visits") or 0) for c in campaign_rows),
            "leads": sum(int(c.get("leads") or 0) for c in campaign_rows),
            "recent_leads_returned": len(lead_rows),
        }

        return JSONResponse(
            {
                "shop": {"id": shop["id"], "name": shop["name"]},
                "metrics": metrics,
                "campaigns": campaign_rows,
                "recent_leads": lead_rows,
                "privacy": {
                    "phone_exposed": False,
                    "email_exposed": False,
                    "names_redacted_to_initial": True,
                    "read_only": True,
                },
            },
            headers={"Cache-Control": "no-store, no-cache, must-revalidate"},
        )
    except Exception as exc:
        conn.rollback()
        return JSONResponse(
            {"error": type(exc).__name__, "detail": str(exc)[:500]},
            status_code=503,
            headers={"Cache-Control": "no-store"},
        )
    finally:
        conn.close()
