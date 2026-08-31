"""Runtime wiring for Digital Consultations.

Loaded by the explicit production bootstrap through settings_sms_test.
This keeps Concierge lead capture authoritative while adding a consultation
thread immediately after a lead is persisted.
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
        # Never lose a valid Concierge lead because Twilio or the consultation
        # layer is temporarily unavailable.
        try:
            core.event(
                "consultation.start_failed",
                "customer",
                customer_id,
                str(exc),
            )
        except Exception:
            pass
    return customer_id, lead_id


def _render_with_consultations(shop, leads):
    rendered = _ORIGINAL_RENDER(shop, leads)
    old = "<a class='btn' href='/concierge'>Open Concierge</a>"
    new = "<a class='back' href='/consultations'>Digital Consultations</a><a class='btn' href='/concierge'>Open Concierge</a>"
    return rendered.replace(old, new)


def _backfill_existing_threads():
    """Create silent consultation records for existing opted-in Concierge leads.

    This does not text older leads; it only makes them available in the new inbox.
    Startup must never fail if the database is temporarily unavailable.
    """
    conn = None
    rows = []
    try:
        conn = core.connect()
        concierge_leads._ensure_table(conn)
        rows = core.db_fetchall(conn, """
            SELECT l.shop_id,l.customer_id,l.id AS lead_id
            FROM concierge_leads l
            JOIN customers c ON c.id=l.customer_id AND c.shop_id=l.shop_id
            WHERE c.communication_consent=1
            ORDER BY l.created_at DESC
            LIMIT 1000
        """)
    except Exception:
        if conn is not None:
            try:
                conn.rollback()
            except Exception:
                pass
        return
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass

    for row in rows:
        try:
            concierge_sms.ensure_conversation(
                row["shop_id"],
                row["customer_id"],
                row["lead_id"],
            )
        except Exception as exc:
            try:
                core.event(
                    "consultation.backfill_failed",
                    "customer",
                    row["customer_id"],
                    str(exc),
                )
            except Exception:
                pass


def install():
    global _PATCHED
    if _PATCHED:
        return
    concierge_leads.save_concierge_profile = _save_with_consultation
    concierge_leads._render_leads = _render_with_consultations
    _PATCHED = True
    _backfill_existing_threads()


install()
