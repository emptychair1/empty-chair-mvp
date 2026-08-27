"""Simulation V3: adversarial/realistic M4 policy stress benchmark.

V3 evaluates three policies against the same deterministic hard-world outcomes:
1) legacy baseline ranking,
2) full learned decision ranking,
3) hybrid top-five re-ranker.

The hybrid preserves the baseline slate, then only reorders the baseline's top
five candidates using learned calibration + pairwise decision value. Ranks six
and below remain in baseline order.

No customer is contacted. Only founder_sim_v3_* benchmark rows are written, and
all writes are restricted to the validated Crybaby founder sandbox.
"""

from __future__ import annotations

import json
import math
import uuid

import app as core
import m4_decision_policy as decision
import m4_founder_simulation_engine as legacy
import m4_runtime
from founder_simulation_safety import load_and_assert_founder_simulation_target

SIM_PREFIX = "founder_sim_"


def ensure_tables(conn):
    # Keep the original V3 table for backwards compatibility.
    core.db_execute(
        conn,
        """
        CREATE TABLE IF NOT EXISTS founder_sim_v3_benchmarks (
            id TEXT PRIMARY KEY,
            shop_id TEXT NOT NULL,
            cycles INTEGER NOT NULL,
            baseline_json TEXT NOT NULL,
            decision_json TEXT NOT NULL,
            environment_json TEXT NOT NULL,
            winner TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """,
    )
    # New table stores the three-way benchmark without altering the old schema.
    core.db_execute(
        conn,
        """
        CREATE TABLE IF NOT EXISTS founder_sim_v3_threeway_benchmarks (
            id TEXT PRIMARY KEY,
            shop_id TEXT NOT NULL,
            cycles INTEGER NOT NULL,
            baseline_json TEXT NOT NULL,
            decision_json TEXT NOT NULL,
            hybrid_json TEXT NOT NULL,
            environment_json TEXT NOT NULL,
            winner TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """,
    )


def _sigmoid(x):
    x = max(-20.0, min(20.0, float(x)))
    return 1.0 / (1.0 + math.exp(-x))


def _clamp(x, lo=0.005, hi=0.97):
    return max(lo, min(hi, float(x)))


def _stable(*parts):
    return legacy._stable_unit(*parts)


def _latent_environment(shop_id, opening, customer, cycle):
    """Hidden world state intentionally unavailable to ranking policies."""
    opening_id = opening["id"]
    customer_id = customer["id"]

    demand_roll = _stable(shop_id, opening_id, cycle, "v3_demand")
    if demand_roll < 0.14:
        demand_multiplier, demand_regime = 0.24, "very_weak"
    elif demand_roll < 0.42:
        demand_multiplier, demand_regime = 0.52, "weak"
    elif demand_roll > 0.90:
        demand_multiplier, demand_regime = 1.18, "hot"
    else:
        demand_multiplier, demand_regime = 0.82, "normal"

    distance_miles = 3.0 + 72.0 * _stable(
        shop_id, customer_id, opening_id, "v3_distance"
    )
    travel_tolerance = 8.0 + 55.0 * _stable(
        shop_id, customer_id, "v3_travel_tolerance"
    )
    distance_multiplier = (
        1.0
        if distance_miles <= travel_tolerance
        else max(0.20, math.exp(-(distance_miles - travel_tolerance) / 24.0))
    )

    observed_spend = max(100.0, float(customer.get("average_spend") or 350.0))
    hidden_budget = observed_spend * (
        0.72 + 0.75 * _stable(customer_id, "v3_budget")
    )
    price = max(1.0, float(opening.get("price") or 350.0))
    budget_ratio = price / max(1.0, hidden_budget)
    if budget_ratio <= 1.0:
        budget_multiplier = 1.0
    elif budget_ratio <= 1.25:
        budget_multiplier = 0.72
    elif budget_ratio <= 1.55:
        budget_multiplier = 0.38
    else:
        budget_multiplier = 0.12

    short_notice = _stable(opening_id, cycle, "v3_short_notice") < 0.46
    readiness = _stable(customer_id, cycle // 12, "v3_readiness")
    short_notice_multiplier = (
        0.35 + 0.85 * readiness
        if short_notice
        else 0.82 + 0.30 * readiness
    )

    fatigue_trait = _stable(customer_id, "v3_fatigue_trait")
    fatigue_phase = cycle % 15
    fatigue_multiplier = max(
        0.42,
        1.0 - fatigue_trait * (fatigue_phase / 28.0),
    )

    cold_start = _stable(customer_id, "v3_cold_start") < 0.22
    cold_start_multiplier = 0.88 if cold_start else 1.0

    artist_affinity = _stable(
        customer_id,
        opening.get("artist_id"),
        "v3_artist_affinity",
    )
    artist_multiplier = 0.62 + 0.78 * artist_affinity

    era = cycle // 40
    drift = (_stable(customer_id, era, "v3_drift") - 0.5) * 0.90
    drift_multiplier = math.exp(drift)

    noise = (
        _stable(customer_id, opening_id, cycle, "v3_noise") - 0.5
    ) * 0.48
    noise_multiplier = math.exp(noise)

    return {
        "demand_regime": demand_regime,
        "demand_multiplier": demand_multiplier,
        "distance_miles": distance_miles,
        "travel_tolerance": travel_tolerance,
        "distance_multiplier": distance_multiplier,
        "hidden_budget": hidden_budget,
        "budget_multiplier": budget_multiplier,
        "short_notice": short_notice,
        "short_notice_multiplier": short_notice_multiplier,
        "fatigue_multiplier": fatigue_multiplier,
        "cold_start": cold_start,
        "cold_start_multiplier": cold_start_multiplier,
        "artist_multiplier": artist_multiplier,
        "drift_multiplier": drift_multiplier,
        "noise_multiplier": noise_multiplier,
    }


def hidden_probability_v3(shop_id, customer, opening, cycle):
    base = legacy.hidden_probability(customer, opening)
    env = _latent_environment(shop_id, opening, customer, cycle)
    odds = base / max(1e-9, 1.0 - base)
    logit = math.log(max(1e-9, odds))
    multiplier = (
        env["demand_multiplier"]
        * env["distance_multiplier"]
        * env["budget_multiplier"]
        * env["short_notice_multiplier"]
        * env["fatigue_multiplier"]
        * env["cold_start_multiplier"]
        * env["artist_multiplier"]
        * env["drift_multiplier"]
        * env["noise_multiplier"]
    )
    p = _sigmoid(logit + math.log(max(1e-6, multiplier)))
    return _clamp(p, 0.003, 0.93), env


def _load_state(conn, shop_id):
    customers = [
        dict(row)
        for row in core.db_fetchall(
            conn,
            "SELECT * FROM customers WHERE shop_id=? AND id LIKE ?",
            (shop_id, SIM_PREFIX + "%"),
        )
    ]
    openings = [
        dict(row)
        for row in core.db_fetchall(
            conn,
            "SELECT * FROM openings WHERE shop_id=? AND id LIKE ? ORDER BY date,start_time",
            (shop_id, SIM_PREFIX + "%"),
        )
    ]
    learning = {
        row["customer_id"]: float(row.get("calibration_delta") or 0.0)
        for row in [
            dict(item)
            for item in core.db_fetchall(
                conn,
                "SELECT customer_id,calibration_delta FROM founder_sim_customer_learning WHERE shop_id=?",
                (shop_id,),
            )
        ]
    }
    pairwise = {
        row["customer_id"]: float(row.get("pairwise_delta") or 0.0)
        for row in [
            dict(item)
            for item in core.db_fetchall(
                conn,
                "SELECT customer_id,pairwise_delta FROM founder_sim_pairwise_learning WHERE shop_id=?",
                (shop_id,),
            )
        ]
    }
    return customers, openings, learning, pairwise


def _baseline_order(customers, opening):
    ranked = m4_runtime.rank(customers, opening, len(customers))
    by_id = {customer["id"]: customer for customer in customers}
    return [by_id[row["customer_id"]] for row in ranked]


def _decision_value(customer, opening, learning, pairwise):
    return decision.decision_score(
        customer,
        opening,
        learning.get(customer["id"], 0.0),
        pairwise.get(customer["id"], 0.0),
    )


def _ordered(policy_name, customers, opening, learning, pairwise):
    baseline_order = _baseline_order(customers, opening)

    if policy_name == "baseline":
        return baseline_order

    if policy_name == "decision":
        return sorted(
            customers,
            key=lambda customer: _decision_value(
                customer,
                opening,
                learning,
                pairwise,
            ),
            reverse=True,
        )

    if policy_name == "hybrid":
        # Preserve the baseline candidate pool and only re-rank the decision
        # boundary. This is intentionally conservative: learned evidence can
        # change who is contacted first, but cannot elevate a weak candidate
        # from deep in the slate above the baseline's top five.
        top_five = baseline_order[:5]
        tail = baseline_order[5:]
        reranked_top_five = sorted(
            top_five,
            key=lambda customer: _decision_value(
                customer,
                opening,
                learning,
                pairwise,
            ),
            reverse=True,
        )
        return reranked_top_five + tail

    raise ValueError(f"Unknown V3 policy: {policy_name}")


def _evaluate(
    shop_id,
    cycles,
    policy_name,
    customers,
    openings,
    learning,
    pairwise,
    seed_offset,
):
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
            ordered = _ordered(
                policy_name,
                customers,
                opening,
                learning,
                pairwise,
            )
            accepted_flags = []
            environments = []

            for customer in ordered:
                truth, env = hidden_probability_v3(
                    shop_id,
                    customer,
                    opening,
                    cycle,
                )
                accepted = (
                    _stable(
                        shop_id,
                        opening["id"],
                        customer["id"],
                        cycle,
                        "v3_accept",
                    )
                    < truth
                )
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

            booked_index = next(
                (
                    position
                    for position, accepted in enumerate(accepted_flags)
                    if accepted
                ),
                None,
            )

            if booked_index is None:
                totals["unfilled_openings"] += 1
                totals["contacts"] += len(ordered)
                contact_range = range(len(ordered))
            else:
                totals["bookings"] += 1
                totals["contacts"] += booked_index + 1
                totals["recovered_revenue"] += float(
                    opening.get("price") or 0.0
                )
                contact_range = range(booked_index + 1)

            for position in contact_range:
                env = environments[position]
                if env["cold_start"]:
                    totals["cold_start_contacts"] += 1
                if env["budget_multiplier"] <= 0.38:
                    totals["budget_blocked_contacts"] += 1
                if env["distance_multiplier"] <= 0.45:
                    totals["distance_blocked_contacts"] += 1

    openings_count = max(1, totals["openings"])
    bookings_count = max(1, totals["bookings"])
    contacts_count = max(1, totals["contacts"])

    totals["top1_rate"] = totals["top1_bookings"] / openings_count
    totals["top3_rate"] = totals["top3_bookings"] / openings_count
    totals["booking_rate"] = totals["bookings"] / openings_count
    totals["unfilled_rate"] = totals["unfilled_openings"] / openings_count
    totals["contacts_per_booking"] = totals["contacts"] / bookings_count
    totals["revenue_per_contact"] = (
        totals["recovered_revenue"] / contacts_count
    )
    return totals


def _lift(candidate, baseline):
    return {
        "top1_rate": candidate["top1_rate"] - baseline["top1_rate"],
        "top3_rate": candidate["top3_rate"] - baseline["top3_rate"],
        "booking_rate": candidate["booking_rate"] - baseline["booking_rate"],
        "unfilled_rate": candidate["unfilled_rate"] - baseline["unfilled_rate"],
        "recovered_revenue": (
            candidate["recovered_revenue"] - baseline["recovered_revenue"]
        ),
        "contacts_per_booking": (
            candidate["contacts_per_booking"]
            - baseline["contacts_per_booking"]
        ),
        "revenue_per_contact": (
            candidate["revenue_per_contact"]
            - baseline["revenue_per_contact"]
        ),
    }


def _winner(policies):
    # Business-first winner. Revenue/contact is primary; top-1 is the tie-break.
    best_name = None
    best_metrics = None
    for name, metrics in policies.items():
        if best_metrics is None:
            best_name, best_metrics = name, metrics
            continue
        if metrics["revenue_per_contact"] > best_metrics["revenue_per_contact"] * 1.001:
            best_name, best_metrics = name, metrics
            continue
        revenue_close = abs(
            metrics["revenue_per_contact"] - best_metrics["revenue_per_contact"]
        ) <= max(0.50, best_metrics["revenue_per_contact"] * 0.001)
        if revenue_close and metrics["top1_rate"] > best_metrics["top1_rate"]:
            best_name, best_metrics = name, metrics
    return best_name or "baseline"


def run_benchmark(shop_id, cycles=250):
    cycles = max(50, min(int(cycles), 500))
    pairwise_training = decision.rebuild_pairwise_learning(shop_id)

    conn = core.connect()
    try:
        load_and_assert_founder_simulation_target(
            conn,
            core.db_fetchone,
            shop_id,
        )
        decision.ensure_tables(conn)
        ensure_tables(conn)
        conn.commit()

        customers, openings, learning, pairwise = _load_state(conn, shop_id)
        if not customers or not openings:
            raise RuntimeError(
                "Crybaby founder simulation must be seeded before V3 benchmarking."
            )

        row = core.db_fetchone(
            conn,
            "SELECT MAX(cycle) AS max_cycle FROM founder_sim_metrics WHERE shop_id=?",
            (shop_id,),
        )
        conn.rollback()
    finally:
        conn.close()

    seed_offset = (
        int(row["max_cycle"] or 0) + 30000
        if row
        else 30000
    )

    baseline = _evaluate(
        shop_id,
        cycles,
        "baseline",
        customers,
        openings,
        learning,
        pairwise,
        seed_offset,
    )
    full_decision = _evaluate(
        shop_id,
        cycles,
        "decision",
        customers,
        openings,
        learning,
        pairwise,
        seed_offset,
    )
    hybrid = _evaluate(
        shop_id,
        cycles,
        "hybrid",
        customers,
        openings,
        learning,
        pairwise,
        seed_offset,
    )

    policies = {
        "baseline": baseline,
        "decision": full_decision,
        "hybrid": hybrid,
    }
    winner = _winner(policies)

    environment = {
        "version": "v3-adversarial-threeway",
        "weak_demand_share_target": 0.28,
        "very_weak_demand_share_target": 0.14,
        "cold_start_share_target": 0.22,
        "hybrid_top_n": 5,
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
        "pairwise_training": pairwise_training,
        "baseline": baseline,
        "decision": full_decision,
        "hybrid": hybrid,
        "lift": {
            "decision_vs_baseline": _lift(full_decision, baseline),
            "hybrid_vs_baseline": _lift(hybrid, baseline),
        },
        "winner": winner,
        "success_bar": {
            "baseline_top1_rate": baseline["top1_rate"],
            "baseline_top3_rate": baseline["top3_rate"],
            "baseline_contacts_per_booking": baseline["contacts_per_booking"],
            "baseline_revenue_per_contact": baseline["revenue_per_contact"],
        },
    }

    conn = core.connect()
    try:
        ensure_tables(conn)
        conn.commit()
        benchmark_id = "founder_sim_v3_threeway_" + uuid.uuid4().hex
        core.db_execute(
            conn,
            """
            INSERT INTO founder_sim_v3_threeway_benchmarks(
                id,shop_id,cycles,baseline_json,decision_json,hybrid_json,
                environment_json,winner,created_at
            ) VALUES (?,?,?,?,?,?,?,?,?)
            """,
            (
                benchmark_id,
                shop_id,
                cycles,
                json.dumps(baseline),
                json.dumps(full_decision),
                json.dumps(hybrid),
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


def latest_benchmark(shop_id):
    conn = core.connect()
    try:
        ensure_tables(conn)
        conn.commit()
        row = core.db_fetchone(
            conn,
            """
            SELECT * FROM founder_sim_v3_threeway_benchmarks
            WHERE shop_id=? ORDER BY created_at DESC LIMIT 1
            """,
            (shop_id,),
        )
        conn.rollback()
        if not row:
            return None
        item = dict(row)
        item["baseline"] = json.loads(item.pop("baseline_json"))
        item["decision"] = json.loads(item.pop("decision_json"))
        item["hybrid"] = json.loads(item.pop("hybrid_json"))
        item["environment"] = json.loads(item.pop("environment_json"))
        return item
    finally:
        conn.close()
