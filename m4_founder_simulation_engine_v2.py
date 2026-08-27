"""Cycle-continuing wrapper for the founder M4 simulation engine.

The original engine is intentionally left intact. This wrapper makes repeated
simulation runs append new cycle numbers instead of restarting at cycle 1,
which prevents duplicate primary keys in outcomes, recommendations, and metrics.
"""

import app as core
import m4_founder_simulation_engine as legacy


# Re-export the existing public helpers used elsewhere.
ensure_tables = legacy.ensure_tables
latest_recommendation = legacy.latest_recommendation
run_cycle = legacy.run_cycle
learned_probability = legacy.learned_probability
hidden_probability = legacy.hidden_probability


def _next_cycle_number(shop_id):
    conn = core.connect()
    try:
        legacy.ensure_tables(conn)
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


def run_simulation(shop_id, cycles=30, candidates_per_opening=10):
    cycles = max(1, min(int(cycles), 365))
    start_cycle = _next_cycle_number(shop_id)
    end_cycle = start_cycle + cycles - 1

    results = [
        legacy.run_cycle(
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
