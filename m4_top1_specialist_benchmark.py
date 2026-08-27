"""Conditional top-1 specialist for the M4 V3 stress benchmark.

The specialist is deliberately conservative. Legacy M4 still creates the slate.
Historical founder-simulation outcomes are split into train/tune periods:
- train builds smoothed customer x artist/style acceptance evidence;
- tune selects the baseline-margin gate and context weight;
- V3 future cycles are the untouched holdout benchmark.

This avoids tuning directly against the V3 answers while targeting the precise
weakness exposed by the hybrid policy: top-1 ordering.
"""

from __future__ import annotations

import json
import math
import uuid

import app as core
import m4_runtime
import m4_stress_benchmark_v3 as v3
from founder_simulation_safety import load_and_assert_founder_simulation_target


def ensure_table(conn):
    core.db_execute(
        conn,
        """
        CREATE TABLE IF NOT EXISTS founder_sim_v3_top1_benchmarks (
            id TEXT PRIMARY KEY,
            shop_id TEXT NOT NULL,
            cycles INTEGER NOT NULL,
            baseline_json TEXT NOT NULL,
            decision_json TEXT NOT NULL,
            hybrid_json TEXT NOT NULL,
            specialist_json TEXT NOT NULL,
            training_json TEXT NOT NULL,
            environment_json TEXT NOT NULL,
            winner TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """,
    )


def _logit(p):
    p = max(0.01, min(0.99, float(p)))
    return math.log(p / (1.0 - p))


def _sigmoid(x):
    return 1.0 / (1.0 + math.exp(-max(-20.0, min(20.0, float(x)))))


def _history(conn, shop_id):
    return [
        dict(row)
        for row in core.db_fetchall(
            conn,
            """
            SELECT fo.cycle,fo.opening_id,fo.customer_id,fo.rank,
                   fo.baseline_probability,fo.accepted,
                   o.artist_id,o.style
            FROM founder_sim_outcomes fo
            JOIN openings o ON o.id=fo.opening_id
            WHERE fo.shop_id=?
            ORDER BY fo.cycle,fo.opening_id,fo.rank
            """,
            (shop_id,),
        )
    ]


def _add(bucket, key, accepted):
    wins, attempts = bucket.get(key, (0, 0))
    bucket[key] = (wins + int(bool(accepted)), attempts + 1)


def _rate(bucket, key, prior_rate, strength=8.0):
    wins, attempts = bucket.get(key, (0, 0))
    return (wins + prior_rate * strength) / (attempts + strength)


def _build_context(rows):
    customer = {}
    artist = {}
    style = {}
    total_wins = 0
    total_attempts = 0
    for row in rows:
        accepted = int(row.get("accepted") or 0)
        customer_id = row["customer_id"]
        artist_id = str(row.get("artist_id") or "")
        style_name = str(row.get("style") or "").strip().lower()
        _add(customer, customer_id, accepted)
        _add(artist, (customer_id, artist_id), accepted)
        _add(style, (customer_id, style_name), accepted)
        total_wins += accepted
        total_attempts += 1
    global_rate = (total_wins + 5.0) / (total_attempts + 10.0)
    return {
        "customer": customer,
        "artist": artist,
        "style": style,
        "global_rate": global_rate,
        "rows": total_attempts,
    }


def _context_probability(context, customer_id, opening):
    global_rate = context["global_rate"]
    customer_rate = _rate(context["customer"], customer_id, global_rate, 12.0)
    artist_rate = _rate(
        context["artist"],
        (customer_id, str(opening.get("artist_id") or "")),
        customer_rate,
        7.0,
    )
    style_rate = _rate(
        context["style"],
        (customer_id, str(opening.get("style") or "").strip().lower()),
        customer_rate,
        7.0,
    )
    # Artist evidence is slightly more specific to tattoo-shop behavior.
    return 0.58 * artist_rate + 0.42 * style_rate


def _groups(rows):
    grouped = {}
    for row in rows:
        grouped.setdefault((int(row["cycle"]), row["opening_id"]), []).append(row)
    for candidates in grouped.values():
        candidates.sort(key=lambda row: int(row.get("rank") or 999))
    return list(grouped.values())


def _tune(context, tune_rows, openings_by_id):
    thresholds = (0.015, 0.03, 0.05, 0.075, 0.10, 0.14)
    weights = (0.10, 0.18, 0.26, 0.34, 0.42)
    best = None
    groups = _groups(tune_rows)

    for threshold in thresholds:
        for weight in weights:
            correct = 0
            overrides = 0
            evaluated = 0
            for candidates in groups:
                top = candidates[:5]
                if len(top) < 2:
                    continue
                opening = openings_by_id.get(top[0]["opening_id"])
                if not opening:
                    continue
                first_p = float(top[0].get("baseline_probability") or 0.0)
                second_p = float(top[1].get("baseline_probability") or 0.0)
                margin = first_p - second_p
                chosen = top[0]
                if margin < threshold:
                    def score(row):
                        baseline_p = float(row.get("baseline_probability") or 0.0)
                        context_p = _context_probability(context, row["customer_id"], opening)
                        return (1.0 - weight) * baseline_p + weight * context_p
                    contender = max(top, key=score)
                    if contender["customer_id"] != top[0]["customer_id"]:
                        overrides += 1
                    chosen = contender
                correct += int(chosen.get("accepted") or 0)
                evaluated += 1

            accuracy = correct / max(1, evaluated)
            override_rate = overrides / max(1, evaluated)
            candidate = {
                "threshold": threshold,
                "context_weight": weight,
                "tune_top1_rate": accuracy,
                "override_rate": override_rate,
                "evaluated_openings": evaluated,
            }
            if best is None:
                best = candidate
                continue
            if accuracy > best["tune_top1_rate"] + 1e-12:
                best = candidate
            elif abs(accuracy - best["tune_top1_rate"]) <= 1e-12 and override_rate < best["override_rate"]:
                best = candidate
    return best or {
        "threshold": 0.05,
        "context_weight": 0.25,
        "tune_top1_rate": 0.0,
        "override_rate": 0.0,
        "evaluated_openings": 0,
    }


def _train_specialist(conn, shop_id, openings):
    rows = _history(conn, shop_id)
    cycles = sorted({int(row["cycle"]) for row in rows})
    if len(cycles) < 10:
        raise RuntimeError("Not enough founder simulation history to train top-1 specialist.")
    split_index = max(1, int(len(cycles) * 0.70))
    train_cycles = set(cycles[:split_index])
    tune_cycles = set(cycles[split_index:])
    train_rows = [row for row in rows if int(row["cycle"]) in train_cycles]
    tune_rows = [row for row in rows if int(row["cycle"]) in tune_cycles]
    context = _build_context(train_rows)
    openings_by_id = {opening["id"]: opening for opening in openings}
    tuned = _tune(context, tune_rows, openings_by_id)
    summary = {
        "history_cycles": len(cycles),
        "train_cycles": len(train_cycles),
        "tune_cycles": len(tune_cycles),
        "train_rows": len(train_rows),
        "tune_rows": len(tune_rows),
        **tuned,
    }
    return context, summary


def _specialist_order(customers, opening, context, tuned):
    ranked = m4_runtime.rank(customers, opening, len(customers))
    by_id = {customer["id"]: customer for customer in customers}
    baseline = [by_id[row["customer_id"]] for row in ranked]
    if len(ranked) < 2:
        return baseline

    first_p = float(ranked[0].get("booking_probability") or 0.0)
    second_p = float(ranked[1].get("booking_probability") or 0.0)
    margin = first_p - second_p
    top_five_rows = ranked[:5]
    top_five = baseline[:5]
    tail = baseline[5:]
    weight = float(tuned["context_weight"])

    def score_pair(item):
        row, customer = item
        baseline_p = float(row.get("booking_probability") or 0.0)
        context_p = _context_probability(context, customer["id"], opening)
        return (1.0 - weight) * baseline_p + weight * context_p

    if margin >= float(tuned["threshold"]):
        # Protect a strong baseline #1, but still optimize positions 2-5.
        protected = top_five[0]
        remaining_pairs = list(zip(top_five_rows[1:], top_five[1:]))
        reranked_tail = [customer for _, customer in sorted(remaining_pairs, key=score_pair, reverse=True)]
        return [protected] + reranked_tail + tail

    pairs = list(zip(top_five_rows, top_five))
    reranked = [customer for _, customer in sorted(pairs, key=score_pair, reverse=True)]
    return reranked + tail


def _evaluate_specialist(shop_id, cycles, customers, openings, context, tuned, seed_offset):
    totals = {
        "cycles": cycles,
        "openings": 0,
        "top1_bookings": 0,
        "top3_bookings": 0,
        "bookings": 0,
        "unfilled_openings": 0,
        "contacts": 0,
        "recovered_revenue": 0.0,
        "weak_demand_openings": 0,
        "very_weak_demand_openings": 0,
        "cold_start_contacts": 0,
        "budget_blocked_contacts": 0,
        "distance_blocked_contacts": 0,
    }
    for index in range(1, cycles + 1):
        cycle = seed_offset + index
        for opening in openings:
            totals["openings"] += 1
            ordered = _specialist_order(customers, opening, context, tuned)
            accepted_flags = []
            environments = []
            for customer in ordered:
                truth, env = v3.hidden_probability_v3(shop_id, customer, opening, cycle)
                accepted = v3._stable(shop_id, opening["id"], customer["id"], cycle, "v3_accept") < truth
                accepted_flags.append(bool(accepted))
                environments.append(env)
            if environments:
                if environments[0]["demand_regime"] == "weak":
                    totals["weak_demand_openings"] += 1
                elif environments[0]["demand_regime"] == "very_weak":
                    totals["very_weak_demand_openings"] += 1
            if accepted_flags and accepted_flags[0]:
                totals["top1_bookings"] += 1
            if any(accepted_flags[:3]):
                totals["top3_bookings"] += 1
            booked_index = next((i for i, accepted in enumerate(accepted_flags) if accepted), None)
            if booked_index is None:
                totals["unfilled_openings"] += 1
                totals["contacts"] += len(ordered)
                contact_range = range(len(ordered))
            else:
                totals["bookings"] += 1
                totals["contacts"] += booked_index + 1
                totals["recovered_revenue"] += float(opening.get("price") or 0.0)
                contact_range = range(booked_index + 1)
            for position in contact_range:
                env = environments[position]
                if env["cold_start"]:
                    totals["cold_start_contacts"] += 1
                if env["budget_multiplier"] <= 0.38:
                    totals["budget_blocked_contacts"] += 1
                if env["distance_multiplier"] <= 0.45:
                    totals["distance_blocked_contacts"] += 1

    n_openings = max(1, totals["openings"])
    n_bookings = max(1, totals["bookings"])
    n_contacts = max(1, totals["contacts"])
    totals["top1_rate"] = totals["top1_bookings"] / n_openings
    totals["top3_rate"] = totals["top3_bookings"] / n_openings
    totals["booking_rate"] = totals["bookings"] / n_openings
    totals["unfilled_rate"] = totals["unfilled_openings"] / n_openings
    totals["contacts_per_booking"] = totals["contacts"] / n_bookings
    totals["revenue_per_contact"] = totals["recovered_revenue"] / n_contacts
    return totals


def _winner(policies):
    # Top-1 specialist benchmark: require business efficiency not to collapse,
    # then prioritize top-1 accuracy. This prevents gaming top-1 with spam.
    baseline = policies["baseline"]
    eligible = {}
    for name, metrics in policies.items():
        revenue_floor = baseline["revenue_per_contact"] * 0.985
        contacts_ceiling = baseline["contacts_per_booking"] * 1.03
        if metrics["revenue_per_contact"] >= revenue_floor and metrics["contacts_per_booking"] <= contacts_ceiling:
            eligible[name] = metrics
    if not eligible:
        return "baseline"
    return max(
        eligible,
        key=lambda name: (
            eligible[name]["top1_rate"],
            eligible[name]["top3_rate"],
            eligible[name]["revenue_per_contact"],
        ),
    )


def run_benchmark(shop_id, cycles=250):
    cycles = max(50, min(int(cycles), 500))
    conn = core.connect()
    try:
        load_and_assert_founder_simulation_target(conn, core.db_fetchone, shop_id)
        v3.ensure_tables(conn)
        ensure_table(conn)
        conn.commit()
        customers, openings, learning, pairwise = v3._load_state(conn, shop_id)
        if not customers or not openings:
            raise RuntimeError("Crybaby founder simulation must be seeded before benchmarking.")
        context, training = _train_specialist(conn, shop_id, openings)
        row = core.db_fetchone(conn, "SELECT MAX(cycle) AS max_cycle FROM founder_sim_metrics WHERE shop_id=?", (shop_id,))
        conn.rollback()
    finally:
        conn.close()

    seed_offset = int(row["max_cycle"] or 0) + 30000 if row else 30000
    baseline = v3._evaluate(shop_id, cycles, "baseline", customers, openings, learning, pairwise, seed_offset)
    full_decision = v3._evaluate(shop_id, cycles, "decision", customers, openings, learning, pairwise, seed_offset)
    hybrid = v3._evaluate(shop_id, cycles, "hybrid", customers, openings, learning, pairwise, seed_offset)
    specialist = _evaluate_specialist(shop_id, cycles, customers, openings, context, training, seed_offset)

    policies = {
        "baseline": baseline,
        "decision": full_decision,
        "hybrid": hybrid,
        "top1_specialist": specialist,
    }
    winner = _winner(policies)
    lift = {
        "decision_vs_baseline": v3._lift(full_decision, baseline),
        "hybrid_vs_baseline": v3._lift(hybrid, baseline),
        "top1_specialist_vs_baseline": v3._lift(specialist, baseline),
    }
    environment = {
        "version": "v3-adversarial-top1-specialist",
        "weak_demand_share_target": 0.28,
        "very_weak_demand_share_target": 0.14,
        "cold_start_share_target": 0.22,
        "specialist": "conditional baseline-margin gate + contextual customer x artist/style evidence",
        "features": [
            "weak_demand",
            "ambiguous_candidates",
            "hidden_budget",
            "distance_friction",
            "short_notice_readiness",
            "offer_fatigue",
            "cold_start",
            "hidden_artist_affinity",
            "behavioral_drift",
            "adversarial_noise",
        ],
    }
    result = {
        "environment": environment,
        "cycles_per_policy": cycles,
        "specialist_training": training,
        "baseline": baseline,
        "decision": full_decision,
        "hybrid": hybrid,
        "top1_specialist": specialist,
        "lift": lift,
        "winner": winner,
    }

    conn = core.connect()
    try:
        ensure_table(conn)
        conn.commit()
        benchmark_id = "founder_sim_v3_top1_" + uuid.uuid4().hex
        core.db_execute(
            conn,
            """INSERT INTO founder_sim_v3_top1_benchmarks(
                id,shop_id,cycles,baseline_json,decision_json,hybrid_json,
                specialist_json,training_json,environment_json,winner,created_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (
                benchmark_id,
                shop_id,
                cycles,
                json.dumps(baseline),
                json.dumps(full_decision),
                json.dumps(hybrid),
                json.dumps(specialist),
                json.dumps(training),
                json.dumps(environment),
                winner,
                core.now_iso(),
            ),
        )
        conn.commit()
        result["benchmark_id"] = benchmark_id
        return result
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
