from datetime import datetime, timezone

from social_pain_sweep import _caption_evidence


def test_caption_evidence_requires_fresh_pain():
    now = datetime(2026, 9, 7, 2, 0, tzinfo=timezone.utc)
    hit = _caption_evidence("Cancellation today - I have an opening tomorrow", "2026-09-07T01:00:00+00:00", now)
    assert hit is not None
    assert hit["pain_fit"] >= 75


def test_caption_evidence_rejects_stale_and_generic():
    now = datetime(2026, 9, 7, 2, 0, tzinfo=timezone.utc)
    assert _caption_evidence("Cancellation today", "2026-09-01T01:00:00+00:00", now) is None
    assert _caption_evidence("New tattoo I finished today", "2026-09-07T01:00:00+00:00", now) is None
