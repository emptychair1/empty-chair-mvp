"""Research-calibrated simulated human judgment benchmark for M4 V1.

This is NOT a live-human experiment. It measures frozen trained M4 against a
bounded simulation of unaided human judgment using the same observable inputs.
The design is intentionally conservative: the strongest human profile receives
all visible signals and weights close to the trained/statistical solution, but
human profiles exhibit bounded cue under-weighting, attention limits, and
within-judge decision noise.

Calibration premise: meta-analyses of clinical/professional judgment versus
mechanical/statistical prediction generally find statistical combination equal
or superior and report average advantages around 10-13% in relevant bodies of
research (Grove et al., 2000; Aegisdottir et al., 2006). Those findings do NOT
establish tattoo-industry human accuracy; they justify modeling imperfect human
cue integration and decision noise rather than an omniscient comparator.
"""
from __future__ import annotations

import json
import math
import random
import statistics
import uuid

import app as core
import m4_v1_fast_train as trainer
from founder_simulation_safety import load_and_assert_founder_simulation_target

VERSION = "m4-v1-human-sim-benchmark-1"
ROWS = 100_000
START_SHOP = 60_000
SEED = 81001
JUDGES_PER_PROFILE = 150
OPENINGS_PER_JUDGE = 600

# Profiles are fixed before observing results. noise is score-space SD.
PROFILES = {
    "novice": {"skill": 0.48, "attention": 5, "noise": 0.72},
    "experienced": {"skill": 0.68, "attention": 8, "noise": 0.50},
    "expert": {"skill": 0.82, "attention": 11, "noise": 0.34},
    "near_optimal_human": {"skill": 0.92, "attention": 14, "noise": 0.22},
}

# Human-readable visible cues; excludes regime flags and learned interactions.
VISIBLE_FEATURES = (
    "baseline_logit",
    "distance_log",
    "budget_log",
    "short_notice_log",
    "artist_affinity_log",
    "fatigue_log",
    "price_ratio",
    "completed",
    "cancellations",
    "no_shows",
    "style_fit",
    "declared_artist_fit",
)


def ensure_table(conn):
    core.db_execute(conn, """
        CREATE TABLE IF NOT EXISTS m4_human_sim_benchmarks (
            id TEXT PRIMARY KEY,
            shop_id TEXT NOT NULL,
            version TEXT NOT NULL,
            result_json TEXT NOT NULL,
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
        raise RuntimeError("No completed M4 V1 training run exists.")
    result = json.loads(row["result_json"])
    return str(row["id"]), result


def _weights(result):
    mapping = ((result.get("model") or {}).get("weights") or {})
    return {name: float(mapping.get(name, 0.0)) for name in trainer.FEATURE_NAMES}


def _groups(customers, openings, trained_weights):
    groups = []
    current_key = None
    current = []
    for row in trainer._row_stream(customers, openings, START_SHOP, ROWS, SEED):
        key = (row["shop_id"], row["opening_id"])
        row["trained_probability"] = trainer._clamp(
            trainer._sigmoid(trainer._dot(
                [trained_weights[n] for n in trainer.FEATURE_NAMES], row["features"]
            ))
        )
        row["feature_map"] = dict(zip(trainer.FEATURE_NAMES, row["features"]))
        if current_key is not None and key != current_key:
            groups.append(current)
            current = []
        current_key = key
        current.append(row)
    if current:
        groups.append(current)
    return groups


def _m4_metrics(groups):
    top1 = top3 = 0
    for rows in groups:
        ordered = sorted(rows, key=lambda r: r["trained_probability"], reverse=True)
        top1 += int(bool(ordered[0]["accepted"]))
        top3 += int(any(r["accepted"] for r in ordered[:3]))
    n = max(1, len(groups))
    return {"openings": len(groups), "top1_rate": top1 / n, "top3_rate": top3 / n}


def _human_weights(optimal, profile, rng):
    # Stronger humans approach the statistical solution but remain unaided:
    # no regime features, no engineered interactions, and bounded cue distortion.
    skill = profile["skill"]
    candidates = []
    for name in VISIBLE_FEATURES:
        base = optimal.get(name, 0.0)
        distortion = rng.gauss(1.0, max(0.04, (1.0 - skill) * 0.34))
        weight = base * skill * distortion
        candidates.append((name, weight, abs(base)))
    candidates.sort(key=lambda item: item[2], reverse=True)
    attended = {name for name, _, _ in candidates[: profile["attention"]]}
    return {name: (weight if name in attended else 0.0) for name, weight, _ in candidates}


def _human_score(row, weights, profile, rng):
    fmap = row["feature_map"]
    score = sum(weights.get(name, 0.0) * float(fmap.get(name, 0.0)) for name in VISIBLE_FEATURES)
    # Stable person-level intuition plus trial-level inconsistency.
    return score + rng.gauss(0.0, profile["noise"])


def _judge_result(groups, profile_name, optimal, judge_index):
    profile = PROFILES[profile_name]
    rng = random.Random(SEED + 100_000 * list(PROFILES).index(profile_name) + judge_index * 997)
    weights = _human_weights(optimal, profile, rng)
    if len(groups) <= OPENINGS_PER_JUDGE:
        sampled = groups
    else:
        sampled = rng.sample(groups, OPENINGS_PER_JUDGE)
    top1 = top3 = 0
    for rows in sampled:
        ordered = sorted(rows, key=lambda r: _human_score(r, weights, profile, rng), reverse=True)
        top1 += int(bool(ordered[0]["accepted"]))
        top3 += int(any(r["accepted"] for r in ordered[:3]))
    n = max(1, len(sampled))
    return {"top1_rate": top1 / n, "top3_rate": top3 / n}


def _summary(values):
    vals = sorted(values)
    if not vals:
        return {}
    def pct(p):
        i = min(len(vals) - 1, max(0, round((len(vals) - 1) * p)))
        return vals[i]
    return {
        "mean": statistics.fmean(vals),
        "median": statistics.median(vals),
        "p10": pct(0.10),
        "p90": pct(0.90),
        "best": vals[-1],
    }


def run_benchmark(shop_id):
    conn = core.connect()
    try:
        load_and_assert_founder_simulation_target(conn, core.db_fetchone, shop_id)
        ensure_table(conn)
        training_run_id, training_result = _latest_training(conn, shop_id)
        conn.commit()
    finally:
        conn.close()

    optimal = _weights(training_result)
    customers, openings = trainer._templates(shop_id)
    groups = _groups(customers, openings, optimal)
    m4 = _m4_metrics(groups)

    profiles = {}
    all_top1 = []
    for name in PROFILES:
        results = [_judge_result(groups, name, optimal, j) for j in range(JUDGES_PER_PROFILE)]
        top1 = [r["top1_rate"] for r in results]
        top3 = [r["top3_rate"] for r in results]
        all_top1.extend(top1)
        profiles[name] = {
            "judges": JUDGES_PER_PROFILE,
            "openings_per_judge": min(OPENINGS_PER_JUDGE, len(groups)),
            "top1": _summary(top1),
            "top3": _summary(top3),
            "m4_beats_mean_top1": m4["top1_rate"] > statistics.fmean(top1),
            "m4_beats_best_observed_judge_top1": m4["top1_rate"] > max(top1),
        }

    percentile = sum(1 for x in all_top1 if x < m4["top1_rate"]) / max(1, len(all_top1))
    expert_mean = profiles["expert"]["top1"]["mean"]
    near_mean = profiles["near_optimal_human"]["top1"]["mean"]

    result = {
        "version": VERSION,
        "training_run_id": training_run_id,
        "simulator": trainer.frozen.VERSION,
        "design": {
            "rows": ROWS,
            "openings": len(groups),
            "candidates_per_opening": trainer.CANDIDATES_PER_OPENING,
            "human_profiles": list(PROFILES),
            "judges_per_profile": JUDGES_PER_PROFILE,
            "openings_per_judge": min(OPENINGS_PER_JUDGE, len(groups)),
            "same_observable_inputs": True,
            "live_humans_tested": False,
            "research_calibration": [
                "Grove et al. 2000 meta-analysis: mechanical prediction about 10% more accurate on average",
                "Aegisdottir et al. 2006 meta-analysis: stringent comparisons reported about 13% statistical advantage",
            ],
        },
        "m4": m4,
        "simulated_humans": profiles,
        "m4_percentile_all_simulated_judges_top1": percentile,
        "m4_vs_expert_mean_top1_points": m4["top1_rate"] - expert_mean,
        "m4_vs_near_optimal_human_mean_top1_points": m4["top1_rate"] - near_mean,
        "claim_gate": {
            "beats_experienced_mean": profiles["experienced"]["m4_beats_mean_top1"],
            "beats_expert_mean": profiles["expert"]["m4_beats_mean_top1"],
            "beats_near_optimal_human_mean": profiles["near_optimal_human"]["m4_beats_mean_top1"],
            "above_75th_percentile_all_simulated_humans": percentile >= 0.75,
        },
        "allowed_sales_claim": "In a research-calibrated simulation of human judgment, M4 outperformed the simulated human decision-maker." if (profiles["expert"]["m4_beats_mean_top1"] and percentile >= 0.75) else "M4 was tested against research-calibrated simulated human judgment; results did not clear the predeclared sales-claim gate.",
        "disclosure": "This benchmark uses simulated human decision-makers calibrated to published professional-judgment research. It is not evidence that M4 has outperformed real tattoo artists or shop owners; a live-human benchmark is required for that claim.",
    }

    conn = core.connect()
    try:
        load_and_assert_founder_simulation_target(conn, core.db_fetchone, shop_id)
        ensure_table(conn)
        benchmark_id = "m4_human_sim_" + uuid.uuid4().hex
        core.db_execute(conn, "INSERT INTO m4_human_sim_benchmarks(id,shop_id,version,result_json,created_at) VALUES (?,?,?,?,?)", (benchmark_id, shop_id, VERSION, json.dumps(result), core.now_iso()))
        conn.commit()
        result["benchmark_id"] = benchmark_id
        return result
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
