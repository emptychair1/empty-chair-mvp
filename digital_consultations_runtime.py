"""Safe runtime wiring for Digital Consultations.

This module only patches Python callables at import time. It performs no database
queries, table creation, backfills, Twilio calls, or network I/O during startup.
"""
import app as core
import concierge_leads
import concierge_sms

_PATCHED = False
_ORIGINAL_SAVE = concierge_leads.save_concierge_profile
_ORIGINAL_RENDER = concierge_leads._render_leads


def _save_with_consultation(shop_id, profile, confidence):
    customer_id, lead_id = _ORIGINAL_SAVE(shop_id, profile, confidence)
    try:
        concierge_sms.start_digital_consultation(shop_id, customer_id, lead_id)
    except Exception as exc:
        try:
            core.event("consultation.start_failed", "customer", customer_id, str(exc)[:500])
        except Exception:
            pass
    return customer_id, lead_id


def _render_with_consultations(shop, leads):
    rendered = _ORIGINAL_RENDER(shop, leads)
    old = "<a class='btn' href='/concierge'>Open Concierge</a>"
    new = "<a class='back' href='/consultations'>Digital Consultations</a><a class='btn' href='/concierge'>Open Concierge</a>"
    return rendered.replace(old, new)


def install():
    global _PATCHED
    if _PATCHED:
        return
    concierge_leads.save_concierge_profile = _save_with_consultation
    concierge_leads._render_leads = _render_with_consultations
    _PATCHED = True


install()
