"""Connect M4 intelligence and the shop-private Demand Graph to recovery ranking.

The production queue calls ``core.recovery_score(customer, opening, artist)``.
Replacing that hook preserves the existing consent, cooldown, sequential delivery,
claim, booking, and calendar safeguards while letting M4 use Tattoo DNA, practical
fit, enrichment context, and Artist DNA when that evidence exists.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone

import app as core
import enrichment_v1
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
        items = re.split(r"[,;/|]", str(value))
    return {str(item).strip().lower() for item in items if str(item).strip()}


def _overlap(left, right):
    """Symmetric overlap on [0,1]. Unknown evidence is handled by the caller."""
    a = _tokens(left)
    b = _tokens(right)
    if not a or not b:
        return None
    intersection = len(a & b)
    return (2.0 * intersection) / (len(a) + len(b))


def _artist_practical_evidence(conn, shop_id, artist_id):
    placements, scales = [], []
    try:
        assets = core.db_fetchall(
            conn,
            "SELECT analysis_json FROM artist_portfolio_assets WHERE shop_id=? AND artist_id=? ORDER BY created_at DESC LIMIT 40",
            (shop_id, artist_id),
        )
    except Exception:
        assets = []
    for row in assets:
        analysis = _json(row["analysis_json"])
        placement = analysis.get("likely_placement") or []
        if isinstance(placement, str):
            placement = [placement]
        placements.extend(placement)
        scale = analysis.get("likely_scale")
        if scale:
            scales.append(scale)
    return {"placements": list(_tokens(placements)), "scales": list(_tokens(scales))}


def _demand_graph_evidence(customer_id, shop_id, artist_id):
    if not customer_id or not shop_id or not artist_id:
        return {}, {}, {}, {}, {}, 0.0
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
            artist_practical = _artist_practical_evidence(conn, shop_id, artist_id)
        except Exception:
            return {}, {}, {}, {}, {}, 0.0
    finally:
        conn.close()

    tattoo = _json(profile["tattoo_dna"]) if profile else {}
    practical = _json(profile["practical_fit"]) if profile else {}
    affinity = _json(profile["affinity"]) if profile else {}
    artist = _json(artist_dna["dna_json"]) if artist_dna else {}
    try:
        context = enrichment_v1.customer_context(shop_id, customer_id)
    except Exception:
        context = {}
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
    return tattoo, practical, affinity, artist, {"customer": context, "artist": artist_practical}, max(0.0, min(1.0, graph_confidence))


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


def _money_bounds(value):
    text = str(value or "").lower().replace(",", "")
    if not text or "flex" in text or "open" in text:
        return None
    numbers = [float(n) for n in re.findall(r"\d+(?:\.\d+)?", text)]
    if not numbers:
        return None
    if "+" in text:
        return numbers[0], float("inf")
    if len(numbers) == 1:
        return 0.0, numbers[0]
    return min(numbers[0], numbers[1]), max(numbers[0], numbers[1])


def _budget_fit(value, price):
    bounds = _money_bounds(value)
    if not bounds:
        return None
    low, high = bounds
    price = float(price or 0)
    if low <= price <= high:
        return 1.0
    if price < low:
        return max(0.55, 1.0 - ((low - price) / max(low, 1.0)) * 0.5)
    if high == float("inf"):
        return 1.0
    over = (price - high) / max(high, 1.0)
    return max(0.0, 1.0 - over * 1.7)


def _opening_hours(opening):
    date = str(opening.get("date") or "").strip()
    start = str(opening.get("start_time") or "00:00").strip()
    if not date:
        return None
    try:
        dt = datetime.fromisoformat(f"{date}T{start}")
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return max(0.0, (dt - datetime.now(timezone.utc)).total_seconds() / 3600.0)
    except Exception:
        return None


def _timing_fit(value, opening):
    text = str(value or "").lower()
    hours = _opening_hours(opening)
    if not text or hours is None:
        return None
    days = hours / 24.0
    if "today" in text:
        return 1.0 if days <= 1 else max(0.0, 1.0 - (days - 1) / 14.0)
    if "week" in text:
        return 1.0 if days <= 7 else max(0.0, 1.0 - (days - 7) / 30.0)
    if "month" in text and "3" not in text:
        return 1.0 if days <= 31 else 0.45
    if "3 month" in text:
        return 1.0 if days <= 93 else 0.5
    if "explor" in text:
        return 0.45
    return 0.65


def _short_notice_fit(value, opening):
    text = str(value or "").lower()
    hours = _opening_hours(opening)
    if not text or hours is None:
        return None
    if any(token in text for token in ("yes", "move fast", "same day", "tomorrow")):
        return 1.0 if hours <= 72 else 0.8
    if "2" in text or "3" in text or "maybe" in text:
        if hours < 36:
            return 0.35
        return 1.0 if hours <= 96 else 0.8
    if any(token in text for token in ("plan ahead", "no")):
        return 0.15 if hours <= 72 else 0.8
    return 0.6


def _travel_radius(value):
    text = str(value or "").lower()
    if not text:
        return None
    if "worth traveling" in text or "anywhere" in text:
        return float("inf")
    numbers = re.findall(r"\d+(?:\.\d+)?", text)
    return float(numbers[0]) if numbers else None


def _distance_fit(travel_pref, context):
    radius = _travel_radius(travel_pref)
    travel = ((context or {}).get("customer") or {}).get("travel") or {}
    miles = travel.get("drive_miles")
    if radius is None or miles is None:
        return None
    miles = float(miles)
    if radius == float("inf"):
        return 1.0
    if miles <= radius:
        return 1.0
    return max(0.0, 1.0 - ((miles - radius) / max(radius, 1.0)))


def _placement_fit(placement, context):
    desired = _tokens(placement)
    artist_placements = _tokens(((context or {}).get("artist") or {}).get("placements"))
    if not desired or not artist_placements:
        return None
    direct = len(desired & artist_placements)
    if direct:
        return 1.0
    joined_desired = " ".join(desired)
    joined_artist = " ".join(artist_placements)
    body_groups = [
        {"arm", "forearm", "bicep", "upper arm", "sleeve"},
        {"leg", "thigh", "calf", "shin"},
        {"torso", "chest", "ribs", "stomach", "back"},
        {"hand", "finger", "wrist"},
        {"neck", "head", "face"},
    ]
    for group in body_groups:
        if any(x in joined_desired for x in group) and any(x in joined_artist for x in group):
            return 0.8
    return 0.35


def _component_score(components):
    available = [(value, weight) for value, weight in components if value is not None]
    if not available:
        return None
    total = sum(weight for _, weight in available)
    return sum(value * weight for value, weight in available) / total


def m4_recovery_breakdown(customer, opening, artist):
    customer_dict = dict(customer)
    opening_dict = dict(opening)
    artist_dict = dict(artist) if artist else {}
    result = m4_runtime.score(customer_dict, opening_dict)

    preferred = {item.strip().lower() for item in str(customer_dict.get("preferred_artists") or "").split(",") if item.strip()}
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
    tattoo, practical, affinity, artist_dna, context, graph_confidence = _demand_graph_evidence(customer_id, shop_id, str(opening_dict.get("artist_id") or artist_dict.get("id") or ""))
    visual_match = _visual_match(tattoo, artist_dna)

    dna_weight = 0.18 * graph_confidence if visual_match is not None else 0.0
    score = (base_score * (1.0 - dna_weight)) + (100.0 * visual_match * dna_weight) if dna_weight else base_score

    budget_fit = _budget_fit(practical.get("budget"), opening_dict.get("price"))
    placement_fit = _placement_fit(practical.get("placement"), context)
    distance_fit = _distance_fit(practical.get("travel"), context)
    timing_fit = _timing_fit(practical.get("timing"), opening_dict)
    short_notice_fit = _short_notice_fit(practical.get("short_notice"), opening_dict)
    practical_score = _component_score([
        (budget_fit, 0.28),
        (placement_fit, 0.16),
        (distance_fit, 0.22),
        (timing_fit, 0.18),
        (short_notice_fit, 0.16),
    ])
    practical_weight = min(0.22, 0.22 * graph_confidence) if practical_score is not None else 0.0
    if practical_weight:
        score = (score * (1.0 - practical_weight)) + (100.0 * practical_score * practical_weight)

    why = list(result.get("why") or [])
    if visual_match is not None:
        why.append(f"Tattoo DNA × Artist DNA visual fit {round(visual_match * 100)}%")
    labels = [
        ("budget", budget_fit),
        ("placement", placement_fit),
        ("distance", distance_fit),
        ("timing", timing_fit),
        ("short-notice", short_notice_fit),
    ]
    for label, value in labels:
        if value is not None:
            why.append(f"Practical {label} fit {round(value * 100)}%")
    if artist_fit >= 0.99:
        why.append("Declared artist preference matches this opening")

    return {
        "score": max(0.0, min(100.0, score)),
        "base_score": max(0.0, min(100.0, base_score)),
        "booking_probability": float(result.get("booking_probability", 0)),
        "incremental_uplift": float(result.get("incremental_uplift", 0)),
        "confidence": float(result.get("confidence", 0)),
        "expected_value": result.get("expected_value"),
        "style_fit": float(result.get("style_fit", 0)),
        "budget_fit": budget_fit if budget_fit is not None else float(result.get("budget_fit", 0)),
        "placement_fit": placement_fit,
        "distance_fit": distance_fit,
        "timing_fit": timing_fit,
        "short_notice_fit": short_notice_fit,
        "practical_score": practical_score,
        "practical_weight": practical_weight,
        "artist_affinity": artist_fit,
        "tattoo_dna_match": visual_match,
        "demand_graph_confidence": graph_confidence,
        "dna_weight": dna_weight,
        "tattoo_dna": tattoo,
        "artist_dna": artist_dna,
        "practical_fit": practical,
        "affinity": affinity,
        "contextual": context.get("customer") or {},
        "why": why,
    }


def m4_recovery_score(customer, opening, artist):
    return m4_recovery_breakdown(customer, opening, artist)["score"]


core.recovery_score = m4_recovery_score
