"""Runtime compatibility fix for Contest Intelligence classification.

Campaign-linked Concierge traffic was switched to a contest-first experience in
PR #150. Those historical leads were attributed to a campaign, but the profile
JSON did not persist acquisition_mode='contest'. This patch therefore treats
legacy campaign-linked Concierge leads as contest entries unless they explicitly
identify themselves as another acquisition mode such as Tattoo Finder.
"""

import json

import app as core
import concierge_leads
import contest


CONTEST_CHANNELS = {"facebook_group", "facebook_profile"}
NON_CONTEST_MODES = {"tattoo_finder"}


def _is_contest(profile: dict, source: str, campaign_id: str = "") -> bool:
    mode = str(profile.get("acquisition_mode") or "").strip().lower()
    source_text = str(source or "").strip().lower()
    campaign_text = str(campaign_id or "").strip()

    if mode in NON_CONTEST_MODES:
        return False
    return (
        mode == "contest"
        or "contest" in source_text
        or source_text in CONTEST_CHANNELS
        or bool(campaign_text)
    )


def _load_entries(conn, shop_id: str):
    concierge_leads._ensure_table(conn)
    contest._ensure_decisions_table(conn)
    rows = core.db_fetchall(
        conn,
        """
        SELECT l.*, c.name, c.phone, c.email, c.communication_consent,
               c.preferred_styles, c.preferred_artists,
               d.decision AS contest_decision
        FROM concierge_leads l
        LEFT JOIN customers c ON c.id=l.customer_id AND c.shop_id=l.shop_id
        LEFT JOIN contest_decisions d ON d.lead_id=l.id AND d.shop_id=l.shop_id
        WHERE l.shop_id=?
        ORDER BY l.created_at DESC
        LIMIT 500
        """,
        (shop_id,),
    )
    entries = []
    for row in rows:
        item = dict(row)
        try:
            profile = json.loads(item.get("profile_json") or "{}")
        except Exception:
            profile = {}

        acquisition_source = item.get("acquisition_source") or item.get("source")
        campaign_id = item.get("campaign_id") or profile.get("campaign_id") or ""
        if not _is_contest(profile, acquisition_source, campaign_id):
            continue

        score, reasons = contest._review_score(profile)
        item["profile"] = profile
        item["review_score"] = score
        item["review_reasons"] = reasons
        entries.append(item)

    entries.sort(
        key=lambda x: (x["review_score"], x.get("created_at") or ""),
        reverse=True,
    )
    return entries


contest._is_contest = _is_contest
contest._load_entries = _load_entries
print("Contest acquisition classification fix loaded", flush=True)
