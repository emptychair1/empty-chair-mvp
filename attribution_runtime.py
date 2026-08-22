"""Attribution hooks for Empty Chair's existing recovery engine."""
import app as core
import demand_core

_ORIGINAL_SEND_NEXT = core.send_next_recovery_offer


def _record_sent_offer(offer_id):
    if not offer_id:
        return
    conn = core.connect()
    try:
        demand_core.ensure_schema(conn)
        offer = core.db_fetchone(
            conn,
            """SELECT ofr.id,ofr.customer_id,ofr.opening_id,ofr.channel,ofr.rank,ofr.score,ofr.status,op.shop_id,op.price
               FROM offers ofr JOIN openings op ON op.id=ofr.opening_id WHERE ofr.id=?""",
            (offer_id,),
        )
        if not offer or offer["status"] != "SENT":
            return
        needle = f'%"offer_id": "{offer_id}"%'
        existing = core.db_fetchone(
            conn,
            "SELECT id FROM attribution_events WHERE shop_id=? AND action_type='offer_sent' AND metadata_json LIKE ? LIMIT 1",
            (offer["shop_id"], needle),
        )
        if existing:
            return
        demand_core.record_attribution(
            offer["shop_id"], offer["customer_id"], offer["opening_id"], "offer_sent",
            channel=offer["channel"] or "sms", attribution_class="candidate", value=float(offer["price"] or 0),
            metadata={"offer_id": offer_id, "rank": offer["rank"], "score": offer["score"], "source": "recovery_engine"}, conn=conn,
        )
        demand_core.record_signal(
            offer["shop_id"], offer["customer_id"], "behavior.offer_sent", "empty_chair_runtime",
            {"offer_id": offer_id, "opening_id": offer["opening_id"], "channel": offer["channel"] or "sms"}, confidence=1.0, conn=conn,
        )
        conn.commit()
    finally:
        conn.close()


def send_next_recovery_offer_with_attribution(opening_id):
    offer_id = _ORIGINAL_SEND_NEXT(opening_id)
    try:
        _record_sent_offer(offer_id)
    except Exception as exc:
        core.event("attribution.offer_sent_failed", "opening", opening_id, str(exc))
    return offer_id


core.send_next_recovery_offer = send_next_recovery_offer_with_attribution
