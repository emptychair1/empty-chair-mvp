"""Connect M4 intelligence and the shop-private Demand Graph to recovery ranking.

The production queue calls ``core.recovery_score(customer, opening, artist)``.
Replacing that hook preserves the existing consent, cooldown, sequential delivery,
claim, booking, and calendar safeguards while letting M4 use Tattoo DNA and Artist
DNA when that evidence exists.
"""
import json

import app as core
import m4_runtime

LEGACY_RECOVERY_SCORE = core.recovery_score


def _json(value):
    if not value:
        return {}
    if isinstance(value, dict):
        return value
    try:
        return json.loads(value)
    except Exception:
        return {}


def _tokens(value):
    if not value:
        return set()
    if isinstance(value, (list, tuple, set)):
        items = value
    else:
        items = str(value).replace(";", ",").split(",")
    return {str(item).strip().lower() for item in items if str(item).strip()}


def _overlap(left, right):
    """Symmetric overlap on [0,1]. Unknown evidence is handled by the caller."""
    a = _tokens(left)
    b = _tokens(right)
    if not a or not b:
        return None
    intersection = len(a & b)
    # Sørensen-Dice rewards focused shared taste without requiring identical vocabularies.
    return (2.0 * intersection) / (len(a) + len(b))


def _demand_graph_evidence(customer_id, shop_id, artist_id):
    if not customer_id or not shop_id or not artist_id:
        return {}, {}, {}, 0.0
    conn = core.connect()
    try:
        try:
            profile = core.db_fetchone(
                conn,
                "SELECT tattoo_dna, practical_fit, affinity, completeness FROM demand_profiles WHERE shop_id=? AND customer_id=? LIMIT 1",
                (shop_id, customer_id),
            )
            artist_dna = core.db_fetchone(
                conn,
                "SELECT dna_json, confidence FROM artist_dna WHERE shop_id=? AND artist_id=? LIMIT 1",
                (shop_id, artist_id),
            )
        except Exception:
            # Demand Graph is additive. A deployment with no graph tables yet must keep
            # the legacy M4 production queue fully operational.
            return {}, {}, {}, 0.0
    finally:
        conn.close()

    tattoo = _json(profile["tattoo_dna"]) if profile else {}
    practical = _json(profile["practical_fit"]) if profile else {}
    artist = _json(artist_dna["dna_json"]) if artist_dna else {}
    graph_confidence = 0.0
    if profile:
        try:
            graph_confidence = max(graph_confidence, float(profile["completeness"] or 0))
        except Exception:
            pass
    if artist_dna:
        try:
            graph_confidence = (graph_confidence + float(artist_dna["confidence"] or 0)) / 2.0
        except Exception:
            pass
    return tattoo, practical, artist, max(0.0, min(1.0, graph_confidence))


def _visual_match(tattoo, artist):
    components = []
    for key, weight in (("styles", 0.60), ("motifs", 0.25), ("palette", 0.15)):
        match = _overlap(tattoo.get(key), artist.get(key))
        if match is not None:
            components.append((match, weight))
    if not components:
        return None
    weight_sum = sum(weight for _, weight in components)
    return sum(value * weight for value, weight in components) / weight_sum


def m4_recovery_breakdown(customer, opening, artist):
    customer_dict = dict(customer)
    opening_dict = dict(opening)
    artist_dict = dict(artist) if artist else {}
    result = m4_runtime.score(customer_dict, opening_dict)

    preferred = {
        item.strip().lower()
        for item in str(customer_dict.get("preferred_artists") or "").split(",")
        if item.strip()
    }
    artist_id = str(opening_dict.get("artist_id") or artist_dict.get("id") or "").lower()
    artist_name = str(artist_dict.get("name") or "").lower()
    artist_fit = 1.0 if artist_id in preferred or artist_name in preferred else (0.62 if not preferred else 0.40)

    base_score = 100.0 * (
        0.38 * float(result["booking_probability"])
        + 0.34 * min(float(result["incremental_uplift"]) / 0.35, 1.0)
        + 0.16 * float(result["confidence"])
        + 0.12 * artist_fit
    )

    shop_id = str(opening_dict.get("shop_id") or customer_dict.get("shop_id") or artist_dict.get("shop_id") or "")
    customer_id = str(customer_dict.get("id") or "")
    tattoo, practical, artist_dna, graph_confidence = _demand_graph_evidence(
        customer_id,
        shop_id,
        str(opening_dict.get("artist_id") or artist_dict.get("id") or ""),
    )
    visual_match = _visual_match(tattoo, artist_dna)

    # Vision is meaningful evidence, but it never gets to erase behavioral history.
    # At maximum confidence it controls 18% of the queue score; with sparse evidence it
    # receives proportionally less weight. Shops without DNA retain the prior score exactly.
    dna_weight = 0.18 * graph_confidence if visual_match is not None else 0.0
    score = (base_score * (1.0 - dna_weight)) + (100.0 * visual_match * dna_weight) if dna_weight else base_score

    # Practical zero-party signals are used as small bounded modifiers rather than hard
    # eligibility rules. Existing safety and consent remain authoritative downstream.
    short_notice = str(practical.get("short_notice") or "").lower()
    timing = str(practical.get("timing") or "").lower()
    practical_bonus = 0.0
    if any(token in short_notice for token in ("yes", "fast", "tomorrow", "same day", "short")):
        practical_bonus += 2.0
    if any(token in timing for token in ("today", "week", "soon", "month")):
        practical_bonus += 1.5
    score += practical_bonus

    why = list(result.get("why") or [])
    if visual_match is not None:
        why.append(f"Tattoo DNA × Artist DNA visual fit {round(visual_match * 100)}%")
    if practical_bonus:
        why.append("Customer-declared timing/short-notice fit")

    return {
        "score": max(0.0, min(100.0, score)),
        "base_score": max(0.0, min(100.0, base_score)),
        "booking_probability": float(result.get("booking_probability", 0)),
        "incremental_uplift": float(result.get("incremental_uplift", 0)),
        "confidence": float(result.get("confidence", 0)),
        "expected_value": result.get("expected_value"),
        "style_fit": float(result.get("style_fit", 0)),
        "budget_fit": float(result.get("budget_fit", 0)),
        "artist_affinity": artist_fit,
        "tattoo_dna_match": visual_match,
        "demand_graph_confidence": graph_confidence,
        "dna_weight": dna_weight,
        "practical_bonus": practical_bonus,
        "tattoo_dna": tattoo,
        "artist_dna": artist_dna,
        "practical_fit": practical,
        "why": why,
    }


def m4_recovery_score(customer, opening, artist):
    return m4_recovery_breakdown(customer, opening, artist)["score"]


# Production recovery campaigns use this hook, so DNA affects the real guarded queue—not
# only the operator preview/demo.
core.recovery_score = m4_recovery_score
