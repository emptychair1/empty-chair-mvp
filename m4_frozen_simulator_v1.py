"""Frozen M4 V1 simulation world candidate.

This module defines the final synthetic environment used for M4 V1 training and
holdout generation. Once the validation benchmark lands inside the declared fill
bands, these mechanics are frozen for V1.

Key realism change: some openings are structurally unfillable. A large customer
pool must not imply that every opening can eventually be recovered merely by
contacting enough people.
"""
from __future__ import annotations

import json
import math
import uuid

import app as core
import m4_founder_simulation_engine as legacy
import m4_runtime
import m4_stress_benchmark_v3 as v3
from founder_simulation_safety import load_and_assert_founder_simulation_target

VERSION = "m4-v1-frozen-world-candidate-1"

REGIMES = {
    "easy": {
        "structural_unfillable": 0.08,
        "demand_scale": 1.18,
        "probability_cap": 0.94,
        "target_fill_min": 0.88,
        "target_fill_max": 0.94,
    },
    "normal": {
        "structural_unfillable": 0.18,
        "demand_scale": 0.92,
        "probability_cap": 0.90,
        "target_fill_min": 0.76,
        "target_fill_max": 0.86,
    },
    "hard": {
        "structural_unfillable": 0.32,
        "demand_scale": 0.68,
        "probability_cap": 0.84,
        "target_fill_min": 0.62,
        "target_fill_max": 0.76,
    },
}


def _stable(*parts):
    return legacy._stable_unit(*parts)


def _sigmoid(value):
    value = max(-20.0, min(20.0, float(value)))
    return 1.0 / (1.0 + math.exp(-value))


def _opening_market_state(shop_id, opening, cycle, regime):
    config = REGIMES[regime]
    roll = _stable(shop_id, opening["id"], cycle, regime, "market_available")
    structurally_unfillable = roll < config["structural_unfillable"]
    return {
        "regime": regime,
        "structurally_unfillable": structurally_unfillable,
        "market_roll": roll,
    }


def hidden_probability(shop_id, customer, opening, cycle, regime):
    if regime not in REGIMES:
        raise ValueError(f"Unknown frozen simulator regime: {regime}")

    market = _opening_market_state(shop_id, opening, cycle, regime)
    base_probability, env = v3.hidden_probability_v3(shop_id, customer, opening, cycle)
    env = dict(env)
    env.update(market)

    if market["structurally_unfillable"]:
        env["frozen_probability"] = 0.0
        return 0.0, env

    config = REGIMES[regime]
    odds = base_probability / max(1e-9, 1.0 - base_probability)
    logit = math.log(max(1e-9, odds))

    opening_jitter = 0.72 + 0.58 * _stable(
        shop_id, opening["id"], cycle // 5, regime, "opening_demand_jitter"
    )
    scaled = _sigmoid(
        logit + math.log(max(1e-6, config["demand_scale"] * opening_jitter))
    )
    probability = max(0.001, min(config["probability_cap"], scaled))
    env["frozen_probability"] = probability
    env["opening_demand_jitter"] = opening_jitter
    return probability, env


def _load(conn, shop_id):
    sim_pattern = "founder_sim_%"
    customers = [
        dict(row) for row in core.db_fetchall(
            conn,
            "SELECT * FROM customers WHERE shop_id=? AND id LIKE ?",
            (shop_id, sim_pattern),
        )
    ]
    openings = [
        dict(row) for row in core.db_fetchall(
            conn,
            "SELECT * FROM openings WHERE shop_id=? AND id LIKE ? ORDER BY date,start_time",
            (shop_id, sim_pattern),
        )
    ]
    return customers, openings


def _baseline_order(customers, opening):
    ranked = m4_runtime.rank(customers, opening, len(customers))
    by_id = {customer["id"]: customer for customer in customers}
    return [by_id[row["customer_id"]] for row in ranked]


def _evaluate_regime(shop_id, cycles, customers, openings, regime, seed_offset):
    totals = {
        "cycles": cycles,
        "openings": 0,
        "bookings": 0,
        "unfilled_openings": 0,
        "structurally_unfillable_openings": 0,
        "market_available_unfilled": 0,
        "top1_bookings": 0,
        "top3_bookings": 0,
        "contacts": 0,
        "recovered_revenue": 0.0,
    }

    for index in range(1, cycles + 1):
        cycle = seed_offset + index
        for opening in openings:
            totals["openings"] += 1
            order = _baseline_order(customers, opening)
            market = _opening_market_state(shop_id, opening, cycle, regime)
            if market["structurally_unfillable"]:
                totals["structurally_unfillable_openings"] += 1

            flags = []
            for customer in order:
                probability, _ = hidden_probability(
                    shop_id, customer, opening, cycle, regime
                )
                accepted = _stable(
                    shop_id,
                    opening["id"],
                    customer["id"],
                    cycle,
                    regime,
                    "frozen_accept",
                ) < probability
                flags.append(bool(accepted))

            if flags and flags[0]:
                totals["top1_bookings"] += 1
            if any(flags[:3]):
                totals["top3_bookings"] += 1

            booked_index = next(
                (position for position, accepted in enumerate(flags) if accepted),
                None,
            )
            if booked_index is None:
                totals["unfilled_openings"] += 1
                totals["contacts"] += len(order)
                if not market["structurally_unfillable"]:
                    totals["market_available_unfilled"] += 1
            else:
                totals["bookings"] += 1
                totals["contacts"] += booked_index + 1
                totals["recovered_revenue"] += float(opening.get("price") or 0.0)

    opening_count = max(1, totals["openings"])
    booking_count = max(1, totals["bookings"])
    contact_count = max(1, totals["contacts"])
    totals["fill_rate"] = totals["bookings"] / opening_count
    totals["unfilled_rate"] = totals["unfilled_openings"] / opening_count
    totals["structural_unfillable_rate"] = (
        totals["structurally_unfillable_openings"] / opening_count
    )
    totals["top1_rate"] = totals["top1_bookings"] / opening_count
    totals["top3_rate"] = totals["top3_bookings"] / opening_count
    totals["contacts_per_booking"] = totals["contacts"] / booking_count
    totals["revenue_per_contact"] = totals["recovered_revenue"] / contact_count

    config = REGIMES[regime]
    totals["target_fill_band"] = [
        config["target_fill_min"], config["target_fill_max"]
    ]
    totals["inside_target_band"] = (
        config["target_fill_min"] <= totals["fill_rate"] <= config["target_fill_max"]
    )
    return totals


def ensure_table(conn):
    core.db_execute(conn, """
        CREATE TABLE IF NOT EXISTS founder_sim_frozen_world_benchmarks (
            id TEXT PRIMARY KEY,
            shop_id TEXT NOT NULL,
            cycles INTEGER NOT NULL,
            version TEXT NOT NULL,
            result_json TEXT NOT NULL,
            freeze_ready INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL
        )
    """)


def run_benchmark(shop_id, cycles=250):
    cycles = max(100, min(int(cycles), 500))
    conn = core.connect()
    try:
        load_and_assert_founder_simulation_target(conn, core.db_fetchone, shop_id)
        ensure_table(conn)
        conn.commit()
        customers, openings = _load(conn, shop_id)
        row = core.db_fetchone(
            conn,
            "SELECT MAX(cycle) AS max_cycle FROM founder_sim_metrics WHERE shop_id=?",
            (shop_id,),
        )
        conn.rollback()
    finally:
        conn.close()

    if not customers or not openings:
        raise RuntimeError("Crybaby founder simulation must be seeded before frozen-world validation.")

    seed_offset = int(row["max_cycle"] or 0) + 50000 if row else 50000
    regimes = {
        name: _evaluate_regime(
            shop_id, cycles, customers, openings, name, seed_offset
        )
        for name in ("easy", "normal", "hard")
    }
    freeze_ready = all(result["inside_target_band"] for result in regimes.values())

    result = {
        "environment": {
            "version": VERSION,
            "status": "FREEZE_READY" if freeze_ready else "NEEDS_ONE_FINAL_CALIBRATION",
            "mechanics": [
                "shared opening-level market state",
                "structurally unfillable openings",
                "V3 budget and distance friction",
                "short-notice readiness",
                "offer fatigue",
                "cold-start customers",
                "artist affinity",
                "behavioral drift",
                "adversarial noise",
            ],
            "regime_config": REGIMES,
        },
        "cycles_per_regime": cycles,
        "regimes": regimes,
        "freeze_ready": freeze_ready,
    }

    conn = core.connect()
    try:
        ensure_table(conn)
        conn.commit()
        benchmark_id = "founder_sim_frozen_world_" + uuid.uuid4().hex
        core.db_execute(
            conn,
            """INSERT INTO founder_sim_frozen_world_benchmarks(
                id,shop_id,cycles,version,result_json,freeze_ready,created_at
            ) VALUES (?,?,?,?,?,?,?)""",
            (
                benchmark_id,
                shop_id,
                cycles,
                VERSION,
                json.dumps(result),
                1 if freeze_ready else 0,
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
