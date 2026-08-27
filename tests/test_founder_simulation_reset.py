import sqlite3

import founder_simulation as sim


def _connect(path):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _schema(conn):
    conn.executescript("""
    CREATE TABLE shops (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL
    );
    CREATE TABLE users (
        id TEXT PRIMARY KEY,
        shop_id TEXT NOT NULL,
        name TEXT NOT NULL
    );
    CREATE TABLE artists (
        id TEXT PRIMARY KEY,
        shop_id TEXT NOT NULL,
        name TEXT NOT NULL,
        email TEXT,
        phone TEXT,
        styles TEXT NOT NULL DEFAULT '',
        services TEXT NOT NULL DEFAULT 'tattoo',
        active INTEGER NOT NULL DEFAULT 1
    );
    CREATE TABLE customers (
        id TEXT PRIMARY KEY,
        shop_id TEXT NOT NULL,
        name TEXT NOT NULL,
        phone TEXT NOT NULL,
        email TEXT,
        communication_consent INTEGER NOT NULL DEFAULT 0,
        preferred_artists TEXT NOT NULL DEFAULT '',
        preferred_styles TEXT NOT NULL DEFAULT '',
        preferred_services TEXT NOT NULL DEFAULT 'tattoo',
        appointment_count INTEGER NOT NULL DEFAULT 0,
        completed_count INTEGER NOT NULL DEFAULT 0,
        cancellation_count INTEGER NOT NULL DEFAULT 0,
        no_show_count INTEGER NOT NULL DEFAULT 0,
        average_spend REAL NOT NULL DEFAULT 0,
        last_appointment_at TEXT,
        last_offer_at TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );
    CREATE TABLE openings (
        id TEXT PRIMARY KEY,
        shop_id TEXT NOT NULL,
        artist_id TEXT NOT NULL,
        date TEXT NOT NULL,
        start_time TEXT NOT NULL,
        end_time TEXT,
        service TEXT NOT NULL,
        style TEXT,
        price REAL NOT NULL,
        status TEXT NOT NULL DEFAULT 'OPEN',
        created_at TEXT NOT NULL,
        expires_at TEXT NOT NULL,
        booking_id TEXT
    );
    CREATE TABLE offers (
        id TEXT PRIMARY KEY,
        opening_id TEXT NOT NULL,
        customer_id TEXT NOT NULL,
        score REAL NOT NULL,
        rank INTEGER NOT NULL,
        channel TEXT NOT NULL DEFAULT 'sms',
        expires_at TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'PENDING'
    );
    CREATE TABLE bookings (
        id TEXT PRIMARY KEY,
        opening_id TEXT NOT NULL,
        customer_id TEXT NOT NULL,
        artist_id TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'PENDING',
        amount REAL NOT NULL,
        deposit_amount REAL NOT NULL DEFAULT 0,
        deposit_status TEXT NOT NULL DEFAULT 'NOT_REQUIRED'
    );
    CREATE TABLE events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        event_type TEXT NOT NULL,
        entity_type TEXT NOT NULL,
        entity_id TEXT NOT NULL,
        metadata TEXT,
        created_at TEXT NOT NULL
    );
    CREATE TABLE concierge_leads (
        id TEXT PRIMARY KEY,
        shop_id TEXT NOT NULL,
        customer_id TEXT NOT NULL,
        source TEXT NOT NULL DEFAULT 'concierge',
        profile_json TEXT NOT NULL DEFAULT '{}',
        m4_confidence INTEGER NOT NULL DEFAULT 0,
        offer_opt_in INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );
    """)
    conn.commit()


def test_crybaby_reset_preserves_blindwolf_leads_and_founder(tmp_path, monkeypatch):
    path = tmp_path / "founder-sim.db"
    conn = _connect(path)
    _schema(conn)
    conn.executemany(
        "INSERT INTO shops(id,name) VALUES (?,?)",
        [("shop_crybaby", "Crybaby Tattoos"), ("shop_blindwolf", "Blindwolf Tattoo")],
    )
    conn.executemany(
        "INSERT INTO users(id,shop_id,name) VALUES (?,?,?)",
        [("founder", "shop_crybaby", "Founder"), ("blindwolf_owner", "shop_blindwolf", "Blindwolf Owner")],
    )
    now = "2026-08-26T12:00:00+00:00"
    conn.executemany(
        """INSERT INTO customers(
            id,shop_id,name,phone,email,communication_consent,preferred_artists,
            preferred_styles,preferred_services,appointment_count,completed_count,
            cancellation_count,no_show_count,average_spend,last_appointment_at,
            last_offer_at,created_at,updated_at
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        [
            ("crybaby_old", "shop_crybaby", "Old Test", "+15550000001", None, 1, "", "Blackwork", "tattoo", 0, 0, 0, 0, 0, None, None, now, now),
            ("blindwolf_real", "shop_blindwolf", "Protected Lead", "+15550000002", "lead@example.com", 1, "", "Traditional", "tattoo", 0, 0, 0, 0, 0, None, None, now, now),
        ],
    )
    conn.execute(
        "INSERT INTO concierge_leads(id,shop_id,customer_id,source,profile_json,m4_confidence,offer_opt_in,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?)",
        ("blindwolf_lead", "shop_blindwolf", "blindwolf_real", "concierge", '{"real":true}', 88, 1, now, now),
    )
    conn.commit()
    conn.close()

    monkeypatch.setenv("EMPTY_CHAIR_FOUNDER_SIMULATION_SHOP_ID", "shop_crybaby")
    monkeypatch.setenv("EMPTY_CHAIR_PROTECTED_SHOP_IDS", "shop_blindwolf")
    monkeypatch.setattr(sim.core, "USE_POSTGRES", False)
    monkeypatch.setattr(sim.core, "connect", lambda: _connect(path))

    summary = sim.reset_and_seed_crybaby("shop_crybaby")

    check = _connect(path)
    try:
        assert check.execute("SELECT COUNT(*) FROM users WHERE id='founder' AND shop_id='shop_crybaby'").fetchone()[0] == 1
        assert check.execute("SELECT COUNT(*) FROM shops WHERE id='shop_crybaby'").fetchone()[0] == 1
        assert check.execute("SELECT COUNT(*) FROM customers WHERE shop_id='shop_crybaby'").fetchone()[0] == 50
        assert check.execute("SELECT COUNT(*) FROM artists WHERE shop_id='shop_crybaby'").fetchone()[0] == 5
        assert check.execute("SELECT COUNT(*) FROM openings WHERE shop_id='shop_crybaby'").fetchone()[0] == 5

        # Critical tenant-isolation assertions.
        assert check.execute("SELECT COUNT(*) FROM customers WHERE id='blindwolf_real' AND shop_id='shop_blindwolf'").fetchone()[0] == 1
        assert check.execute("SELECT COUNT(*) FROM concierge_leads WHERE id='blindwolf_lead' AND shop_id='shop_blindwolf'").fetchone()[0] == 1
        protected_profile = check.execute("SELECT profile_json FROM concierge_leads WHERE id='blindwolf_lead'").fetchone()[0]
        assert protected_profile == '{"real":true}'
    finally:
        check.close()

    assert summary == {
        "shop_id": "shop_crybaby",
        "seed_version": "v1",
        "artists": 5,
        "customers": 50,
        "concierge_leads": 15,
        "openings": 5,
        "founder_account_preserved": True,
    }


def test_reset_refuses_blindwolf_before_mutation(tmp_path, monkeypatch):
    path = tmp_path / "founder-sim-protected.db"
    conn = _connect(path)
    _schema(conn)
    conn.execute("INSERT INTO shops(id,name) VALUES (?,?)", ("shop_blindwolf", "Blindwolf Tattoo"))
    conn.commit()
    conn.close()

    monkeypatch.setenv("EMPTY_CHAIR_PROTECTED_SHOP_IDS", "shop_blindwolf")
    monkeypatch.setattr(sim.core, "USE_POSTGRES", False)
    monkeypatch.setattr(sim.core, "connect", lambda: _connect(path))

    import pytest
    from founder_simulation_safety import FounderSimulationSafetyError

    with pytest.raises(FounderSimulationSafetyError):
        sim.reset_and_seed_crybaby("shop_blindwolf")

    check = _connect(path)
    try:
        assert check.execute("SELECT name FROM shops WHERE id='shop_blindwolf'").fetchone()[0] == "Blindwolf Tattoo"
        # Validation happens before simulation tables are even created.
        assert check.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='founder_sim_runs'").fetchone()[0] == 0
    finally:
        check.close()
