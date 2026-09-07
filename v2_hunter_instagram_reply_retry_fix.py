"""Retry previously seen but unmatched Instagram replies.

The original reply sync deduplicated every message_id before attempting another match.
That is correct for already-matched replies, but it permanently stranded a real reply if
Meta delivered it before sender/profile resolution was working. This patch lets the same
official message be reconsidered while its stored event remains unmatched.
"""
from __future__ import annotations

import v2_app as core
import v2_hunter_instagram_reply_sync as sync


_original_record = sync.record_inbound_message


def record_inbound_message_retry_unmatched(
    *,
    message_id: str,
    sender_id: str,
    username: str = "",
    text: str = "",
    created_at=None,
    source: str,
) -> bool:
    message_id = str(message_id or "").strip()
    if not message_id:
        return False

    db = core.DB()
    try:
        sync._ensure(db)
        row = db.execute(
            "SELECT matched FROM hunter_instagram_reply_events WHERE message_id=?",
            (message_id,),
        ).fetchone()
        if row and int(dict(row).get("matched") or 0) == 0:
            db.execute(
                "DELETE FROM hunter_instagram_reply_events WHERE message_id=? AND matched=0",
                (message_id,),
            )
            db.commit()
    finally:
        db.close()

    return _original_record(
        message_id=message_id,
        sender_id=sender_id,
        username=username,
        text=text,
        created_at=created_at,
        source=source,
    )


sync.record_inbound_message = record_inbound_message_retry_unmatched

print("Hunter Instagram reply retry fix loaded // unmatched events can reconcile", flush=True)
