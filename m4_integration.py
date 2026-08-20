"""Connect the learned M4 runtime to the production recovery queue.

The legacy queue calls core.recovery_score(customer, opening, artist). Replacing
that scoring hook means all existing safety, sequential delivery, claim, booking,
and calendar behavior stays intact while M4 decides customer order.
"""
import app as core
import m4_runtime

LEGACY_RECOVERY_SCORE = core.recovery_score


def m4_recovery_score(customer, opening, artist):
    customer_dict = dict(customer)
    opening_dict = dict(opening)
    result = m4_runtime.score(customer_dict, opening_dict)

    preferred = {
        item.strip().lower()
        for item in str(customer_dict.get("preferred_artists") or "").split(",")
        if item.strip()
    }
    artist_id = str(opening_dict.get("artist_id") or "").lower()
    artist_name = str(artist.get("name") or "").lower()
    artist_fit = 1.0 if artist_id in preferred or artist_name in preferred else (0.62 if not preferred else 0.40)

    # Convert M4's probability/value view into the queue's existing 0-100 score.
    # Uplift receives the most weight because the goal is incremental revenue,
    # not simply contacting people who would likely book anyway.
    score = 100.0 * (
        0.38 * float(result["booking_probability"])
        + 0.34 * min(float(result["incremental_uplift"]) / 0.35, 1.0)
        + 0.16 * float(result["confidence"])
        + 0.12 * artist_fit
    )
    return max(0.0, min(100.0, score))


core.recovery_score = m4_recovery_score
