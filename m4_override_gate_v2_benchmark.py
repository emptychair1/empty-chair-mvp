"""Precision-gated top-1 override benchmark for M4.

Goal: materially improve top-1 without sacrificing the hybrid's shortlist and
contact-efficiency gains. Baseline #1 is protected by default. Historical
simulation outcomes train a direct override classifier: among baseline top-five
candidates, learn when replacing #1 has positive expected top-1 gain.

The gate is tuned on held-out historical cycles and evaluated only on the future
V3 adversarial world. Override diagnostics make the result falsifiable.
"""
from __future__ import annotations

import json
import math
import uuid

import app as core
import m4_runtime
import m4_stress_benchmark_v3 as v3
import m4_top1_specialist_benchmark as previous
from founder_simulation_safety import load_and_assert_founder_simulation_target


def ensure_table(conn):
    core.db_execute(conn, """
        CREATE TABLE IF NOT EXISTS founder_sim_v3_override_v2_benchmarks (
            id TEXT PRIMARY KEY, shop_id TEXT NOT NULL, cycles INTEGER NOT NULL,
            baseline_json TEXT NOT NULL, hybrid_json TEXT NOT NULL,
            gate_json TEXT NOT NULL, training_json TEXT NOT NULL,
            environment_json TEXT NOT NULL, winner TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
    """)


def _clamp(x, lo=0.001, hi=0.999):
    return max(lo, min(hi, float(x)))


def _logit(p):
    p = _clamp(p)
    return math.log(p / (1.0 - p))


def _sigmoid(x):
    return 1.0 / (1.0 + math.exp(-max(-20.0, min(20.0, float(x)))))


def _context_stats(context, customer_id, opening):
    global_rate = context["global_rate"]
    customer_rate = previous._rate(context["customer"], customer_id, global_rate, 12.0)
    artist_key = (customer_id, str(opening.get("artist_id") or ""))
    style_key = (customer_id, str(opening.get("style") or "").strip().lower())
    artist_rate = previous._rate(context["artist"], artist_key, customer_rate, 7.0)
    style_rate = previous._rate(context["style"], style_key, customer_rate, 7.0)
    artist_attempts = context["artist"].get(artist_key, (0, 0))[1]
    style_attempts = context["style"].get(style_key, (0, 0))[1]
    contextual = 0.58 * artist_rate + 0.42 * style_rate
    evidence = min(1.0, (artist_attempts + style_attempts) / 24.0)
    return contextual, evidence


def _candidate_signal(row, opening, context):
    baseline_p = float(row.get("baseline_probability") or row.get("booking_probability") or 0.0)
    context_p, evidence = _context_stats(context, row["customer_id"], opening)
    # Shrink context toward baseline unless repeated artist/style evidence exists.
    adjusted = _sigmoid(_logit(baseline_p) + evidence * (_logit(context_p) - _logit(context["global_rate"])))
    return adjusted, evidence


def _choose_from_history(top, opening, context, min_gain, min_evidence):
    incumbent = top[0]
    incumbent_signal, incumbent_evidence = _candidate_signal(incumbent, opening, context)
    best = incumbent
    best_signal = incumbent_signal
    best_evidence = incumbent_evidence
    for row in top[1:5]:
        signal, evidence = _candidate_signal(row, opening, context)
        if signal > best_signal:
            best, best_signal, best_evidence = row, signal, evidence
    gain = best_signal - incumbent_signal
    override = (
        best["customer_id"] != incumbent["customer_id"]
        and gain >= min_gain
        and best_evidence >= min_evidence
    )
    return (best if override else incumbent), override, gain, best_evidence


def _tune_gate(context, tune_rows, openings_by_id):
    # Precision-first grid. We explicitly reject aggressive gates even if their
    # raw accuracy looks attractive on one tuning slice.
    gains = (0.025, 0.04, 0.06, 0.08, 0.10, 0.14, 0.18)
    evidences = (0.20, 0.35, 0.50, 0.65, 0.80)
    groups = previous._groups(tune_rows)
    best = None
    for min_gain in gains:
        for min_evidence in evidences:
            baseline_correct = 0
            chosen_correct = 0
            attempts = wins = losses = neutral = 0
            evaluated = 0
            for candidates in groups:
                top = candidates[:5]
                if len(top) < 2:
                    continue
                opening = openings_by_id.get(top[0]["opening_id"])
                if not opening:
                    continue
                incumbent = top[0]
                chosen, override, _, _ = _choose_from_history(top, opening, context, min_gain, min_evidence)
                base_yes = int(incumbent.get("accepted") or 0)
                chosen_yes = int(chosen.get("accepted") or 0)
                baseline_correct += base_yes
                chosen_correct += chosen_yes
                evaluated += 1
                if override:
                    attempts += 1
                    if chosen_yes and not base_yes:
                        wins += 1
                    elif base_yes and not chosen_yes:
                        losses += 1
                    else:
                        neutral += 1
            net_gain = wins - losses
            precision = wins / max(1, wins + losses)
            rate = attempts / max(1, evaluated)
            accuracy = chosen_correct / max(1, evaluated)
            baseline_accuracy = baseline_correct / max(1, evaluated)
            candidate = {
                "min_gain": min_gain,
                "min_evidence": min_evidence,
                "tune_top1_rate": accuracy,
                "tune_baseline_top1_rate": baseline_accuracy,
                "override_attempts": attempts,
                "override_wins": wins,
                "override_losses": losses,
                "override_neutral": neutral,
                "override_precision": precision,
                "override_rate": rate,
                "net_top1_gain": net_gain,
                "evaluated_openings": evaluated,
            }
            # Require at least a small sample and >60% decisive override precision.
            eligible = attempts >= 8 and precision >= 0.60 and net_gain > 0
            candidate["eligible"] = eligible
            score = (1 if eligible else 0, net_gain if eligible else -999, precision, -rate)
            if best is None or score > best[0]:
                best = (score, candidate)
    chosen = best[1] if best else None
    if not chosen or not chosen.get("eligible"):
        # Fail closed: no evidence that overriding #1 helps.
        chosen = {
            "min_gain": 1.0, "min_evidence": 1.0,
            "tune_top1_rate": 0.0, "tune_baseline_top1_rate": 0.0,
            "override_attempts": 0, "override_wins": 0,
            "override_losses": 0, "override_neutral": 0,
            "override_precision": 0.0, "override_rate": 0.0,
            "net_top1_gain": 0, "evaluated_openings": len(groups),
            "eligible": False, "fail_closed": True,
        }
    return chosen


def _train(conn, shop_id, openings):
    rows = previous._history(conn, shop_id)
    cycles = sorted({int(row["cycle"]) for row in rows})
    if len(cycles) < 20:
        raise RuntimeError("Not enough founder simulation history for override gate V2.")
    split = max(1, int(len(cycles) * 0.70))
    train_cycles = set(cycles[:split])
    tune_cycles = set(cycles[split:])
    train_rows = [r for r in rows if int(r["cycle"]) in train_cycles]
    tune_rows = [r for r in rows if int(r["cycle"]) in tune_cycles]
    context = previous._build_context(train_rows)
    tuned = _tune_gate(context, tune_rows, {o["id"]: o for o in openings})
    return context, {
        "history_cycles": len(cycles), "train_cycles": len(train_cycles),
        "tune_cycles": len(tune_cycles), "train_rows": len(train_rows),
        "tune_rows": len(tune_rows), **tuned,
    }


def _gate_order(customers, opening, context, tuned):
    ranked = m4_runtime.rank(customers, opening, len(customers))
    by_id = {c["id"]: c for c in customers}
    baseline = [by_id[r["customer_id"]] for r in ranked]
    if len(ranked) < 2:
        return baseline, False

    # Start from the proven hybrid behavior for positions 2-5, but lock #1.
    incumbent_row = ranked[0]
    incumbent = baseline[0]
    rest_pairs = list(zip(ranked[1:5], baseline[1:5]))
    rest_pairs.sort(
        key=lambda pair: _candidate_signal(pair[0], opening, context)[0],
        reverse=True,
    )
    ordered_top = [incumbent] + [c for _, c in rest_pairs]

    incumbent_signal, _ = _candidate_signal(incumbent_row, opening, context)
    contender_row = incumbent_row
    contender = incumbent
    contender_signal = incumbent_signal
    contender_evidence = 0.0
    for row, customer in zip(ranked[1:5], baseline[1:5]):
        signal, evidence = _candidate_signal(row, opening, context)
        if signal > contender_signal:
            contender_row, contender = row, customer
            contender_signal, contender_evidence = signal, evidence

    override = (
        contender["id"] != incumbent["id"]
        and contender_signal - incumbent_signal >= float(tuned["min_gain"])
        and contender_evidence >= float(tuned["min_evidence"])
    )
    if override:
        ordered_top = [contender] + [c for c in ordered_top if c["id"] != contender["id"]]
    return ordered_top + baseline[5:], override


def _evaluate(shop_id, cycles, customers, openings, context, tuned, seed_offset):
    totals = {
        "cycles": cycles, "openings": 0, "top1_bookings": 0,
        "top3_bookings": 0, "bookings": 0, "unfilled_openings": 0,
        "contacts": 0, "recovered_revenue": 0.0,
        "weak_demand_openings": 0, "very_weak_demand_openings": 0,
        "cold_start_contacts": 0, "budget_blocked_contacts": 0,
        "distance_blocked_contacts": 0,
        "override_opportunities": 0, "override_attempts": 0,
        "override_wins": 0, "override_losses": 0, "override_neutral": 0,
    }
    for index in range(1, cycles + 1):
        cycle = seed_offset + index
        for opening in openings:
            totals["openings"] += 1
            baseline_order = v3._baseline_order(customers, opening)
            ordered, override = _gate_order(customers, opening, context, tuned)
            if len(baseline_order) > 1:
                totals["override_opportunities"] += 1
            baseline_first = baseline_order[0]["id"] if baseline_order else None
            chosen_first = ordered[0]["id"] if ordered else None
            accepted_flags = []
            environments = []
            acceptance_by_id = {}
            for customer in ordered:
                truth, env = v3.hidden_probability_v3(shop_id, customer, opening, cycle)
                accepted = v3._stable(shop_id, opening["id"], customer["id"], cycle, "v3_accept") < truth
                accepted_flags.append(bool(accepted)); environments.append(env)
                acceptance_by_id[customer["id"]] = bool(accepted)
            if override:
                totals["override_attempts"] += 1
                base_yes = acceptance_by_id.get(baseline_first, False)
                chosen_yes = acceptance_by_id.get(chosen_first, False)
                if chosen_yes and not base_yes: totals["override_wins"] += 1
                elif base_yes and not chosen_yes: totals["override_losses"] += 1
                else: totals["override_neutral"] += 1
            if environments:
                regime = environments[0]["demand_regime"]
                if regime == "weak": totals["weak_demand_openings"] += 1
                elif regime == "very_weak": totals["very_weak_demand_openings"] += 1
            if accepted_flags and accepted_flags[0]: totals["top1_bookings"] += 1
            if any(accepted_flags[:3]): totals["top3_bookings"] += 1
            booked_index = next((i for i, yes in enumerate(accepted_flags) if yes), None)
            if booked_index is None:
                totals["unfilled_openings"] += 1; totals["contacts"] += len(ordered)
                contact_range = range(len(ordered))
            else:
                totals["bookings"] += 1; totals["contacts"] += booked_index + 1
                totals["recovered_revenue"] += float(opening.get("price") or 0.0)
                contact_range = range(booked_index + 1)
            for position in contact_range:
                env = environments[position]
                if env["cold_start"]: totals["cold_start_contacts"] += 1
                if env["budget_multiplier"] <= 0.38: totals["budget_blocked_contacts"] += 1
                if env["distance_multiplier"] <= 0.45: totals["distance_blocked_contacts"] += 1
    n_openings = max(1, totals["openings"]); n_bookings = max(1, totals["bookings"]); n_contacts = max(1, totals["contacts"])
    totals["top1_rate"] = totals["top1_bookings"] / n_openings
    totals["top3_rate"] = totals["top3_bookings"] / n_openings
    totals["booking_rate"] = totals["bookings"] / n_openings
    totals["unfilled_rate"] = totals["unfilled_openings"] / n_openings
    totals["contacts_per_booking"] = totals["contacts"] / n_bookings
    totals["revenue_per_contact"] = totals["recovered_revenue"] / n_contacts
    decisive = totals["override_wins"] + totals["override_losses"]
    totals["override_precision"] = totals["override_wins"] / max(1, decisive)
    totals["override_rate"] = totals["override_attempts"] / n_openings
    totals["net_top1_gain"] = totals["override_wins"] - totals["override_losses"]
    return totals


def run_benchmark(shop_id, cycles=250):
    cycles = max(50, min(int(cycles), 500))
    conn = core.connect()
    try:
        load_and_assert_founder_simulation_target(conn, core.db_fetchone, shop_id)
        v3.ensure_tables(conn); ensure_table(conn); conn.commit()
        customers, openings, learning, pairwise = v3._load_state(conn, shop_id)
        if not customers or not openings:
            raise RuntimeError("Crybaby founder simulation must be seeded before benchmarking.")
        context, training = _train(conn, shop_id, openings)
        row = core.db_fetchone(conn, "SELECT MAX(cycle) AS max_cycle FROM founder_sim_metrics WHERE shop_id=?", (shop_id,))
        conn.rollback()
    finally:
        conn.close()
    seed_offset = int(row["max_cycle"] or 0) + 30000 if row else 30000
    baseline = v3._evaluate(shop_id, cycles, "baseline", customers, openings, learning, pairwise, seed_offset)
    hybrid = v3._evaluate(shop_id, cycles, "hybrid", customers, openings, learning, pairwise, seed_offset)
    gate = _evaluate(shop_id, cycles, customers, openings, context, training, seed_offset)
    lift = v3._lift(gate, baseline)
    winner = "override_gate_v2" if gate["top1_rate"] > baseline["top1_rate"] and gate["revenue_per_contact"] >= baseline["revenue_per_contact"] and gate["contacts_per_booking"] <= baseline["contacts_per_booking"] else "baseline"
    environment = {
        "version": "v3-adversarial-override-gate-v2",
        "goal": "positive net top1 overrides while preserving hybrid shortlist efficiency",
        "features": ["precision_gated_overrides", "artist_style_context", "evidence_shrinkage", "fail_closed_gate", "override_diagnostics"],
    }
    result = {
        "environment": environment, "cycles_per_policy": cycles,
        "override_training": training, "baseline": baseline, "hybrid": hybrid,
        "override_gate_v2": gate, "lift": {"override_gate_v2_vs_baseline": lift},
        "winner": winner,
    }
    conn = core.connect()
    try:
        ensure_table(conn); conn.commit()
        benchmark_id = "founder_sim_v3_override_v2_" + uuid.uuid4().hex
        core.db_execute(conn, """INSERT INTO founder_sim_v3_override_v2_benchmarks(id,shop_id,cycles,baseline_json,hybrid_json,gate_json,training_json,environment_json,winner,created_at) VALUES (?,?,?,?,?,?,?,?,?,?)""", (benchmark_id, shop_id, cycles, json.dumps(baseline), json.dumps(hybrid), json.dumps(gate), json.dumps(training), json.dumps(environment), winner, core.now_iso()))
        conn.commit(); result["benchmark_id"] = benchmark_id; return result
    except Exception:
        conn.rollback(); raise
    finally:
        conn.close()
