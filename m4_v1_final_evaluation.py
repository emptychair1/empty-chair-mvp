"""Final untouched M4 V1 evaluation.

This module DOES NOT TRAIN. It loads the most recent completed M4 V1 model,
then evaluates it against the hand-built baseline on a disjoint synthetic world
using the already-frozen simulator. Pass criteria are fixed in code before the
first final evaluation is observed.
"""
from __future__ import annotations

import json
import uuid

import app as core
import m4_v1_fast_train as trainer
from founder_simulation_safety import load_and_assert_founder_simulation_target

VERSION = "m4-v1-final-eval-1"
EVAL_ROWS = 250_000
START_SHOP = 40_000
EVAL_SEED = 71001

# Frozen before first evaluation result.
MIN_OVERALL_TOP1_LIFT = 0.07
MIN_OVERALL_TOP3_LIFT = 0.04
MIN_CONTACT_EFFICIENCY_GAIN = 0.03
MIN_REVENUE_PER_CONTACT_GAIN = 0.03
MAX_FILL_DEGRADATION = 0.002


def ensure_table(conn):
    core.db_execute(conn, """
        CREATE TABLE IF NOT EXISTS m4_v1_final_evaluations (
            id TEXT PRIMARY KEY,
            shop_id TEXT NOT NULL,
            training_run_id TEXT NOT NULL,
            version TEXT NOT NULL,
            result_json TEXT NOT NULL,
            passed INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL
        )
    """)


def _latest_training(conn, shop_id):
    trainer.ensure_table(conn)
    row = core.db_fetchone(
        conn,
        "SELECT * FROM m4_v1_training_runs WHERE shop_id=? ORDER BY created_at DESC LIMIT 1",
        (shop_id,),
    )
    if not row:
        raise RuntimeError("No completed M4 V1 training run exists to evaluate.")
    result = json.loads(row["result_json"])
    return str(row["id"]), result


def _weights_from_result(result):
    weight_map = ((result.get("model") or {}).get("weights") or {})
    missing = [name for name in trainer.FEATURE_NAMES if name not in weight_map]
    if missing:
        raise RuntimeError("Stored M4 V1 model is missing weights: " + ", ".join(missing))
    return [float(weight_map[name]) for name in trainer.FEATURE_NAMES]


def _evaluate(customers, openings, weights):
    groups = {}
    for row in trainer._row_stream(
        customers,
        openings,
        START_SHOP,
        EVAL_ROWS,
        EVAL_SEED,
    ):
        key = (row["shop_id"], row["opening_id"])
        row["trained_probability"] = trainer._clamp(
            trainer._sigmoid(trainer._dot(weights, row["features"]))
        )
        groups.setdefault(key, []).append(row)

    result = {}
    for policy in ("baseline", "trained"):
        totals = {
            "openings": 0,
            "top1_bookings": 0,
            "top3_bookings": 0,
            "bookings": 0,
            "contacts": 0,
            "recovered_revenue": 0.0,
        }
        by_regime = {
            name: {
                "openings": 0,
                "top1_bookings": 0,
                "top3_bookings": 0,
                "bookings": 0,
                "contacts": 0,
                "recovered_revenue": 0.0,
            }
            for name in trainer.REGIME_ORDER
        }
        for rows in groups.values():
            score_key = "baseline_probability" if policy == "baseline" else "trained_probability"
            ordered = sorted(rows, key=lambda item: item[score_key], reverse=True)
            regime = ordered[0]["regime"]
            booked_index = next(
                (i for i, item in enumerate(ordered) if item["accepted"]),
                None,
            )
            for bucket in (totals, by_regime[regime]):
                bucket["openings"] += 1
                if ordered[0]["accepted"]:
                    bucket["top1_bookings"] += 1
                if any(item["accepted"] for item in ordered[:3]):
                    bucket["top3_bookings"] += 1
                if booked_index is None:
                    bucket["contacts"] += len(ordered)
                else:
                    bucket["bookings"] += 1
                    bucket["contacts"] += booked_index + 1
                    bucket["recovered_revenue"] += ordered[booked_index]["price"]

        result[policy] = trainer._finalize_metrics(totals)
        result[policy]["regimes"] = {
            name: trainer._finalize_metrics(metrics)
            for name, metrics in by_regime.items()
        }
    return result


def _gates(baseline, trained):
    top1_lift = trained["top1_rate"] - baseline["top1_rate"]
    top3_lift = trained["top3_rate"] - baseline["top3_rate"]
    contact_gain = 1.0 - (
        trained["contacts_per_booking"] / max(1e-9, baseline["contacts_per_booking"])
    )
    revenue_gain = (
        trained["revenue_per_contact"] / max(1e-9, baseline["revenue_per_contact"])
    ) - 1.0

    gates = {
        "easy_top1_beats_baseline": (
            trained["regimes"]["easy"]["top1_rate"]
            > baseline["regimes"]["easy"]["top1_rate"]
        ),
        "normal_top1_beats_baseline": (
            trained["regimes"]["normal"]["top1_rate"]
            > baseline["regimes"]["normal"]["top1_rate"]
        ),
        "hard_top1_beats_baseline": (
            trained["regimes"]["hard"]["top1_rate"]
            > baseline["regimes"]["hard"]["top1_rate"]
        ),
        "overall_top1_lift_at_least_7pts": top1_lift >= MIN_OVERALL_TOP1_LIFT,
        "overall_top3_lift_at_least_4pts": top3_lift >= MIN_OVERALL_TOP3_LIFT,
        "fill_not_degraded": (
            trained["fill_rate"] >= baseline["fill_rate"] - MAX_FILL_DEGRADATION
        ),
        "contacts_per_booking_improves_at_least_3pct": (
            contact_gain >= MIN_CONTACT_EFFICIENCY_GAIN
        ),
        "revenue_per_contact_improves_at_least_3pct": (
            revenue_gain >= MIN_REVENUE_PER_CONTACT_GAIN
        ),
    }
    diagnostics = {
        "top1_lift": top1_lift,
        "top3_lift": top3_lift,
        "contact_efficiency_gain": contact_gain,
        "revenue_per_contact_gain": revenue_gain,
        "fill_delta": trained["fill_rate"] - baseline["fill_rate"],
    }
    return gates, diagnostics


def run_final_evaluation(shop_id):
    conn = core.connect()
    try:
        load_and_assert_founder_simulation_target(conn, core.db_fetchone, shop_id)
        ensure_table(conn)
        training_run_id, training_result = _latest_training(conn, shop_id)
        conn.commit()
    finally:
        conn.close()

    weights = _weights_from_result(training_result)
    customers, openings = trainer._templates(shop_id)
    evaluation = _evaluate(customers, openings, weights)
    baseline = evaluation["baseline"]
    trained = evaluation["trained"]
    gates, diagnostics = _gates(baseline, trained)
    passed = all(gates.values())

    result = {
        "version": VERSION,
        "training_run_id": training_run_id,
        "training_model_version": training_result.get("version"),
        "simulator": trainer.frozen.VERSION,
        "untouched_evaluation": {
            "rows": EVAL_ROWS,
            "openings": EVAL_ROWS // trainer.CANDIDATES_PER_OPENING,
            "candidates_per_opening": trainer.CANDIDATES_PER_OPENING,
            "synthetic_shop_start": START_SHOP,
            "seed": EVAL_SEED,
            "retraining_performed": False,
            "weights_changed": False,
        },
        "baseline": baseline,
        "trained": trained,
        "lift": diagnostics,
        "acceptance_gates": gates,
        "status": "PASS" if passed else "FAIL",
        "decision": (
            "FREEZE_M4_V1_SYNTHETIC_LEARNING_SUCCESS"
            if passed
            else "SHIP_SAFE_BASELINE_AND_MOVE_TO_REAL_WORLD_LEARNING"
        ),
    }

    conn = core.connect()
    try:
        load_and_assert_founder_simulation_target(conn, core.db_fetchone, shop_id)
        ensure_table(conn)
        conn.commit()
        eval_id = "m4_v1_final_eval_" + uuid.uuid4().hex
        core.db_execute(
            conn,
            "INSERT INTO m4_v1_final_evaluations(id,shop_id,training_run_id,version,result_json,passed,created_at) VALUES (?,?,?,?,?,?,?)",
            (
                eval_id,
                shop_id,
                training_run_id,
                VERSION,
                json.dumps(result),
                1 if passed else 0,
                core.now_iso(),
            ),
        )
        conn.commit()
        result["evaluation_id"] = eval_id
        return result
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
