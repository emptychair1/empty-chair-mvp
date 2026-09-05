"""Predictive Ready Bench for Empty Chair.

Empty Chair should not begin looking for replacement clients after a chair
becomes empty. This module continuously pre-ranks consented customers for each
active artist/style combination, then uses that bench as the candidate pool
when the real cancellation arrives.

The exact opening is still re-scored at recovery time, so date/service/style
specific information remains authoritative. The bench is preparation, not a
replacement for final matching.
"""

import json
from datetime import datetime, timezone

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse

import app as core


BENCH_SIZE = 25
FINAL_QUEUE_SIZE = 5


def _style_key(value: str | None) -> str:
    return (value or "*").strip().lower() or "*"


def ensure_schema() -> None:
    conn = core.connect()
    try:
        core.db_execute(
            conn,
            """
            CREATE TABLE IF NOT EXISTS ready_bench_matches (
                shop_id TEXT NOT NULL,
                artist_id TEXT NOT NULL,
                style_key TEXT NOT NULL,
                customer_id TEXT NOT NULL,
                bench_score REAL NOT NULL,
                rank INTEGER NOT NULL,
                refreshed_at TEXT NOT NULL,
                PRIMARY KEY (shop_id, artist_id, style_key, customer_id)
            )
            """,
        )
        core.db_execute(
            conn,
            """
            CREATE INDEX IF NOT EXISTS idx_ready_bench_lookup
            ON ready_bench_matches(shop_id, artist_id, style_key, rank)
            """,
        )
        conn.commit()
    finally:
        conn.close()


def _bench_score(customer, artist, style: str) -> float:
    """Score durable fit signals that are knowable before a cancellation."""
    score = 0.0
    artist_preferences = core.csv_values(customer["preferred_artists"])
    style_preferences = core.csv_values(customer["preferred_styles"])
    service_preferences = core.csv_values(customer["preferred_services"])

    artist_id = (artist["id"] or "").lower()
    artist_name = (artist["name"] or "").lower()

    if artist_id in artist_preferences or artist_name in artist_preferences:
        score += 35
    if style != "*" and style in style_preferences:
        score += 25
    if "tattoo" in service_preferences:
        score += 15

    completed = int(customer["completed_count"] or 0)
    appointments = int(customer["appointment_count"] or 0)
    cancellations = int(customer["cancellation_count"] or 0)
    no_shows = int(customer["no_show_count"] or 0)

    score += min(completed, 5) * 4
    if appointments > 0 and cancellations == 0 and no_shows == 0:
        score += 10
    score -= min(cancellations, 3) * 5
    score -= min(no_shows, 2) * 10

    if customer["last_offer_at"]:
        last_offer = core.parse_datetime(customer["last_offer_at"])
        if last_offer:
            age_hours = (datetime.now(timezone.utc) - last_offer).total_seconds() / 3600
            if age_hours < 24:
                score -= 30
            elif age_hours < 72:
                score -= 15
            elif age_hours < 30 * 24:
                score -= 5

    return max(0.0, min(100.0, score))


def refresh_shop(shop_id: str) -> dict:
    """Rebuild all predictive benches for one shop atomically."""
    ensure_schema()
    conn = core.connect()
    try:
        artists = core.db_fetchall(
            conn,
            """
            SELECT * FROM artists
            WHERE shop_id = ? AND active = 1
            ORDER BY name
            """,
            (shop_id,),
        )
        customers = core.db_fetchall(
            conn,
            """
            SELECT * FROM customers
            WHERE shop_id = ? AND communication_consent = 1
            """,
            (shop_id,),
        )

        core.db_execute(
            conn,
            "DELETE FROM ready_bench_matches WHERE shop_id = ?",
            (shop_id,),
        )

        refreshed_at = core.now_iso()
        rows_written = 0
        benches = 0

        for artist in artists:
            styles = sorted(core.csv_values(artist["styles"]))
            style_keys = ["*"] + styles

            for style in style_keys:
                ranked = [
                    (_bench_score(customer, artist, style), customer)
                    for customer in customers
                ]
                ranked.sort(
                    key=lambda item: (
                        item[0],
                        int(item[1]["completed_count"] or 0),
                    ),
                    reverse=True,
                )

                for rank, (score, customer) in enumerate(ranked[:BENCH_SIZE], start=1):
                    core.db_execute(
                        conn,
                        """
                        INSERT INTO ready_bench_matches(
                            shop_id, artist_id, style_key, customer_id,
                            bench_score, rank, refreshed_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            shop_id,
                            artist["id"],
                            style,
                            customer["id"],
                            score,
                            rank,
                            refreshed_at,
                        ),
                    )
                    rows_written += 1
                benches += 1

        conn.commit()
    finally:
        conn.close()

    core.event(
        "ready_bench.refreshed",
        "shop",
        shop_id,
        json.dumps({"benches": benches, "matches": rows_written}),
    )
    return {"benches": benches, "matches": rows_written, "refreshed_at": refreshed_at}


def refresh_all_shops() -> int:
    ensure_schema()
    conn = core.connect()
    try:
        rows = core.db_fetchall(
            conn,
            "SELECT id FROM shops WHERE status = 'active'",
        )
    finally:
        conn.close()

    refreshed = 0
    for row in rows:
        try:
            refresh_shop(row["id"])
            refreshed += 1
        except Exception as exc:
            core.event("ready_bench.refresh_failed", "shop", row["id"], str(exc))
    return refreshed


def get_bench_customer_ids(opening, limit: int = BENCH_SIZE) -> list[str]:
    """Return the already-prepared pool for a newly empty chair."""
    ensure_schema()
    style = _style_key(opening["style"])
    conn = core.connect()
    try:
        rows = core.db_fetchall(
            conn,
            """
            SELECT customer_id
            FROM ready_bench_matches
            WHERE shop_id = ?
              AND artist_id = ?
              AND style_key IN (?, '*')
            ORDER BY
              CASE WHEN style_key = ? THEN 0 ELSE 1 END,
              rank
            LIMIT ?
            """,
            (
                opening["shop_id"],
                opening["artist_id"],
                style,
                style,
                limit,
            ),
        )
    finally:
        conn.close()

    seen = set()
    result = []
    for row in rows:
        customer_id = row["customer_id"]
        if customer_id not in seen:
            seen.add(customer_id)
            result.append(customer_id)
    return result


def create_recovery_queue_from_bench(opening_id: str) -> int:
    """Build the real five-person queue from the predictive bench."""
    ensure_schema()
    conn = core.connect()
    try:
        opening = core.db_fetchone(
            conn,
            "SELECT * FROM openings WHERE id = ?",
            (opening_id,),
        )
        if not opening:
            return 0

        artist = core.db_fetchone(
            conn,
            "SELECT * FROM artists WHERE id = ?",
            (opening["artist_id"],),
        )
        if not artist:
            return 0

        existing = core.db_fetchone(
            conn,
            "SELECT COUNT(*) AS n FROM offers WHERE opening_id = ?",
            (opening_id,),
        )
        if existing and existing["n"]:
            return existing["n"]
    finally:
        conn.close()

    # The bench is deliberately refreshed before use. This keeps it warm during
    # normal operation while ensuring contact-fatigue changes are respected.
    # We still use the precomputed table rather than discovering candidates from
    # scratch after the cancellation.
    bench_ids = get_bench_customer_ids(opening)
    if not bench_ids:
        refresh_shop(opening["shop_id"])
        bench_ids = get_bench_customer_ids(opening)

    conn = core.connect()
    try:
        if bench_ids:
            placeholders = ",".join("?" for _ in bench_ids)
            customers = core.db_fetchall(
                conn,
                f"""
                SELECT * FROM customers
                WHERE shop_id = ?
                  AND communication_consent = 1
                  AND id IN ({placeholders})
                """,
                (opening["shop_id"], *bench_ids),
            )
        else:
            customers = []

        by_id = {customer["id"]: customer for customer in customers}
        ordered_customers = [by_id[cid] for cid in bench_ids if cid in by_id]

        candidates = [
            (core.recovery_score(customer, opening, artist), customer)
            for customer in ordered_customers
        ]
        candidates.sort(
            key=lambda item: (
                item[0],
                int(item[1]["completed_count"] or 0),
            ),
            reverse=True,
        )
        selected = candidates[:FINAL_QUEUE_SIZE]

        for rank, (score, customer) in enumerate(selected, start=1):
            offer_id = f"offer_{core.uuid.uuid4().hex[:12]}"
            placeholder_expiration = datetime.now(timezone.utc) + core.timedelta(minutes=30)
            core.db_execute(
                conn,
                """
                INSERT INTO offers(
                    id, opening_id, customer_id, score, rank,
                    channel, expires_at, status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    offer_id,
                    opening_id,
                    customer["id"],
                    score,
                    rank,
                    "sms",
                    placeholder_expiration.isoformat(),
                    "PENDING",
                ),
            )

        core.db_execute(
            conn,
            "UPDATE openings SET status = ? WHERE id = ?",
            ("RECOVERY_ACTIVE" if selected else "NO_RECOVERY", opening_id),
        )
        conn.commit()
    finally:
        conn.close()

    core.event(
        "ready_bench.activated",
        "opening",
        opening_id,
        json.dumps({"bench_candidates": len(bench_ids), "queue_size": len(selected)}),
    )
    return len(selected)


def bench_snapshot(shop_id: str) -> list[dict]:
    ensure_schema()
    conn = core.connect()
    try:
        rows = core.db_fetchall(
            conn,
            """
            SELECT
                rb.artist_id,
                a.name AS artist_name,
                rb.style_key,
                rb.customer_id,
                c.name AS customer_name,
                rb.bench_score,
                rb.rank,
                rb.refreshed_at
            FROM ready_bench_matches rb
            JOIN artists a ON a.id = rb.artist_id
            JOIN customers c ON c.id = rb.customer_id
            WHERE rb.shop_id = ?
            ORDER BY a.name, rb.style_key, rb.rank
            """,
            (shop_id,),
        )
        return [dict(row) for row in rows]
    finally:
        conn.close()


@core.app.on_event("startup")
def warm_ready_benches() -> None:
    try:
        refresh_all_shops()
    except Exception as exc:
        core.event("ready_bench.startup_failed", "system", "ready-bench", str(exc))


@core.app.get("/api/ready-bench")
def ready_bench_api(request: Request):
    user = core.get_current_user(request)
    if not user:
        raise HTTPException(401, "Sign in first.")
    return JSONResponse({"matches": bench_snapshot(user["shop_id"])})


@core.app.post("/api/ready-bench/refresh")
def refresh_ready_bench_api(request: Request):
    user = core.get_current_user(request)
    if not user:
        raise HTTPException(401, "Sign in first.")
    return JSONResponse({"ok": True, **refresh_shop(user["shop_id"])})


# Patch the canonical queue builder. start_recovery_campaign performs a module
# global lookup at call time, so every existing recovery trigger now consumes
# the predictive bench without changing callers.
core.create_recovery_queue = create_recovery_queue_from_bench
