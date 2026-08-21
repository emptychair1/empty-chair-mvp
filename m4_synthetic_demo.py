"""Resettable, isolated synthetic dataset for the M4 operator demo.

This augments the existing public demo shop only. It never touches production
shops. All records are synthetic and external delivery is intentionally avoided.
"""
import random
from datetime import date, timedelta

from fastapi import Request
from fastapi.responses import JSONResponse

import app as core
import demo_mode

DEMO_SHOP_ID = demo_mode.DEMO_SHOP_ID
DEMO_USER_ID = demo_mode.DEMO_USER_ID
_rng = random.Random(4404)

ARTISTS = [
    ("demo_artist_alex", "Alex Rivera", "Blackwork,Traditional"),
    ("demo_artist_morgan", "Morgan Vale", "Fine line,Realism"),
    ("demo_artist_nico", "Nico Hart", "American Traditional,Neo Traditional"),
    ("demo_artist_sage", "Sage Monroe", "Black & Grey,Realism"),
    ("demo_artist_ivy", "Ivy Brooks", "Fine line,Botanical"),
    ("demo_artist_rome", "Rome Ellis", "Japanese,Blackwork"),
]
STYLES = ["Blackwork", "Traditional", "American Traditional", "Neo Traditional", "Fine line", "Realism", "Black & Grey", "Botanical", "Japanese"]


def _seed_synthetic_operator_data():
    conn = core.connect()
    try:
        now = core.now_iso()
        today = date.today()

        existing = {r["id"] for r in core.db_fetchall(conn, "SELECT id FROM artists WHERE shop_id=?", (DEMO_SHOP_ID,))}
        for aid, name, styles in ARTISTS:
            if aid in existing:
                core.db_execute(conn, "UPDATE artists SET name=?,styles=?,services='Tattoo',active=1 WHERE id=? AND shop_id=?", (name, styles, aid, DEMO_SHOP_ID))
            else:
                core.db_execute(conn, "INSERT INTO artists(id,shop_id,name,email,phone,styles,services,active) VALUES (?,?,?,?,?,?,?,1)", (aid, DEMO_SHOP_ID, name, None, None, styles, "Tattoo"))

        current_customers = core.db_fetchall(conn, "SELECT id FROM customers WHERE shop_id=?", (DEMO_SHOP_ID,))
        current_n = len(current_customers)
        target = 1200
        artist_ids = [a[0] for a in ARTISTS]

        # Deterministic broad population. No real phone/email values are created.
        for i in range(current_n + 1, target + 1):
            cid = f"demo_customer_{i:04d}"
            artist = _rng.choice(artist_ids)
            artist_styles = next(x[2].split(",") for x in ARTISTS if x[0] == artist)
            style = _rng.choice(artist_styles if _rng.random() < 0.72 else STYLES)
            completed = max(0, min(16, int(_rng.gauss(3.8, 2.8))))
            cancellations = 1 if _rng.random() < 0.16 else 0
            no_shows = 1 if _rng.random() < 0.055 else 0
            appointments = completed + cancellations + no_shows + (1 if _rng.random() < 0.35 else 0)
            avg = int(max(140, min(1400, _rng.lognormvariate(5.85, 0.42))))
            consent = 1 if _rng.random() < 0.87 else 0
            core.db_execute(conn, "INSERT INTO customers(id,shop_id,name,phone,email,communication_consent,preferred_artists,preferred_styles,preferred_services,appointment_count,completed_count,cancellation_count,no_show_count,average_spend,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                            (cid, DEMO_SHOP_ID, f"Synthetic Customer {i:04d}", None, None, consent, artist, style, "Tattoo", appointments, completed, cancellations, no_shows, avg, now, now))

        # Known high-signal examples for benchmark scenarios. These are synthetic
        # ground-truth fixtures, not claims about real customers.
        fixtures = [
            ("demo_signal_blackwork", "Blackwork Benchmark", "demo_artist_alex", "Blackwork", 9, 9, 0, 0, 650),
            ("demo_signal_fine", "Fine Line Benchmark", "demo_artist_ivy", "Fine line", 7, 7, 0, 0, 420),
            ("demo_signal_trad", "Traditional Benchmark", "demo_artist_nico", "American Traditional", 11, 10, 1, 0, 575),
            ("demo_signal_realism", "Realism Benchmark", "demo_artist_sage", "Black & Grey", 8, 8, 0, 0, 900),
            ("demo_signal_japanese", "Japanese Benchmark", "demo_artist_rome", "Japanese", 6, 6, 0, 0, 780),
        ]
        for cid, name, artist, style, appts, completed, cancels, no_shows, avg in fixtures:
            row = core.db_fetchone(conn, "SELECT id FROM customers WHERE id=?", (cid,))
            if row:
                core.db_execute(conn, "UPDATE customers SET name=?,communication_consent=1,preferred_artists=?,preferred_styles=?,preferred_services='Tattoo',appointment_count=?,completed_count=?,cancellation_count=?,no_show_count=?,average_spend=?,updated_at=? WHERE id=?",
                                (name, artist, style, appts, completed, cancels, no_shows, avg, now, cid))
            else:
                core.db_execute(conn, "INSERT INTO customers(id,shop_id,name,phone,email,communication_consent,preferred_artists,preferred_styles,preferred_services,appointment_count,completed_count,cancellation_count,no_show_count,average_spend,created_at,updated_at) VALUES (?,?,?,?,?,1,?,?,?,?,?,?,?,?,?,?)",
                                (cid, DEMO_SHOP_ID, name, None, None, artist, style, "Tattoo", appts, completed, cancels, no_shows, avg, now, now))

        # Add four additional open gaps; the existing demo reset already provides
        # one Fine-line OPEN gap, producing five current operator scenarios.
        gaps = [
            ("demo_m4_gap_blackwork", "demo_artist_alex", 1, "15:00", "19:00", "Blackwork", 650),
            ("demo_m4_gap_trad", "demo_artist_nico", 2, "12:00", "16:00", "American Traditional", 575),
            ("demo_m4_gap_realism", "demo_artist_sage", 3, "13:00", "18:00", "Black & Grey", 900),
            ("demo_m4_gap_japanese", "demo_artist_rome", 5, "11:00", "16:00", "Japanese", 780),
        ]
        for oid, aid, plus_days, start, end, style, price in gaps:
            if not core.db_fetchone(conn, "SELECT id FROM openings WHERE id=?", (oid,)):
                core.db_execute(conn, "INSERT INTO openings(id,shop_id,artist_id,date,start_time,end_time,service,style,price,status,created_at,expires_at) VALUES (?,?,?,?,?,?,'Tattoo',? ,?,'OPEN',?,?)",
                                (oid, DEMO_SHOP_ID, aid, (today + timedelta(days=plus_days)).isoformat(), start, end, style, price, now, (today + timedelta(days=7)).isoformat() + "T23:59:00+00:00"))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


_original_reset = demo_mode._reset_data


def _synthetic_reset():
    _original_reset()
    _seed_synthetic_operator_data()


demo_mode._reset_data = _synthetic_reset


@core.app.post("/api/m4/operator/reset-synthetic")
def reset_m4_synthetic(request: Request):
    user = core.get_current_user(request)
    if not user or user["id"] != DEMO_USER_ID or user["shop_id"] != DEMO_SHOP_ID:
        return JSONResponse({"error": "Synthetic reset is available only inside the isolated demo account."}, status_code=403)
    _synthetic_reset()
    return JSONResponse({
        "ok": True,
        "synthetic": True,
        "artists": 6,
        "customers": 1205,
        "open_scenarios": 5,
        "message": "Synthetic M4 shop reset complete. No real customer data or external recipients are present.",
    }, headers={"Cache-Control": "no-store"})
