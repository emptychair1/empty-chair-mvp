"""Fast M4 V1 synthetic trainer.

Streams a large synthetic corpus from the frozen V1 simulator so we can get a
useful pass/fail answer quickly without persisting ~1M training rows. The final
holdout uses disjoint synthetic shops and seeds and is never used for updates.
"""
from __future__ import annotations

import json
import math
import random
import uuid

import app as core
import m4_frozen_simulator_v1 as frozen
import m4_runtime
import m4_signal_ablation_benchmark as ablation
from founder_simulation_safety import load_and_assert_founder_simulation_target

VERSION = "m4-v1-fast-train-1"
TRAIN_ROWS = 750_000
VALIDATION_ROWS = 125_000
HOLDOUT_ROWS = 125_000
CANDIDATES_PER_OPENING = 20
REGIME_ORDER = ("easy", "normal", "hard")

FEATURE_NAMES = (
    "bias",
    "baseline_logit",
    "distance_log",
    "budget_log",
    "short_notice_log",
    "artist_affinity_log",
    "fatigue_log",
    "price_ratio",
    "completed",
    "cancellations",
    "no_shows",
    "style_fit",
    "declared_artist_fit",
    "normal_regime",
    "hard_regime",
    "baseline_x_budget",
    "baseline_x_distance",
)


def _clamp(value, lo=1e-5, hi=1 - 1e-5):
    return max(lo, min(hi, float(value)))


def _logit(p):
    p = _clamp(p)
    return math.log(p / (1.0 - p))


def _sigmoid(z):
    z = max(-25.0, min(25.0, float(z)))
    return 1.0 / (1.0 + math.exp(-z))


def _dot(weights, features):
    return sum(w * x for w, x in zip(weights, features))


def _synthetic_customer(template, shop_index, customer_index, rng):
    customer = dict(template)
    customer["id"] = f"m4v1_shop_{shop_index}_customer_{customer_index}"
    spend = max(100.0, float(customer.get("average_spend") or 350.0))
    customer["average_spend"] = round(spend * rng.uniform(0.72, 1.38), 2)
    customer["completed_count"] = max(0, int(float(customer.get("completed_count") or 0) + rng.randint(-2, 4)))
    customer["cancellation_count"] = max(0, int(float(customer.get("cancellation_count") or 0) + (1 if rng.random() < 0.12 else 0)))
    customer["no_show_count"] = max(0, int(float(customer.get("no_show_count") or 0) + (1 if rng.random() < 0.05 else 0)))
    return customer


def _synthetic_opening(template, shop_index, opening_index, rng):
    opening = dict(template)
    opening["id"] = f"m4v1_shop_{shop_index}_opening_{opening_index}"
    opening["artist_id"] = f"m4v1_shop_{shop_index}_artist_{opening_index % 7}"
    base_price = max(80.0, float(opening.get("price") or 350.0))
    opening["price"] = round(base_price * rng.uniform(0.72, 1.42), 2)
    return opening


def _feature_vector(shop_id, customer, opening, cycle, regime):
    scored = m4_runtime.score(customer, opening)
    baseline_p = _clamp(scored.get("booking_probability") or 0.01)
    baseline_logit = _logit(baseline_p) / 4.0

    distance = ablation._observed_multiplier(shop_id, customer, opening, cycle, "distance")
    budget = ablation._observed_multiplier(shop_id, customer, opening, cycle, "budget")
    short_notice = ablation._observed_multiplier(shop_id, customer, opening, cycle, "short_notice")
    artist_affinity = ablation._observed_multiplier(shop_id, customer, opening, cycle, "artist_affinity")
    fatigue = ablation._observed_multiplier(shop_id, customer, opening, cycle, "fatigue")

    preferred_styles = {x.strip().lower() for x in str(customer.get("preferred_styles") or "").split(",") if x.strip()}
    style = str(opening.get("style") or "").strip().lower()
    preferred_artists = {x.strip() for x in str(customer.get("preferred_artists") or "").split(",") if x.strip()}
    artist_id = str(opening.get("artist_id") or "")
    spend = max(100.0, float(customer.get("average_spend") or 350.0))
    price_ratio = max(0.25, min(3.0, float(opening.get("price") or 350.0) / spend)) / 3.0
    completed = min(10.0, float(customer.get("completed_count") or 0.0)) / 10.0
    cancellations = min(5.0, float(customer.get("cancellation_count") or 0.0)) / 5.0
    no_shows = min(5.0, float(customer.get("no_show_count") or 0.0)) / 5.0

    dlog = math.log(max(0.05, distance))
    blog = math.log(max(0.05, budget))
    slog = math.log(max(0.05, short_notice))
    alog = math.log(max(0.05, artist_affinity))
    flog = math.log(max(0.05, fatigue))

    return (
        1.0,
        baseline_logit,
        dlog,
        blog,
        slog,
        alog,
        flog,
        price_ratio,
        completed,
        cancellations,
        no_shows,
        1.0 if style and style in preferred_styles else 0.0,
        1.0 if artist_id and artist_id in preferred_artists else 0.0,
        1.0 if regime == "normal" else 0.0,
        1.0 if regime == "hard" else 0.0,
        baseline_logit * blog,
        baseline_logit * dlog,
    )


def _templates(shop_id):
    conn = core.connect()
    try:
        load_and_assert_founder_simulation_target(conn, core.db_fetchone, shop_id)
        customers, openings = frozen._load(conn, shop_id)
        conn.rollback()
    finally:
        conn.close()
    if not customers or not openings:
        raise RuntimeError("Crybaby founder simulation must be seeded before M4 V1 training.")
    return customers, openings


def _row_stream(customers, openings, start_shop, rows, seed):
    rng = random.Random(seed)
    produced = 0
    opening_index = 0
    while produced < rows:
        shop_index = start_shop + opening_index // 250
        shop_id = f"m4v1_synth_shop_{shop_index}"
        regime = REGIME_ORDER[(opening_index + shop_index) % len(REGIME_ORDER)]
        opening_template = openings[opening_index % len(openings)]
        opening = _synthetic_opening(opening_template, shop_index, opening_index, rng)
        cycle = 1 + (opening_index % 600)
        for position in range(CANDIDATES_PER_OPENING):
            if produced >= rows:
                break
            template = customers[(opening_index * 7 + position * 11) % len(customers)]
            customer = _synthetic_customer(template, shop_index, opening_index * CANDIDATES_PER_OPENING + position, rng)
            features = _feature_vector(shop_id, customer, opening, cycle, regime)
            truth, env = frozen.hidden_probability(shop_id, customer, opening, cycle, regime)
            accepted = 1.0 if frozen._stable(shop_id, opening["id"], customer["id"], cycle, regime, "m4v1_train_accept") < truth else 0.0
            yield {
                "shop_id": shop_id,
                "opening_id": opening["id"],
                "price": float(opening.get("price") or 0.0),
                "regime": regime,
                "features": features,
                "baseline_probability": _clamp(m4_runtime.score(customer, opening).get("booking_probability") or 0.01),
                "accepted": accepted,
                "structurally_unfillable": bool(env.get("structurally_unfillable")),
            }
            produced += 1
        opening_index += 1


def _train(customers, openings):
    weights = [0.0] * len(FEATURE_NAMES)
    learning_rate = 0.035
    l2 = 0.00002
    seen = 0
    loss = 0.0
    for row in _row_stream(customers, openings, 0, TRAIN_ROWS, 41001):
        x = row["features"]
        y = row["accepted"]
        p = _clamp(_sigmoid(_dot(weights, x)))
        error = y - p
        eta = learning_rate / math.sqrt(1.0 + seen / 75_000.0)
        for i in range(len(weights)):
            weights[i] += eta * (error * x[i] - l2 * weights[i])
        loss += -(y * math.log(p) + (1.0 - y) * math.log(1.0 - p))
        seen += 1
    return weights, {"rows": seen, "log_loss": loss / max(1, seen)}


def _validation_loss(customers, openings, weights):
    loss = 0.0
    brier = 0.0
    seen = 0
    for row in _row_stream(customers, openings, 10_000, VALIDATION_ROWS, 51001):
        p = _clamp(_sigmoid(_dot(weights, row["features"])))
        y = row["accepted"]
        loss += -(y * math.log(p) + (1.0 - y) * math.log(1.0 - p))
        brier += (p - y) ** 2
        seen += 1
    return {"rows": seen, "log_loss": loss / max(1, seen), "brier": brier / max(1, seen)}


def _finalize_metrics(totals):
    openings = max(1, totals["openings"])
    bookings = max(1, totals["bookings"])
    contacts = max(1, totals["contacts"])
    totals["top1_rate"] = totals["top1_bookings"] / openings
    totals["top3_rate"] = totals["top3_bookings"] / openings
    totals["fill_rate"] = totals["bookings"] / openings
    totals["contacts_per_booking"] = totals["contacts"] / bookings
    totals["revenue_per_contact"] = totals["recovered_revenue"] / contacts
    return totals


def _holdout(customers, openings, weights):
    groups = {}
    for row in _row_stream(customers, openings, 20_000, HOLDOUT_ROWS, 61001):
        key = (row["shop_id"], row["opening_id"])
        row["trained_probability"] = _clamp(_sigmoid(_dot(weights, row["features"])))
        groups.setdefault(key, []).append(row)

    result = {}
    for policy in ("baseline", "trained"):
        totals = {"openings": 0, "top1_bookings": 0, "top3_bookings": 0, "bookings": 0, "contacts": 0, "recovered_revenue": 0.0}
        by_regime = {name: {"openings": 0, "top1_bookings": 0, "top3_bookings": 0, "bookings": 0, "contacts": 0, "recovered_revenue": 0.0} for name in REGIME_ORDER}
        for rows in groups.values():
            ordered = sorted(rows, key=lambda r: r["baseline_probability"] if policy == "baseline" else r["trained_probability"], reverse=True)
            regime = ordered[0]["regime"]
            booked_index = next((i for i, r in enumerate(ordered) if r["accepted"]), None)
            for bucket in (totals, by_regime[regime]):
                bucket["openings"] += 1
                if ordered and ordered[0]["accepted"]:
                    bucket["top1_bookings"] += 1
                if any(r["accepted"] for r in ordered[:3]):
                    bucket["top3_bookings"] += 1
                if booked_index is None:
                    bucket["contacts"] += len(ordered)
                else:
                    bucket["bookings"] += 1
                    bucket["contacts"] += booked_index + 1
                    bucket["recovered_revenue"] += ordered[booked_index]["price"]
        result[policy] = _finalize_metrics(totals)
        result[policy]["regimes"] = {name: _finalize_metrics(metrics) for name, metrics in by_regime.items()}
    return result


def _material_pass(baseline, trained):
    normal = trained["regimes"]["normal"]
    hard = trained["regimes"]["hard"]
    easy = trained["regimes"]["easy"]
    baseline_normal = baseline["regimes"]["normal"]
    baseline_hard = baseline["regimes"]["hard"]
    baseline_easy = baseline["regimes"]["easy"]
    return {
        "easy_top1_at_least_69pct": easy["top1_rate"] >= 0.69,
        "normal_top1_at_least_58pct": normal["top1_rate"] >= 0.58,
        "hard_top1_at_least_45pct": hard["top1_rate"] >= 0.45,
        "easy_beats_holdout_baseline": easy["top1_rate"] > baseline_easy["top1_rate"],
        "normal_beats_holdout_baseline": normal["top1_rate"] > baseline_normal["top1_rate"],
        "hard_beats_holdout_baseline": hard["top1_rate"] > baseline_hard["top1_rate"],
        "fill_not_degraded": trained["fill_rate"] >= baseline["fill_rate"] - 0.002,
        "contact_efficiency_improves": trained["contacts_per_booking"] < baseline["contacts_per_booking"],
        "revenue_per_contact_improves": trained["revenue_per_contact"] > baseline["revenue_per_contact"],
    }


def ensure_table(conn):
    core.db_execute(conn, """
        CREATE TABLE IF NOT EXISTS m4_v1_training_runs (
            id TEXT PRIMARY KEY,
            shop_id TEXT NOT NULL,
            version TEXT NOT NULL,
            result_json TEXT NOT NULL,
            passed INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL
        )
    """)


def run_training(shop_id):
    customers, openings = _templates(shop_id)
    weights, training = _train(customers, openings)
    validation = _validation_loss(customers, openings, weights)
    holdout = _holdout(customers, openings, weights)
    baseline = holdout["baseline"]
    trained = holdout["trained"]
    gates = _material_pass(baseline, trained)
    passed = all(gates.values())

    result = {
        "version": VERSION,
        "dataset": {
            "train_rows": TRAIN_ROWS,
            "validation_rows": VALIDATION_ROWS,
            "holdout_rows": HOLDOUT_ROWS,
            "holdout_sealed": True,
            "candidates_per_opening": CANDIDATES_PER_OPENING,
            "simulator": frozen.VERSION,
        },
        "features": list(FEATURE_NAMES),
        "training": training,
        "validation": validation,
        "model": {"type": "online_logistic_regression", "weights": {name: weight for name, weight in zip(FEATURE_NAMES, weights)}},
        "holdout": holdout,
        "acceptance_gates": gates,
        "status": "PASS" if passed else "FAIL",
    }

    conn = core.connect()
    try:
        load_and_assert_founder_simulation_target(conn, core.db_fetchone, shop_id)
        ensure_table(conn)
        conn.commit()
        run_id = "m4_v1_train_" + uuid.uuid4().hex
        core.db_execute(conn, "INSERT INTO m4_v1_training_runs(id,shop_id,version,result_json,passed,created_at) VALUES (?,?,?,?,?,?)", (run_id, shop_id, VERSION, json.dumps(result), 1 if passed else 0, core.now_iso()))
        conn.commit()
        result["run_id"] = run_id
        return result
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
