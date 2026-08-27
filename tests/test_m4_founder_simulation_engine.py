import os
import sqlite3
from pathlib import Path

import app as core
import founder_simulation
import m4_founder_simulation_engine as engine


def _connect_factory(path):
    def _connect():
        conn = sqlite3.connect(path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn
    return _connect


def _prepare(tmp_path, monkeypatch):
    db_path = Path(tmp_path) / "sim.db"
    monkeypatch.setattr(core, "USE_POSTGRES", False)
    monkeypatch.setattr(core, "connect", _connect_factory(str(db_path)))
    monkeypatch.setenv("EMPTY_CHAIR_FOUNDER_SIMULATION_SHOP_ID", "shop_crybaby")
    monkeypatch.setenv("EMPTY_CHAIR_PROTECTED_SHOP_IDS", "shop_blindwolf")

    conn = core.connect()
    conn.executescript("""
        CREATE TABLE shops(id TEXT PRIMARY KEY,name TEXT,timezone TEXT,email TEXT,status TEXT,created_at TEXT);
        CREATE TABLE users(id TEXT PRIMARY KEY,shop_id TEXT,name TEXT,email TEXT,password_hash TEXT,password_salt TEXT,is_active INTEGER,created_at TEXT);
        CREATE TABLE artists(id TEXT PRIMARY KEY,shop_id TEXT,name TEXT,email TEXT,phone TEXT,styles TEXT,services TEXT,active INTEGER);
        CREATE TABLE customers(
            id TEXT PRIMARY KEY,shop_id TEXT,name TEXT,phone TEXT,email TEXT,communication_consent INTEGER,
            preferred_artists TEXT,preferred_styles TEXT,preferred_services TEXT,appointment_count INTEGER,
            completed_count INTEGER,cancellation_count INTEGER,no_show_count INTEGER,average_spend REAL,
            last_appointment_at TEXT,last_offer_at TEXT,created_at TEXT,updated_at TEXT
        );
        CREATE TABLE openings(
            id TEXT PRIMARY KEY,shop_id TEXT,artist_id TEXT,date TEXT,start_time TEXT,end_time TEXT,
            service TEXT,style TEXT,price REAL,status TEXT,created_at TEXT,expires_at TEXT,booking_id TEXT
        );
        CREATE TABLE offers(id TEXT PRIMARY KEY,opening_id TEXT,customer_id TEXT,score REAL,rank INTEGER,channel TEXT,sent_at TEXT,opened_at TEXT,responded_at TEXT,claimed_at TEXT,declined_at TEXT,expires_at TEXT,status TEXT,decline_reason TEXT);
        CREATE TABLE bookings(id TEXT PRIMARY KEY,opening_id TEXT,customer_id TEXT,artist_id TEXT,status TEXT,amount REAL,deposit_amount REAL,deposit_status TEXT,booked_at TEXT);
        CREATE TABLE events(id INTEGER PRIMARY KEY AUTOINCREMENT,event_type TEXT,entity_type TEXT,entity_id TEXT,metadata TEXT,created_at TEXT);
        CREATE TABLE concierge_leads(
            id TEXT PRIMARY KEY,shop_id TEXT,customer_id TEXT,source TEXT,profile_json TEXT,m4_confidence INTEGER,
            offer_opt_in INTEGER,created_at TEXT,updated_at TEXT
        );
    """)
    now = core.now_iso()
    conn.execute("INSERT INTO shops VALUES (?,?,?,?,?,?)", ("shop_crybaby", "Crybaby Tattoos", "America/New_York", "cry@example.test", "active", now))
    conn.execute("INSERT INTO shops VALUES (?,?,?,?,?,?)", ("shop_blindwolf", "Blindwolf Tattoo", "America/New_York", "blind@example.test", "active", now))
    conn.execute("INSERT INTO users VALUES (?,?,?,?,?,?,?,?)", ("founder", "shop_crybaby", "Founder", "founder@example.test", "h", "s", 1, now))
    conn.execute("INSERT INTO customers VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (
        "blind_customer", "shop_blindwolf", "Protected Lead", "+15559990000", "protected@example.test", 1,
        "", "Blackwork", "tattoo", 0, 0, 0, 0, 0, None, None, now, now,
    ))
    conn.execute("INSERT INTO concierge_leads VALUES (?,?,?,?,?,?,?,?,?)", (
        "blind_lead", "shop_blindwolf", "blind_customer", "concierge", '{"project":"protected"}', 90, 1, now, now,
    ))
    conn.commit()
    conn.close()
    founder_simulation.reset_and_seed_crybaby("shop_crybaby")
    return db_path


def test_simulation_records_outcomes_and_recommendations(tmp_path, monkeypatch):
    _prepare(tmp_path, monkeypatch)
    metrics = engine.run_cycle("shop_crybaby", cycle=1)
    assert metrics["offers"] > 0

    conn = core.connect()
    try:
        outcomes = core.db_fetchall(conn, "SELECT * FROM founder_sim_outcomes WHERE shop_id=?", ("shop_crybaby",))
        recommendations = core.db_fetchall(conn, "SELECT * FROM founder_sim_recommendations WHERE shop_id=?", ("shop_crybaby",))
        learning = core.db_fetchall(conn, "SELECT * FROM founder_sim_customer_learning WHERE shop_id=?", ("shop_crybaby",))
        protected = core.db_fetchone(conn, "SELECT profile_json FROM concierge_leads WHERE id='blind_lead'")
    finally:
        conn.close()

    assert len(outcomes) == metrics["offers"]
    assert recommendations
    assert learning
    assert protected["profile_json"] == '{"project":"protected"}'


def test_simulation_is_deterministic_after_reset(tmp_path, monkeypatch):
    _prepare(tmp_path, monkeypatch)
    first = engine.run_cycle("shop_crybaby", cycle=1)
    founder_simulation.reset_and_seed_crybaby("shop_crybaby")
    second = engine.run_cycle("shop_crybaby", cycle=1)
    assert first == second


def test_learning_changes_probabilities_over_repeated_cycles(tmp_path, monkeypatch):
    _prepare(tmp_path, monkeypatch)
    engine.run_cycle("shop_crybaby", cycle=1)
    conn = core.connect()
    try:
        before = core.db_fetchall(conn, "SELECT customer_id,calibration_delta FROM founder_sim_customer_learning WHERE shop_id=?", ("shop_crybaby",))
    finally:
        conn.close()
    engine.run_cycle("shop_crybaby", cycle=2)
    conn = core.connect()
    try:
        after = core.db_fetchall(conn, "SELECT customer_id,calibration_delta FROM founder_sim_customer_learning WHERE shop_id=?", ("shop_crybaby",))
    finally:
        conn.close()
    before_map = {row["customer_id"]: float(row["calibration_delta"]) for row in before}
    after_map = {row["customer_id"]: float(row["calibration_delta"]) for row in after}
    assert any(after_map[key] != before_map[key] for key in before_map)


def test_latest_recommendation_uses_configured_voice_id(tmp_path, monkeypatch):
    _prepare(tmp_path, monkeypatch)
    engine.run_cycle("shop_crybaby", cycle=1)
    recommendation = engine.latest_recommendation("shop_crybaby")
    assert recommendation is not None
    assert recommendation["voice_id"] == "Ss7hQAiJNG6a81OU5k51"
    assert "I recommend contacting" in recommendation["recommendation_text"]
