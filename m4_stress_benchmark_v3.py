"""Simulation V3: adversarial/realistic M4 policy stress benchmark.

V3 keeps the existing V2 benchmark intact and evaluates both policies against a
harder synthetic world with weak demand, ambiguous customers, budget/distance
friction, short-notice mismatch, fatigue, cold-start uncertainty, hidden artist
loyalty, noisy signals, and behavioral drift.

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


def _sigmoid(x):
    x = max(-20.0, min(20.0, float(x)))
    return 1.0 / (1.0 + math.exp(-x))


def _clamp(x, lo=0.005, hi=0.97):
    return max(lo, min(hi, float(x)))


def _stable(*parts):
    return legacy._stable_unit(*parts)


def _latent_environment(shop_id, opening, customer, cycle):
    """Hidden world state intentionally unavailable to either ranking policy."""
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

    distance_miles = 3.0 + 72.0 * _stable(shop_id, customer_id, opening_id, "v3_distance")
    travel_tolerance = 8.0 + 55.0 * _stable(shop_id, customer_id, "v3_travel_tolerance")
    distance_multiplier = 1.0 if distance_miles <= travel_tolerance else max(0.20, math.exp(-(distance_miles - travel_tolerance) / 24.0))

    observed_spend = max(100.0, float(customer.get("average_spend") or 350.0))
    hidden_budget = observed_spend * (0.72 + 0.75 * _stable(customer_id, "v3_budget"))
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
    short_notice_multiplier = (0.35 + 0.85 * readiness) if short_notice else (0.82 + 0.30 * readiness)

    fatigue_trait = _stable(customer_id, "v3_fatigue_trait")
    fatigue_phase = cycle % 15
    fatigue_multiplier = max(0.42, 1.0 - fatigue_trait * (fatigue_phase / 28.0))
    cold_start = _stable(customer_id, "v3_cold_start") < 0.22
    cold_start_multiplier = 0.88 if cold_start else 1.0
    artist_affinity = _stable(customer_id, opening.get("artist_id"), "v3_artist_affinity")
    artist_multiplier = 0.62 + 0.78 * artist_affinity
    era = cycle // 40
    drift = (_stable(customer_id, era, "v3_drift") - 0.5) * 0.90
    drift_multiplier = math.exp(drift)
    noise = (_stable(customer_id, opening_id, cycle, "v3_noise") - 0.5) * 0.48
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
        env["demand_multiplier"] * env["distance_multiplier"] * env["budget_multiplier"]
        * env["short_notice_multiplier"] * env["fatigue_multiplier"]
        * env["cold_start_multiplier"] * env["artist_multiplier"]
        * env["drift_multiplier"] * env["noise_multiplier"]
    )
    p = _sigmoid(logit + math.log(max(1e-6, multiplier)))
    return _clamp(p, 0.003, 0.93), env


def _load_state(conn, shop_id):
    customers = [dict(r) for r in core.db_fetchall(conn, "SELECT * FROM customers WHERE shop_id=? AND id LIKE ?", (shop_id, SIM_PREFIX + "%"))]
    openings = [dict(r) for r in core.db_fetchall(conn, "SELECT * FROM openings WHERE shop_id=? AND id LIKE ? ORDER BY date,start_time", (shop_id, SIM_PREFIX + "%"))]
    learning = {r["customer_id"]: float(r.get("calibration_delta") or 0.0) for r in [dict(x) for x in core.db_fetchall(conn, "SELECT customer_id,calibration_delta FROM founder_sim_customer_learning WHERE shop_id=?", (shop_id,))]}
    pairwise = {r["customer_id"]: float(r.get("pairwise_delta") or 0.0) for r in [dict(x) for x in core.db_fetchall(conn, "SELECT customer_id,pairwise_delta FROM founder_sim_pairwise_learning WHERE shop_id=?", (shop_id,))]}
    return customers, openings, learning, pairwise


def _ordered(policy_name, customers, opening, learning, pairwise):
    if policy_name == "baseline":
        ranked = m4_runtime.rank(customers, opening, len(customers))
        by_id = {c["id"]: c for c in customers}
        return [by_id[row["customer_id"]] for row in ranked]
    return sorted(customers, key=lambda c: decision.decision_score(c, opening, learning.get(c["id"], 0.0), pairwise.get(c["id"], 0.0)), reverse=True)


def _evaluate(shop_id, cycles, policy_name, customers, openings, learning, pairwise, seed_offset):
    totals = {"cycles": cycles, "openings": 0, "top1_bookings": 0, "top3_bookings": 0, "bookings": 0, "unfilled_openings": 0, "contacts": 0, "recovered_revenue": 0.0, "weak_demand_openings": 0, "very_weak_demand_openings": 0, "cold_start_contacts": 0, "budget_blocked_contacts": 0, "distance_blocked_contacts": 0}
    for i in range(1, cycles + 1):
        cycle = seed_offset + i
        for opening in openings:
            totals["openings"] += 1
            ordered = _ordered(policy_name, customers, opening, learning, pairwise)
            accepted_flags, envs = [], []
            for customer in ordered:
                truth, env = hidden_probability_v3(shop_id, customer, opening, cycle)
                accepted_flags.append(_stable(shop_id, opening["id"], customer["id"], cycle, "v3_accept") < truth)
                envs.append(env)
            if envs:
                if envs[0]["demand_regime"] == "weak": totals["weak_demand_openings"] += 1
                elif envs[0]["demand_regime"] == "very_weak": totals["very_weak_demand_openings"] += 1
            if accepted_flags and accepted_flags[0]: totals["top1_bookings"] += 1
            if any(accepted_flags[:3]): totals["top3_bookings"] += 1
            booked_index = next((idx for idx, yes in enumerate(accepted_flags) if yes), None)
            if booked_index is None:
                totals["unfilled_openings"] += 1
                totals["contacts"] += len(ordered)
                contact_range = range(len(ordered))
            else:
                totals["bookings"] += 1
                totals["contacts"] += booked_index + 1
                totals["recovered_revenue"] += float(opening.get("price") or 0.0)
                contact_range = range(booked_index + 1)
            for idx in contact_range:
                env = envs[idx]
                if env["cold_start"]: totals["cold_start_contacts"] += 1
                if env["budget_multiplier"] <= 0.38: totals["budget_blocked_contacts"] += 1
                if env["distance_multiplier"] <= 0.45: totals["distance_blocked_contacts"] += 1
    n_openings, n_bookings, n_contacts = max(1, totals["openings"]), max(1, totals["bookings"]), max(1, totals["contacts"])
    totals["top1_rate"] = totals["top1_bookings"] / n_openings
    totals["top3_rate"] = totals["top3_bookings"] / n_openings
    totals["booking_rate"] = totals["bookings"] / n_openings
    totals["unfilled_rate"] = totals["unfilled_openings"] / n_openings
    totals["contacts_per_booking"] = totals["contacts"] / n_bookings
    totals["revenue_per_contact"] = totals["recovered_revenue"] / n_contacts
    return totals


def run_benchmark(shop_id, cycles=250):
    cycles = max(50, min(int(cycles), 500))
    pairwise_training = decision.rebuild_pairwise_learning(shop_id)
    conn = core.connect()
    try:
        load_and_assert_founder_simulation_target(conn, core.db_fetchone, shop_id)
        decision.ensure_tables(conn)
        ensure_tables(conn)
        # DDL must be committed before we close this connection. Previously this
        # transaction was rolled back after reading MAX(cycle), so the final
        # result insert could not see founder_sim_v3_benchmarks on first run.
        conn.commit()
        customers, openings, learning, pairwise = _load_state(conn, shop_id)
        if not customers or not openings:
            raise RuntimeError("Crybaby founder simulation must be seeded before V3 benchmarking.")
        row = core.db_fetchone(conn, "SELECT MAX(cycle) AS max_cycle FROM founder_sim_metrics WHERE shop_id=?", (shop_id,))
        conn.rollback()
    finally:
        conn.close()

    seed_offset = int(row["max_cycle"] or 0) + 30000 if row else 30000
    baseline = _evaluate(shop_id, cycles, "baseline", customers, openings, learning, pairwise, seed_offset)
    new_policy = _evaluate(shop_id, cycles, "decision", customers, openings, learning, pairwise, seed_offset)
    lift = {
        "top1_rate": new_policy["top1_rate"] - baseline["top1_rate"],
        "top3_rate": new_policy["top3_rate"] - baseline["top3_rate"],
        "booking_rate": new_policy["booking_rate"] - baseline["booking_rate"],
        "unfilled_rate": new_policy["unfilled_rate"] - baseline["unfilled_rate"],
        "recovered_revenue": new_policy["recovered_revenue"] - baseline["recovered_revenue"],
        "contacts_per_booking": new_policy["contacts_per_booking"] - baseline["contacts_per_booking"],
        "revenue_per_contact": new_policy["revenue_per_contact"] - baseline["revenue_per_contact"],
    }
    if new_policy["revenue_per_contact"] > baseline["revenue_per_contact"] * 1.005: winner = "decision"
    elif baseline["revenue_per_contact"] > new_policy["revenue_per_contact"] * 1.005: winner = "baseline"
    elif new_policy["top1_rate"] > baseline["top1_rate"]: winner = "decision"
    elif baseline["top1_rate"] > new_policy["top1_rate"]: winner = "baseline"
    else: winner = "tie"
    environment = {"version": "v3-adversarial", "weak_demand_share_target": 0.28, "very_weak_demand_share_target": 0.14, "cold_start_share_target": 0.22, "features": ["weak_demand", "ambiguous_candidates", "hidden_budget", "distance_friction", "short_notice_readiness", "offer_fatigue", "cold_start", "hidden_artist_affinity", "behavioral_drift", "adversarial_noise"]}
    result = {"environment": environment, "cycles_per_policy": cycles, "pairwise_training": pairwise_training, "baseline": baseline, "decision": new_policy, "lift": lift, "winner": winner}

    conn = core.connect()
    try:
        # Defensive/idempotent: guarantees the result table exists even if a
        # deployment or database transaction interrupted the earlier setup.
        ensure_tables(conn)
        conn.commit()
        benchmark_id = "founder_sim_v3_benchmark_" + uuid.uuid4().hex
        core.db_execute(conn, """INSERT INTO founder_sim_v3_benchmarks(id,shop_id,cycles,baseline_json,decision_json,environment_json,winner,created_at) VALUES (?,?,?,?,?,?,?,?)""", (benchmark_id, shop_id, cycles, json.dumps(baseline), json.dumps(new_policy), json.dumps(environment), winner, core.now_iso()))
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
        row = core.db_fetchone(conn, "SELECT * FROM founder_sim_v3_benchmarks WHERE shop_id=? ORDER BY created_at DESC LIMIT 1", (shop_id,))
        conn.rollback()
        if not row: return None
        item = dict(row)
        item["baseline"] = json.loads(item.pop("baseline_json"))
        item["decision"] = json.loads(item.pop("decision_json"))
        item["environment"] = json.loads(item.pop("environment_json"))
        return item
    finally:
        conn.close()
