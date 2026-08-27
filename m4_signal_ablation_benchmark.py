"""M4 signal-ablation benchmark.

Measures the incremental value of exposing previously hidden practical/customer
signals to M4 in the same V3 adversarial world. Outcomes remain identical across
policies; only ranking information changes.

This is intentionally a measurement harness, not a production ranker. It tells
us which inputs are worth collecting/enriching before we generate a much larger
synthetic training corpus.
"""
from __future__ import annotations

import json
import math
import uuid

import app as core
import m4_runtime
import m4_stress_benchmark_v3 as v3
from founder_simulation_safety import load_and_assert_founder_simulation_target

SIGNALS = (
    "distance",
    "budget",
    "short_notice",
    "artist_affinity",
    "fatigue",
)


def ensure_table(conn):
    core.db_execute(conn, """
        CREATE TABLE IF NOT EXISTS founder_sim_v3_signal_ablation_benchmarks (
            id TEXT PRIMARY KEY,
            shop_id TEXT NOT NULL,
            cycles INTEGER NOT NULL,
            result_json TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
    """)


def _observed_multiplier(shop_id, customer, opening, cycle, signal):
    """Return a realistic/noisy observable proxy for one latent V3 factor."""
    env = v3._latent_environment(shop_id, opening, customer, cycle)
    cid = customer["id"]
    oid = opening["id"]

    if signal == "distance":
        # Geocoding/drive-time is highly observable but still imperfect.
        true = env["distance_multiplier"]
        noise = 0.94 + 0.12 * v3._stable(cid, oid, "ablation_distance_noise")
        return max(0.20, min(1.05, true * noise))

    if signal == "budget":
        # Budget inferred from spend history/zero-party data is noisier.
        true = env["budget_multiplier"]
        noise = 0.82 + 0.36 * v3._stable(cid, "ablation_budget_noise")
        return max(0.12, min(1.08, true * noise))

    if signal == "short_notice":
        # Explicit availability or concierge answer can be very strong.
        true = env["short_notice_multiplier"]
        noise = 0.90 + 0.20 * v3._stable(cid, cycle // 6, "ablation_short_notice_noise")
        return max(0.30, min(1.22, true * noise))

    if signal == "artist_affinity":
        # Historical artist loyalty / visual preference evidence.
        true = env["artist_multiplier"]
        noise = 0.86 + 0.28 * v3._stable(cid, opening.get("artist_id"), "ablation_artist_noise")
        return max(0.55, min(1.45, true * noise))

    if signal == "fatigue":
        # Directly derived from prior offer-response history, fairly observable.
        true = env["fatigue_multiplier"]
        noise = 0.94 + 0.12 * v3._stable(cid, cycle // 5, "ablation_fatigue_noise")
        return max(0.40, min(1.05, true * noise))

    return 1.0


def _order(shop_id, customers, opening, cycle, signals):
    ranked = m4_runtime.rank(customers, opening, len(customers))
    by_id = {c["id"]: c for c in customers}
    scored = []
    for row in ranked:
        customer = by_id[row["customer_id"]]
        p = max(0.001, float(row.get("booking_probability") or 0.0))
        multiplier = 1.0
        for signal in signals:
            multiplier *= _observed_multiplier(shop_id, customer, opening, cycle, signal)
        # Work in log space so stacked signals combine smoothly and do not let a
        # single multiplier dominate unrealistically.
        score = math.log(p) + 0.72 * math.log(max(0.05, multiplier))
        scored.append((score, customer))
    scored.sort(key=lambda item: item[0], reverse=True)
    return [customer for _, customer in scored]


def _evaluate(shop_id, cycles, customers, openings, seed_offset, signals):
    totals = {
        "cycles": cycles,
        "openings": 0,
        "top1_bookings": 0,
        "top3_bookings": 0,
        "bookings": 0,
        "unfilled_openings": 0,
        "contacts": 0,
        "recovered_revenue": 0.0,
    }
    for index in range(1, cycles + 1):
        cycle = seed_offset + index
        for opening in openings:
            totals["openings"] += 1
            ordered = _order(shop_id, customers, opening, cycle, signals)
            accepted_flags = []
            for customer in ordered:
                truth, _ = v3.hidden_probability_v3(shop_id, customer, opening, cycle)
                accepted = v3._stable(
                    shop_id,
                    opening["id"],
                    customer["id"],
                    cycle,
                    "v3_accept",
                ) < truth
                accepted_flags.append(bool(accepted))

            if accepted_flags and accepted_flags[0]:
                totals["top1_bookings"] += 1
            if any(accepted_flags[:3]):
                totals["top3_bookings"] += 1

            booked_index = next((i for i, yes in enumerate(accepted_flags) if yes), None)
            if booked_index is None:
                totals["unfilled_openings"] += 1
                totals["contacts"] += len(ordered)
            else:
                totals["bookings"] += 1
                totals["contacts"] += booked_index + 1
                totals["recovered_revenue"] += float(opening.get("price") or 0.0)

    openings_n = max(1, totals["openings"])
    bookings_n = max(1, totals["bookings"])
    contacts_n = max(1, totals["contacts"])
    totals["top1_rate"] = totals["top1_bookings"] / openings_n
    totals["top3_rate"] = totals["top3_bookings"] / openings_n
    totals["booking_rate"] = totals["bookings"] / openings_n
    totals["unfilled_rate"] = totals["unfilled_openings"] / openings_n
    totals["contacts_per_booking"] = totals["contacts"] / bookings_n
    totals["revenue_per_contact"] = totals["recovered_revenue"] / contacts_n
    return totals


def _lift(metrics, baseline):
    return {
        "top1_rate": metrics["top1_rate"] - baseline["top1_rate"],
        "top3_rate": metrics["top3_rate"] - baseline["top3_rate"],
        "booking_rate": metrics["booking_rate"] - baseline["booking_rate"],
        "contacts_per_booking": metrics["contacts_per_booking"] - baseline["contacts_per_booking"],
        "revenue_per_contact": metrics["revenue_per_contact"] - baseline["revenue_per_contact"],
    }


def run_benchmark(shop_id, cycles=250):
    cycles = max(50, min(int(cycles), 500))
    conn = core.connect()
    try:
        load_and_assert_founder_simulation_target(conn, core.db_fetchone, shop_id)
        ensure_table(conn)
        v3.ensure_tables(conn)
        conn.commit()
        customers, openings, _, _ = v3._load_state(conn, shop_id)
        if not customers or not openings:
            raise RuntimeError("Crybaby founder simulation must be seeded before signal ablation.")
        row = core.db_fetchone(
            conn,
            "SELECT MAX(cycle) AS max_cycle FROM founder_sim_metrics WHERE shop_id=?",
            (shop_id,),
        )
        conn.rollback()
    finally:
        conn.close()

    seed_offset = int(row["max_cycle"] or 0) + 40000 if row else 40000
    baseline = _evaluate(shop_id, cycles, customers, openings, seed_offset, ())

    individual = {}
    for signal in SIGNALS:
        metrics = _evaluate(shop_id, cycles, customers, openings, seed_offset, (signal,))
        individual[signal] = {"metrics": metrics, "lift": _lift(metrics, baseline)}

    cumulative = {}
    active = []
    # Order by measured individual top-1 lift, not by a hand-picked sequence.
    ranked_signals = sorted(
        SIGNALS,
        key=lambda s: individual[s]["lift"]["top1_rate"],
        reverse=True,
    )
    for signal in ranked_signals:
        active.append(signal)
        metrics = _evaluate(shop_id, cycles, customers, openings, seed_offset, tuple(active))
        cumulative["+".join(active)] = {
            "signals": list(active),
            "metrics": metrics,
            "lift": _lift(metrics, baseline),
        }

    best_single = max(SIGNALS, key=lambda s: individual[s]["lift"]["top1_rate"])
    best_combo_name, best_combo = max(
        cumulative.items(),
        key=lambda item: (
            item[1]["metrics"]["top1_rate"],
            item[1]["metrics"]["revenue_per_contact"],
        ),
    )
    result = {
        "environment": {
            "version": "v3-signal-ablation",
            "purpose": "measure incremental information value before large-scale synthetic training",
            "signals": list(SIGNALS),
            "note": "signals are noisy observable proxies, not perfect latent truth",
        },
        "cycles": cycles,
        "baseline": baseline,
        "individual": individual,
        "cumulative": cumulative,
        "ranked_signals_by_top1_lift": ranked_signals,
        "best_single_signal": best_single,
        "best_combination": best_combo_name,
        "best_combination_metrics": best_combo["metrics"],
        "best_combination_lift": best_combo["lift"],
    }

    conn = core.connect()
    try:
        ensure_table(conn)
        conn.commit()
        benchmark_id = "founder_sim_v3_signal_ablation_" + uuid.uuid4().hex
        core.db_execute(
            conn,
            "INSERT INTO founder_sim_v3_signal_ablation_benchmarks(id,shop_id,cycles,result_json,created_at) VALUES (?,?,?,?,?)",
            (benchmark_id, shop_id, cycles, json.dumps(result), core.now_iso()),
        )
        conn.commit()
        result["benchmark_id"] = benchmark_id
        return result
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
