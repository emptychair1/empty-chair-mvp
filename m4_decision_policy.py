"""Pairwise decision policy and A/B benchmark for the Crybaby founder lab.

This module learns relative customer preference from historical founder-simulation
outcomes, then compares the legacy M4 ranking against a decision-value policy on
identical deterministic future synthetic outcomes.

No real customer is contacted and no production shop data is mutated. Only
founder_sim_* learning/benchmark tables for the validated Crybaby sandbox are
written.
"""

from __future__ import annotations

import json
import math
import uuid

import app as core
import m4_founder_simulation_engine as legacy
import m4_founder_simulation_engine_v2 as engine
import m4_runtime
from founder_simulation_safety import load_and_assert_founder_simulation_target

SIM_PREFIX = "founder_sim_"


def ensure_tables(conn):
    core.db_execute(
        conn,
        """
        CREATE TABLE IF NOT EXISTS founder_sim_pairwise_learning (
            shop_id TEXT NOT NULL,
            customer_id TEXT NOT NULL,
            wins INTEGER NOT NULL DEFAULT 0,
            losses INTEGER NOT NULL DEFAULT 0,
            pairwise_delta REAL NOT NULL DEFAULT 0,
            updated_at TEXT NOT NULL,
            PRIMARY KEY(shop_id, customer_id)
        )
        """,
    )
    core.db_execute(
        conn,
        """
        CREATE TABLE IF NOT EXISTS founder_sim_policy_benchmarks (
            id TEXT PRIMARY KEY,
            shop_id TEXT NOT NULL,
            cycles INTEGER NOT NULL,
            baseline_json TEXT NOT NULL,
            decision_json TEXT NOT NULL,
            winner TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """,
    )


def rebuild_pairwise_learning(shop_id):
    """Derive relative wins/losses from existing synthetic outcome history."""
    conn = core.connect()
    try:
        load_and_assert_founder_simulation_target(conn, core.db_fetchone, shop_id)
        ensure_tables(conn)
        rows = [
            dict(row)
            for row in core.db_fetchall(
                conn,
                """SELECT cycle,opening_id,customer_id,accepted
                   FROM founder_sim_outcomes
                   WHERE shop_id=?
                   ORDER BY cycle,opening_id,rank""",
                (shop_id,),
            )
        ]
        grouped = {}
        for row in rows:
            grouped.setdefault((row["cycle"], row["opening_id"]), []).append(row)

        state = {}
        for candidates in grouped.values():
            accepted = [row for row in candidates if int(row.get("accepted") or 0) == 1]
            rejected = [row for row in candidates if int(row.get("accepted") or 0) == 0]
            if not accepted or not rejected:
                continue
            for winner in accepted:
                bucket = state.setdefault(winner["customer_id"], [0, 0])
                bucket[0] += len(rejected)
            for loser in rejected:
                bucket = state.setdefault(loser["customer_id"], [0, 0])
                bucket[1] += len(accepted)

        core.db_execute(
            conn,
            "DELETE FROM founder_sim_pairwise_learning WHERE shop_id=?",
            (shop_id,),
        )
        now = core.now_iso()
        for customer_id, (wins, losses) in state.items():
            total = wins + losses
            # Smoothed log-odds. Clamp so pairwise history informs ranking without
            # overwhelming probability, fit, reliability, and revenue signals.
            delta = math.log((wins + 3.0) / (losses + 3.0))
            delta = max(-1.25, min(1.25, delta))
            core.db_execute(
                conn,
                """INSERT INTO founder_sim_pairwise_learning(
                    shop_id,customer_id,wins,losses,pairwise_delta,updated_at
                ) VALUES (?,?,?,?,?,?)""",
                (shop_id, customer_id, wins, losses, delta, now),
            )
        conn.commit()
        return {"customers": len(state), "comparisons": sum(w + l for w, l in state.values())}
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


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
            dict(r)
            for r in core.db_fetchall(
                conn,
                "SELECT customer_id,calibration_delta FROM founder_sim_customer_learning WHERE shop_id=?",
                (shop_id,),
            )
        ]
    }
    pairwise = {
        row["customer_id"]: float(row.get("pairwise_delta") or 0.0)
        for row in [
            dict(r)
            for r in core.db_fetchall(
                conn,
                "SELECT customer_id,pairwise_delta FROM founder_sim_pairwise_learning WHERE shop_id=?",
                (shop_id,),
            )
        ]
    }
    return customers, openings, learning, pairwise


def _learned_probability(customer, opening, calibration_delta):
    baseline = float(m4_runtime.score(customer, opening)["booking_probability"])
    baseline = max(0.01, min(0.99, baseline))
    logit = math.log(baseline / (1.0 - baseline)) + float(calibration_delta)
    return max(0.01, min(0.99, 1.0 / (1.0 + math.exp(-max(-20.0, min(20.0, logit))))))


def _fit_multiplier(customer, opening):
    styles = {
        x.strip().lower()
        for x in str(customer.get("preferred_styles") or "").split(",")
        if x.strip()
    }
    artists = {
        x.strip()
        for x in str(customer.get("preferred_artists") or "").split(",")
        if x.strip()
    }
    style_match = str(opening.get("style") or "").strip().lower() in styles
    artist_match = str(opening.get("artist_id") or "").strip() in artists
    reliability = 1.0
    reliability += min(0.20, 0.03 * float(customer.get("completed_count") or 0))
    reliability -= min(0.35, 0.12 * float(customer.get("cancellation_count") or 0))
    reliability -= min(0.45, 0.20 * float(customer.get("no_show_count") or 0))
    fit = 1.0 + (0.18 if style_match else 0.0) + (0.12 if artist_match else 0.0)
    return max(0.45, fit * reliability)


def decision_score(customer, opening, calibration_delta=0.0, pairwise_delta=0.0):
    probability = _learned_probability(customer, opening, calibration_delta)
    price = max(1.0, float(opening.get("price") or 350.0))
    fit = _fit_multiplier(customer, opening)
    pairwise_factor = math.exp(max(-1.25, min(1.25, pairwise_delta)) * 0.35)
    # Expected recoverable revenue, adjusted by relative slate evidence.
    return probability * price * fit * pairwise_factor


def _evaluate_policy(shop_id, cycles, policy, customers, openings, learning, pairwise, seed_offset):
    totals = {
        "cycles": cycles,
        "openings": 0,
        "top1_bookings": 0,
        "top3_bookings": 0,
        "bookings": 0,
        "contacts": 0,
        "recovered_revenue": 0.0,
    }

    # Both policies see identical deterministic future outcomes. The policy only
    # changes order, not whether a customer would accept that opening.
    for cycle_index in range(1, cycles + 1):
        synthetic_cycle = seed_offset + cycle_index
        for opening in openings:
            totals["openings"] += 1
            if policy == "baseline":
                ranked = m4_runtime.rank(customers, opening, len(customers))
                ordered = [next(c for c in customers if c["id"] == row["customer_id"]) for row in ranked]
            else:
                ordered = sorted(
                    customers,
                    key=lambda c: decision_score(
                        c,
                        opening,
                        learning.get(c["id"], 0.0),
                        pairwise.get(c["id"], 0.0),
                    ),
                    reverse=True,
                )

            accepted_flags = []
            for customer in ordered:
                truth = legacy.hidden_probability(customer, opening)
                accepted = legacy._stable_unit(
                    shop_id,
                    opening["id"],
                    customer["id"],
                    synthetic_cycle,
                    "policy_benchmark_accept",
                ) < truth
                accepted_flags.append(bool(accepted))

            if accepted_flags and accepted_flags[0]:
                totals["top1_bookings"] += 1
            if any(accepted_flags[:3]):
                totals["top3_bookings"] += 1

            # Sequential-contact economics: stop at first accepting customer.
            booked_index = next((i for i, accepted in enumerate(accepted_flags) if accepted), None)
            if booked_index is not None:
                totals["bookings"] += 1
                totals["contacts"] += booked_index + 1
                totals["recovered_revenue"] += float(opening.get("price") or 0.0)
            else:
                totals["contacts"] += len(ordered)

    openings_count = max(1, totals["openings"])
    bookings_count = max(1, totals["bookings"])
    totals["top1_rate"] = totals["top1_bookings"] / openings_count
    totals["top3_rate"] = totals["top3_bookings"] / openings_count
    totals["booking_rate"] = totals["bookings"] / openings_count
    totals["contacts_per_booking"] = totals["contacts"] / bookings_count
    totals["revenue_per_contact"] = totals["recovered_revenue"] / max(1, totals["contacts"])
    return totals


def run_benchmark(shop_id, cycles=250):
    cycles = max(20, min(int(cycles), 500))
    pairwise_summary = rebuild_pairwise_learning(shop_id)

    conn = core.connect()
    try:
        load_and_assert_founder_simulation_target(conn, core.db_fetchone, shop_id)
        ensure_tables(conn)
        customers, openings, learning, pairwise = _load_state(conn, shop_id)
        if not customers or not openings:
            raise RuntimeError("Crybaby founder simulation must be seeded before benchmarking.")
        max_cycle_row = core.db_fetchone(
            conn,
            "SELECT MAX(cycle) AS max_cycle FROM founder_sim_metrics WHERE shop_id=?",
            (shop_id,),
        )
        conn.rollback()
    finally:
        conn.close()

    seed_offset = int(max_cycle_row["max_cycle"] or 0) + 10000 if max_cycle_row else 10000
    baseline = _evaluate_policy(shop_id, cycles, "baseline", customers, openings, learning, pairwise, seed_offset)
    decision = _evaluate_policy(shop_id, cycles, "decision", customers, openings, learning, pairwise, seed_offset)

    # Business-first winner: revenue/contact, then top-1 rate, then contacts/booking.
    if decision["revenue_per_contact"] > baseline["revenue_per_contact"] * 1.001:
        winner = "decision"
    elif baseline["revenue_per_contact"] > decision["revenue_per_contact"] * 1.001:
        winner = "baseline"
    elif decision["top1_rate"] > baseline["top1_rate"]:
        winner = "decision"
    elif baseline["top1_rate"] > decision["top1_rate"]:
        winner = "baseline"
    else:
        winner = "tie"

    result = {
        "cycles_per_policy": cycles,
        "pairwise_training": pairwise_summary,
        "baseline": baseline,
        "decision": decision,
        "lift": {
            "top1_rate": decision["top1_rate"] - baseline["top1_rate"],
            "top3_rate": decision["top3_rate"] - baseline["top3_rate"],
            "recovered_revenue": decision["recovered_revenue"] - baseline["recovered_revenue"],
            "contacts_per_booking": decision["contacts_per_booking"] - baseline["contacts_per_booking"],
            "revenue_per_contact": decision["revenue_per_contact"] - baseline["revenue_per_contact"],
        },
        "winner": winner,
    }

    conn = core.connect()
    try:
        benchmark_id = "founder_sim_benchmark_" + uuid.uuid4().hex
        core.db_execute(
            conn,
            """INSERT INTO founder_sim_policy_benchmarks(
                id,shop_id,cycles,baseline_json,decision_json,winner,created_at
            ) VALUES (?,?,?,?,?,?,?)""",
            (
                benchmark_id,
                shop_id,
                cycles,
                json.dumps(baseline),
                json.dumps(decision),
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
        row = core.db_fetchone(
            conn,
            "SELECT * FROM founder_sim_policy_benchmarks WHERE shop_id=? ORDER BY created_at DESC LIMIT 1",
            (shop_id,),
        )
        conn.rollback()
        if not row:
            return None
        data = dict(row)
        data["baseline"] = json.loads(data.pop("baseline_json"))
        data["decision"] = json.loads(data.pop("decision_json"))
        return data
    finally:
        conn.close()
