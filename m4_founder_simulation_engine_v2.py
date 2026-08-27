"""Fast, cycle-continuing founder M4 simulation engine.

This module preserves the existing synthetic behavior model but removes the
per-candidate database round trips from the hot path. A cycle loads the shop's
synthetic customers/openings/learning state once, computes outcomes in memory,
and persists outcomes + learning + recommendations in bulk.
"""

from __future__ import annotations

import json
import math

import app as core
import m4_runtime
import m4_founder_simulation_engine as legacy
from founder_simulation_safety import load_and_assert_founder_simulation_target

SIM_PREFIX = "founder_sim_"


def ensure_tables(conn):
    """Create founder simulation tables plus indexes needed for long runs."""
    legacy.ensure_tables(conn)
    core.db_execute(
        conn,
        "CREATE INDEX IF NOT EXISTS idx_founder_sim_metrics_shop_cycle ON founder_sim_metrics(shop_id, cycle)",
    )
    core.db_execute(
        conn,
        "CREATE INDEX IF NOT EXISTS idx_founder_sim_outcomes_shop_cycle ON founder_sim_outcomes(shop_id, cycle)",
    )
    core.db_execute(
        conn,
        "CREATE INDEX IF NOT EXISTS idx_founder_sim_outcomes_shop_customer ON founder_sim_outcomes(shop_id, customer_id)",
    )
    core.db_execute(
        conn,
        "CREATE INDEX IF NOT EXISTS idx_founder_sim_recommendations_shop_created ON founder_sim_recommendations(shop_id, created_at)",
    )
    core.db_execute(
        conn,
        "CREATE INDEX IF NOT EXISTS idx_founder_sim_learning_shop ON founder_sim_customer_learning(shop_id)",
    )


# Public helpers used by routes/dashboard.
latest_recommendation = legacy.latest_recommendation
hidden_probability = legacy.hidden_probability


def _bulk_insert(conn, table, columns, rows):
    """Insert many rows with one statement using the app's ? placeholder layer."""
    if not rows:
        return
    width = len(columns)
    marks = "(" + ",".join("?" for _ in range(width)) + ")"
    values_sql = ",".join(marks for _ in rows)
    params = []
    for row in rows:
        params.extend(row)
    core.db_execute(
        conn,
        f"INSERT INTO {table} ({','.join(columns)}) VALUES {values_sql}",
        tuple(params),
    )


def _bulk_upsert_learning(conn, rows):
    if not rows:
        return
    columns = (
        "shop_id",
        "customer_id",
        "attempts",
        "accepts",
        "declines",
        "ignores",
        "calibration_delta",
        "updated_at",
    )
    marks = "(" + ",".join("?" for _ in columns) + ")"
    values_sql = ",".join(marks for _ in rows)
    params = []
    for row in rows:
        params.extend(row)
    core.db_execute(
        conn,
        f"""
        INSERT INTO founder_sim_customer_learning ({','.join(columns)})
        VALUES {values_sql}
        ON CONFLICT(shop_id, customer_id) DO UPDATE SET
            attempts=excluded.attempts,
            accepts=excluded.accepts,
            declines=excluded.declines,
            ignores=excluded.ignores,
            calibration_delta=excluded.calibration_delta,
            updated_at=excluded.updated_at
        """,
        tuple(params),
    )


def _baseline_probability(customer, opening):
    return float(m4_runtime.score(customer, opening)["booking_probability"])


def _learned_probability_from_delta(customer, opening, delta):
    baseline = _baseline_probability(customer, opening)
    baseline = max(0.01, min(0.99, baseline))
    logit = math.log(baseline / max(1e-9, 1.0 - baseline))
    value = 1.0 / (1.0 + math.exp(-max(-20.0, min(20.0, logit + float(delta)))))
    return max(0.01, min(0.99, value))


def _next_cycle_number(shop_id):
    conn = core.connect()
    try:
        row = core.db_fetchone(
            conn,
            "SELECT MAX(cycle) AS max_cycle FROM founder_sim_metrics WHERE shop_id=?",
            (shop_id,),
        )
        conn.rollback()
        current = int(row["max_cycle"] or 0) if row else 0
        return current + 1
    finally:
        conn.close()


def run_cycle(shop_id, cycle, candidates_per_opening=10):
    """Run one optimized synthetic cycle without schema/DDL work."""
    conn = core.connect()
    try:
        if getattr(core, "USE_POSTGRES", False):
            core.db_execute(conn, "SET LOCAL statement_timeout = '15000ms'")
            core.db_execute(conn, "SET LOCAL lock_timeout = '2000ms'")

        load_and_assert_founder_simulation_target(conn, core.db_fetchone, shop_id)

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
        learning_rows = [
            dict(row)
            for row in core.db_fetchall(
                conn,
                "SELECT * FROM founder_sim_customer_learning WHERE shop_id=?",
                (shop_id,),
            )
        ]

        if not customers or not openings:
            raise RuntimeError("Crybaby founder simulation must be seeded before running a cycle.")

        learning = {
            row["customer_id"]: {
                "attempts": int(row.get("attempts") or 0),
                "accepts": int(row.get("accepts") or 0),
                "declines": int(row.get("declines") or 0),
                "ignores": int(row.get("ignores") or 0),
                "delta": float(row.get("calibration_delta") or 0.0),
            }
            for row in learning_rows
        }
        customer_by_id = {customer["id"]: customer for customer in customers}

        cycle_rows = []
        outcome_rows = []
        recommendation_rows = []
        total_accepts = 0
        voice_id = "Ss7hQAiJNG6a81OU5k51"
        now = core.now_iso()

        for opening in openings:
            ranked = m4_runtime.rank(customers, opening, candidates_per_opening)
            enriched = []

            for rank_index, pick in enumerate(ranked, start=1):
                customer = customer_by_id[pick["customer_id"]]
                state = learning.setdefault(
                    customer["id"],
                    {
                        "attempts": 0,
                        "accepts": 0,
                        "declines": 0,
                        "ignores": 0,
                        "delta": 0.0,
                    },
                )

                baseline = float(pick["booking_probability"])
                learned = _learned_probability_from_delta(customer, opening, state["delta"])
                truth = legacy.hidden_probability(customer, opening)
                accepted = int(
                    legacy._stable_unit(
                        shop_id,
                        opening["id"],
                        customer["id"],
                        cycle,
                        "accept",
                    )
                    < truth
                )

                if accepted:
                    outcome = "ACCEPTED"
                    total_accepts += 1
                else:
                    response_roll = legacy._stable_unit(
                        shop_id,
                        opening["id"],
                        customer["id"],
                        cycle,
                        "response",
                    )
                    outcome = "DECLINED" if response_roll < 0.58 else "IGNORED"

                cycle_rows.append(
                    {
                        "opening_id": opening["id"],
                        "customer_id": customer["id"],
                        "rank": rank_index,
                        "baseline_probability": baseline,
                        "learned_probability": learned,
                        "hidden_probability": truth,
                        "outcome": outcome,
                        "accepted": accepted,
                    }
                )
                enriched.append((pick, learned))

                outcome_rows.append(
                    (
                        f"{SIM_PREFIX}outcome_{cycle:04d}_{opening['id']}_{customer['id']}",
                        shop_id,
                        opening["id"],
                        customer["id"],
                        cycle,
                        rank_index,
                        baseline,
                        learned,
                        truth,
                        outcome,
                        accepted,
                        now,
                    )
                )

                state["attempts"] += 1
                if accepted:
                    state["accepts"] += 1
                    state["delta"] += 0.34 / math.sqrt(state["attempts"])
                elif outcome == "DECLINED":
                    state["declines"] += 1
                    state["delta"] -= 0.24 / math.sqrt(state["attempts"])
                else:
                    state["ignores"] += 1
                    state["delta"] -= 0.14 / math.sqrt(state["attempts"])
                state["delta"] = max(-1.75, min(1.75, state["delta"]))

            if enriched:
                recommendation_pick, recommendation_probability = max(
                    enriched,
                    key=lambda pair: pair[1],
                )
                evidence = {
                    "why": recommendation_pick.get("why") or [],
                    "expected_value": recommendation_pick.get("expected_value"),
                    "style_fit": recommendation_pick.get("style_fit"),
                    "budget_fit": recommendation_pick.get("budget_fit"),
                    "baseline_probability": recommendation_pick.get("booking_probability"),
                    "learned_probability": recommendation_probability,
                }
                recommendation_rows.append(
                    (
                        f"{SIM_PREFIX}recommendation_{cycle:04d}_{opening['id']}",
                        shop_id,
                        opening["id"],
                        recommendation_pick["customer_id"],
                        legacy._recommendation_text(
                            opening,
                            recommendation_pick,
                            recommendation_probability,
                        ),
                        recommendation_pick["confidence"],
                        json.dumps(evidence),
                        voice_id,
                        now,
                    )
                )

        learning_upserts = [
            (
                shop_id,
                customer_id,
                state["attempts"],
                state["accepts"],
                state["declines"],
                state["ignores"],
                state["delta"],
                now,
            )
            for customer_id, state in learning.items()
        ]

        _bulk_insert(
            conn,
            "founder_sim_outcomes",
            (
                "id",
                "shop_id",
                "opening_id",
                "customer_id",
                "cycle",
                "rank",
                "baseline_probability",
                "learned_probability",
                "hidden_probability",
                "outcome",
                "accepted",
                "created_at",
            ),
            outcome_rows,
        )
        _bulk_upsert_learning(conn, learning_upserts)
        _bulk_insert(
            conn,
            "founder_sim_recommendations",
            (
                "id",
                "shop_id",
                "opening_id",
                "customer_id",
                "recommendation_text",
                "confidence",
                "evidence_json",
                "voice_id",
                "created_at",
            ),
            recommendation_rows,
        )

        metrics = {
            "cycle": int(cycle),
            "offers": len(cycle_rows),
            "accepts": total_accepts,
            "baseline_brier": legacy._brier(cycle_rows, "baseline_probability"),
            "learned_brier": legacy._brier(cycle_rows, "learned_probability"),
            "baseline_top_pick_accuracy": legacy._top_pick_accuracy(
                cycle_rows,
                "baseline_probability",
            ),
            "learned_top_pick_accuracy": legacy._top_pick_accuracy(
                cycle_rows,
                "learned_probability",
            ),
        }
        core.db_execute(
            conn,
            """
            INSERT INTO founder_sim_metrics(
                id,shop_id,cycle,baseline_brier,learned_brier,
                baseline_top_pick_accuracy,learned_top_pick_accuracy,
                offers,accepts,created_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?)
            """,
            (
                f"{SIM_PREFIX}metrics_{cycle:04d}",
                shop_id,
                cycle,
                metrics["baseline_brier"],
                metrics["learned_brier"],
                metrics["baseline_top_pick_accuracy"],
                metrics["learned_top_pick_accuracy"],
                metrics["offers"],
                metrics["accepts"],
                now,
            ),
        )
        conn.commit()
        return metrics
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def run_simulation(shop_id, cycles=30, candidates_per_opening=10):
    cycles = max(1, min(int(cycles), 365))
    start_cycle = _next_cycle_number(shop_id)
    end_cycle = start_cycle + cycles - 1

    results = [
        run_cycle(
            shop_id,
            cycle=cycle_number,
            candidates_per_opening=candidates_per_opening,
        )
        for cycle_number in range(start_cycle, end_cycle + 1)
    ]

    first = results[0]
    last = results[-1]
    return {
        "cycles": cycles,
        "start_cycle": start_cycle,
        "end_cycle": end_cycle,
        "first": first,
        "last": last,
        "brier_improvement": first["learned_brier"] - last["learned_brier"],
        "top_pick_improvement": (
            last["learned_top_pick_accuracy"]
            - first["learned_top_pick_accuracy"]
        ),
    }
