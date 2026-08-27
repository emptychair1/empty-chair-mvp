"""Closed-loop M4 simulation for the Crybaby founder sandbox.

The simulator uses the real M4 ranking function as its baseline, generates
repeatable synthetic customer outcomes from hidden behavior traits, records
those outcomes, and learns a shop-scoped calibration adjustment over time.
No delivery provider is called and no real customer is contacted.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass

import app as core
import m4_runtime
from founder_simulation_safety import load_and_assert_founder_simulation_target

SIM_PREFIX = "founder_sim_"


def _clamp(value, lo=0.01, hi=0.99):
    return max(lo, min(hi, float(value)))


def _sigmoid(value):
    value = max(-20.0, min(20.0, float(value)))
    return 1.0 / (1.0 + math.exp(-value))


def _stable_unit(*parts):
    raw = "|".join(str(part) for part in parts).encode("utf-8")
    digest = hashlib.sha256(raw).digest()
    return int.from_bytes(digest[:8], "big") / float(2**64 - 1)


def ensure_tables(conn):
    core.db_execute(conn, """
        CREATE TABLE IF NOT EXISTS founder_sim_customer_learning (
            shop_id TEXT NOT NULL,
            customer_id TEXT NOT NULL,
            attempts INTEGER NOT NULL DEFAULT 0,
            accepts INTEGER NOT NULL DEFAULT 0,
            declines INTEGER NOT NULL DEFAULT 0,
            ignores INTEGER NOT NULL DEFAULT 0,
            calibration_delta REAL NOT NULL DEFAULT 0,
            updated_at TEXT NOT NULL,
            PRIMARY KEY(shop_id, customer_id)
        )
    """)
    core.db_execute(conn, """
        CREATE TABLE IF NOT EXISTS founder_sim_outcomes (
            id TEXT PRIMARY KEY,
            shop_id TEXT NOT NULL,
            opening_id TEXT NOT NULL,
            customer_id TEXT NOT NULL,
            cycle INTEGER NOT NULL,
            rank INTEGER NOT NULL,
            baseline_probability REAL NOT NULL,
            learned_probability REAL NOT NULL,
            hidden_probability REAL NOT NULL,
            outcome TEXT NOT NULL,
            accepted INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL
        )
    """)
    core.db_execute(conn, """
        CREATE TABLE IF NOT EXISTS founder_sim_metrics (
            id TEXT PRIMARY KEY,
            shop_id TEXT NOT NULL,
            cycle INTEGER NOT NULL,
            baseline_brier REAL NOT NULL,
            learned_brier REAL NOT NULL,
            baseline_top_pick_accuracy REAL NOT NULL,
            learned_top_pick_accuracy REAL NOT NULL,
            offers INTEGER NOT NULL,
            accepts INTEGER NOT NULL,
            created_at TEXT NOT NULL
        )
    """)
    core.db_execute(conn, """
        CREATE TABLE IF NOT EXISTS founder_sim_recommendations (
            id TEXT PRIMARY KEY,
            shop_id TEXT NOT NULL,
            opening_id TEXT NOT NULL,
            customer_id TEXT NOT NULL,
            recommendation_text TEXT NOT NULL,
            confidence REAL NOT NULL,
            evidence_json TEXT NOT NULL DEFAULT '{}',
            voice_id TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
    """)


def _learning_row(conn, shop_id, customer_id):
    return core.db_fetchone(
        conn,
        "SELECT * FROM founder_sim_customer_learning WHERE shop_id=? AND customer_id=?",
        (shop_id, customer_id),
    )


def learned_probability(conn, shop_id, customer, opening):
    baseline = float(m4_runtime.score(customer, opening)["booking_probability"])
    row = _learning_row(conn, shop_id, customer["id"])
    delta = float(row["calibration_delta"]) if row else 0.0
    return _clamp(_sigmoid(math.log(baseline / max(1e-9, 1.0 - baseline)) + delta))


def hidden_probability(customer, opening):
    """Synthetic ground truth unknown to M4.

    It intentionally includes artist loyalty, exact style fit, price tolerance,
    reliability, and stable individual preference noise so repeated outcomes
    contain learnable signal without simply copying M4's own probability.
    """
    preferred_styles = {
        item.strip().lower()
        for item in str(customer.get("preferred_styles") or "").split(",")
        if item.strip()
    }
    style = str(opening.get("style") or "").strip().lower()
    preferred_artists = {
        item.strip()
        for item in str(customer.get("preferred_artists") or "").split(",")
        if item.strip()
    }
    artist_id = str(opening.get("artist_id") or "")
    average_spend = max(100.0, float(customer.get("average_spend") or 350))
    price = max(1.0, float(opening.get("price") or 350))
    price_ratio = price / average_spend
    completed = min(8.0, float(customer.get("completed_count") or 0))
    cancellations = float(customer.get("cancellation_count") or 0)
    no_shows = float(customer.get("no_show_count") or 0)

    z = -1.15
    z += 1.35 if style and style in preferred_styles else -0.55
    z += 0.85 if artist_id and artist_id in preferred_artists else 0.0
    z += 0.11 * completed
    z -= 0.55 * cancellations
    z -= 0.85 * no_shows
    if price_ratio <= 1.05:
        z += 0.55
    elif price_ratio <= 1.35:
        z += 0.10
    else:
        z -= min(1.4, (price_ratio - 1.35) * 1.4)
    z += (_stable_unit(customer.get("id"), "latent") - 0.5) * 1.2
    return _clamp(_sigmoid(z), 0.02, 0.95)


def _update_learning(conn, shop_id, customer_id, accepted, outcome):
    row = _learning_row(conn, shop_id, customer_id)
    attempts = int(row["attempts"]) if row else 0
    accepts = int(row["accepts"]) if row else 0
    declines = int(row["declines"]) if row else 0
    ignores = int(row["ignores"]) if row else 0
    delta = float(row["calibration_delta"]) if row else 0.0

    attempts += 1
    if accepted:
        accepts += 1
        delta += 0.34 / math.sqrt(attempts)
    elif outcome == "DECLINED":
        declines += 1
        delta -= 0.24 / math.sqrt(attempts)
    else:
        ignores += 1
        delta -= 0.14 / math.sqrt(attempts)
    delta = max(-1.75, min(1.75, delta))
    now = core.now_iso()

    if row:
        core.db_execute(
            conn,
            """UPDATE founder_sim_customer_learning
               SET attempts=?,accepts=?,declines=?,ignores=?,calibration_delta=?,updated_at=?
               WHERE shop_id=? AND customer_id=?""",
            (attempts, accepts, declines, ignores, delta, now, shop_id, customer_id),
        )
    else:
        core.db_execute(
            conn,
            """INSERT INTO founder_sim_customer_learning(
                shop_id,customer_id,attempts,accepts,declines,ignores,calibration_delta,updated_at
            ) VALUES (?,?,?,?,?,?,?,?)""",
            (shop_id, customer_id, attempts, accepts, declines, ignores, delta, now),
        )


def _brier(rows, key):
    if not rows:
        return 0.0
    return sum((float(row[key]) - float(row["accepted"])) ** 2 for row in rows) / len(rows)


def _top_pick_accuracy(rows, probability_key):
    grouped = {}
    for row in rows:
        grouped.setdefault(row["opening_id"], []).append(row)
    if not grouped:
        return 0.0
    hits = 0
    for candidates in grouped.values():
        pick = max(candidates, key=lambda item: float(item[probability_key]))
        hits += int(bool(pick["accepted"]))
    return hits / len(grouped)


def _recommendation_text(opening, pick, learned_probability_value):
    confidence = float(pick["confidence"])
    reasons = pick.get("why") or []
    reason = reasons[0] if reasons else "the strongest current evidence"
    return (
        f"I recommend contacting {pick['name']} first for the {opening.get('style') or opening.get('service')} "
        f"opening. I estimate about {learned_probability_value:.0%} booking probability, driven by {reason}. "
        "If they do not convert, move to the next ranked customer rather than widening the blast."
    )


def run_cycle(shop_id, cycle=1, candidates_per_opening=10):
    conn = core.connect()
    try:
        load_and_assert_founder_simulation_target(conn, core.db_fetchone, shop_id)
        ensure_tables(conn)
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
        if not customers or not openings:
            raise RuntimeError("Crybaby founder simulation must be seeded before running a cycle.")

        cycle_rows = []
        total_accepts = 0
        voice_id = "Ss7hQAiJNG6a81OU5k51"

        for opening in openings:
            ranked = m4_runtime.rank(customers, opening, candidates_per_opening)
            enriched = []
            for rank_index, pick in enumerate(ranked, start=1):
                customer = next(c for c in customers if c["id"] == pick["customer_id"])
                baseline = float(pick["booking_probability"])
                learned = learned_probability(conn, shop_id, customer, opening)
                truth = hidden_probability(customer, opening)
                accepted = int(_stable_unit(shop_id, opening["id"], customer["id"], cycle, "accept") < truth)
                if accepted:
                    outcome = "ACCEPTED"
                    total_accepts += 1
                else:
                    response_roll = _stable_unit(shop_id, opening["id"], customer["id"], cycle, "response")
                    outcome = "DECLINED" if response_roll < 0.58 else "IGNORED"

                row = {
                    "opening_id": opening["id"],
                    "customer_id": customer["id"],
                    "rank": rank_index,
                    "baseline_probability": baseline,
                    "learned_probability": learned,
                    "hidden_probability": truth,
                    "outcome": outcome,
                    "accepted": accepted,
                }
                cycle_rows.append(row)
                enriched.append((pick, learned))
                outcome_id = f"{SIM_PREFIX}outcome_{cycle:04d}_{opening['id']}_{customer['id']}"
                core.db_execute(
                    conn,
                    """INSERT INTO founder_sim_outcomes(
                        id,shop_id,opening_id,customer_id,cycle,rank,baseline_probability,
                        learned_probability,hidden_probability,outcome,accepted,created_at
                    ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        outcome_id, shop_id, opening["id"], customer["id"], cycle, rank_index,
                        baseline, learned, truth, outcome, accepted, core.now_iso(),
                    ),
                )
                _update_learning(conn, shop_id, customer["id"], accepted, outcome)

            if enriched:
                recommendation_pick, recommendation_probability = max(enriched, key=lambda pair: pair[1])
                recommendation_id = f"{SIM_PREFIX}recommendation_{cycle:04d}_{opening['id']}"
                evidence = {
                    "why": recommendation_pick.get("why") or [],
                    "expected_value": recommendation_pick.get("expected_value"),
                    "style_fit": recommendation_pick.get("style_fit"),
                    "budget_fit": recommendation_pick.get("budget_fit"),
                    "baseline_probability": recommendation_pick.get("booking_probability"),
                    "learned_probability": recommendation_probability,
                }
                core.db_execute(
                    conn,
                    """INSERT INTO founder_sim_recommendations(
                        id,shop_id,opening_id,customer_id,recommendation_text,confidence,
                        evidence_json,voice_id,created_at
                    ) VALUES (?,?,?,?,?,?,?,?,?)""",
                    (
                        recommendation_id, shop_id, opening["id"], recommendation_pick["customer_id"],
                        _recommendation_text(opening, recommendation_pick, recommendation_probability),
                        recommendation_pick["confidence"], json.dumps(evidence), voice_id, core.now_iso(),
                    ),
                )

        metrics = {
            "cycle": int(cycle),
            "offers": len(cycle_rows),
            "accepts": total_accepts,
            "baseline_brier": _brier(cycle_rows, "baseline_probability"),
            "learned_brier": _brier(cycle_rows, "learned_probability"),
            "baseline_top_pick_accuracy": _top_pick_accuracy(cycle_rows, "baseline_probability"),
            "learned_top_pick_accuracy": _top_pick_accuracy(cycle_rows, "learned_probability"),
        }
        metric_id = f"{SIM_PREFIX}metrics_{cycle:04d}"
        core.db_execute(
            conn,
            """INSERT INTO founder_sim_metrics(
                id,shop_id,cycle,baseline_brier,learned_brier,baseline_top_pick_accuracy,
                learned_top_pick_accuracy,offers,accepts,created_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (
                metric_id, shop_id, cycle, metrics["baseline_brier"], metrics["learned_brier"],
                metrics["baseline_top_pick_accuracy"], metrics["learned_top_pick_accuracy"],
                metrics["offers"], metrics["accepts"], core.now_iso(),
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
    results = [
        run_cycle(shop_id, cycle=index, candidates_per_opening=candidates_per_opening)
        for index in range(1, cycles + 1)
    ]
    first = results[0]
    last = results[-1]
    return {
        "cycles": cycles,
        "first": first,
        "last": last,
        "brier_improvement": first["learned_brier"] - last["learned_brier"],
        "top_pick_improvement": last["learned_top_pick_accuracy"] - first["learned_top_pick_accuracy"],
    }


def latest_recommendation(shop_id):
    conn = core.connect()
    try:
        ensure_tables(conn)
        row = core.db_fetchone(
            conn,
            """SELECT r.*,c.name AS customer_name,o.style,o.service,o.price,a.name AS artist_name
               FROM founder_sim_recommendations r
               JOIN customers c ON c.id=r.customer_id AND c.shop_id=r.shop_id
               JOIN openings o ON o.id=r.opening_id AND o.shop_id=r.shop_id
               JOIN artists a ON a.id=o.artist_id AND a.shop_id=r.shop_id
               WHERE r.shop_id=? ORDER BY r.created_at DESC LIMIT 1""",
            (shop_id,),
        )
        if not row:
            return None
        result = dict(row)
        try:
            result["evidence"] = json.loads(result.get("evidence_json") or "{}")
        except Exception:
            result["evidence"] = {}
        return result
    finally:
        conn.close()
