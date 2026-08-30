"""Authenticated Crybaby Tattoos cleanup tool.

This module never mutates data on import. It registers a small authenticated
maintenance screen that previews clearly synthetic/test records and only
executes after an explicit POST confirmation from a signed-in Crybaby user.
"""

from __future__ import annotations

import html
import json

from fastapi import Form, Request
from fastapi.responses import HTMLResponse

import app as core
from founder_simulation_safety import load_and_assert_founder_simulation_target

SIM_PREFIX = "founder_sim_"
CONFIRM_PHRASE = "CLEAN CRYBABY"


def _table_exists(conn, table_name: str) -> bool:
    if getattr(core, "USE_POSTGRES", False):
        row = core.db_fetchone(
            conn,
            "SELECT 1 FROM information_schema.tables WHERE table_schema='public' AND table_name=?",
            (table_name,),
        )
        return bool(row)
    row = core.db_fetchone(
        conn,
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (table_name,),
    )
    return bool(row)


def _column_exists(conn, table_name: str, column_name: str) -> bool:
    if not _table_exists(conn, table_name):
        return False
    if getattr(core, "USE_POSTGRES", False):
        row = core.db_fetchone(
            conn,
            """SELECT 1 FROM information_schema.columns
               WHERE table_schema='public' AND table_name=? AND column_name=?""",
            (table_name, column_name),
        )
        return bool(row)
    rows = core.db_fetchall(conn, f"PRAGMA table_info({table_name})")
    return any(str(row[1]) == column_name for row in rows)


def _normalized(value) -> str:
    return " ".join(str(value or "").strip().lower().split())


def _assert_signed_in_crybaby(conn, user):
    if not user or not user.get("shop_id"):
        raise RuntimeError("Crybaby cleanup refused: signed-in shop is required")
    shop_id = str(user["shop_id"])
    load_and_assert_founder_simulation_target(conn, core.db_fetchone, shop_id)
    shop = core.db_fetchone(conn, "SELECT id,name FROM shops WHERE id=?", (shop_id,))
    if not shop:
        raise RuntimeError("Crybaby cleanup refused: shop was not found")
    return shop


def _artists_for_shop(conn, shop_id: str) -> list[dict]:
    return [
        dict(row)
        for row in core.db_fetchall(
            conn,
            "SELECT id,name,email FROM artists WHERE shop_id=? ORDER BY name,id",
            (shop_id,),
        )
    ]


def _resolve_founder_artist(conn, shop_id: str, selected_artist_id: str | None = None):
    users = [
        dict(row)
        for row in core.db_fetchall(
            conn,
            "SELECT id,name,email FROM users WHERE shop_id=? AND is_active=1 ORDER BY created_at ASC",
            (shop_id,),
        )
    ]
    artists = _artists_for_shop(conn, shop_id)

    if not users:
        raise RuntimeError("Crybaby cleanup refused: no active Crybaby user account found")

    if selected_artist_id:
        selected_artist_id = str(selected_artist_id).strip()
        selected = next((row for row in artists if str(row.get("id")) == selected_artist_id), None)
        if not selected:
            raise RuntimeError("Selected founder artist does not belong to this Crybaby shop")
        return selected

    matches: dict[str, dict] = {}
    for artist in artists:
        artist_name = _normalized(artist.get("name"))
        artist_email = _normalized(artist.get("email"))
        for user in users:
            user_name = _normalized(user.get("name"))
            user_email = _normalized(user.get("email"))
            if artist_email and user_email and artist_email == user_email:
                matches[str(artist["id"])] = artist
                break
            if artist_name and user_name and artist_name == user_name:
                matches[str(artist["id"])] = artist
                break
        if artist_name in {"josh daniels", "joshua daniels"}:
            matches[str(artist["id"])] = artist

    if len(matches) == 1:
        return next(iter(matches.values()))
    if len(matches) > 1:
        named = [
            row
            for row in matches.values()
            if _normalized(row.get("name")) in {"josh daniels", "joshua daniels"}
        ]
        if len(named) == 1:
            return named[0]
        return None

    non_sim = [
        row
        for row in artists
        if not str(row.get("id") or "").lower().startswith((SIM_PREFIX, "test_", "demo_"))
    ]
    if len(non_sim) == 1:
        return non_sim[0]
    if len(non_sim) > 1:
        return None

    return None


def _customer_is_test(row) -> bool:
    customer_id = str(row.get("id") or "").lower()
    name = _normalized(row.get("name"))
    email = _normalized(row.get("email"))
    phone = str(row.get("phone") or "").strip().lower()
    if customer_id.startswith((SIM_PREFIX, "test_", "demo_")):
        return True
    if name.startswith("sim customer "):
        return True
    if name in {"test", "test customer", "demo customer", "simulation customer"}:
        return True
    if name.startswith("test ") or name.startswith("demo test "):
        return True
    if email.endswith("@example.test") or email.endswith(".test"):
        return True
    if phone.startswith("+155500"):
        return True
    return False


def _lead_is_test(row, test_customer_ids: set[str]) -> bool:
    lead_id = str(row.get("id") or "").lower()
    source = _normalized(row.get("source"))
    customer_id = str(row.get("customer_id") or "")
    if customer_id in test_customer_ids:
        return True
    if lead_id.startswith((SIM_PREFIX, "test_", "demo_")):
        return True
    if source in {"founder_simulation", "simulation", "sim", "test", "demo"}:
        return True
    try:
        profile = json.loads(row.get("profile_json") or "{}")
    except Exception:
        profile = {}
    return profile.get("synthetic") is True or profile.get("test") is True


def _delete_by_ids(conn, table: str, column: str, ids: list[str]) -> int:
    if not ids or not _column_exists(conn, table, column):
        return 0
    marks = ",".join("?" for _ in ids)
    cursor = core.db_execute(conn, f"DELETE FROM {table} WHERE {column} IN ({marks})", ids)
    return max(int(getattr(cursor, "rowcount", 0) or 0), 0)


def preview_cleanup(conn, user, selected_artist_id: str | None = None) -> dict:
    shop = _assert_signed_in_crybaby(conn, user)
    shop_id = shop["id"]
    artists = _artists_for_shop(conn, shop_id)
    founder_artist = _resolve_founder_artist(conn, shop_id, selected_artist_id)

    if founder_artist:
        remove_artists = [row for row in artists if row["id"] != founder_artist["id"]]
    else:
        remove_artists = []

    customers = core.db_fetchall(
        conn,
        "SELECT id,name,phone,email FROM customers WHERE shop_id=? ORDER BY name",
        (shop_id,),
    )
    test_customers = [dict(row) for row in customers if _customer_is_test(row)]
    test_customer_ids = {row["id"] for row in test_customers}

    leads = []
    if _table_exists(conn, "concierge_leads"):
        leads = core.db_fetchall(
            conn,
            "SELECT id,customer_id,source,profile_json FROM concierge_leads WHERE shop_id=? ORDER BY created_at DESC",
            (shop_id,),
        )
    test_leads = [dict(row) for row in leads if _lead_is_test(row, test_customer_ids)]

    return {
        "shop": dict(shop),
        "artists": artists,
        "founder_artist": dict(founder_artist) if founder_artist else None,
        "remove_artists": remove_artists,
        "test_customers": test_customers,
        "test_leads": test_leads,
        "selected_artist_id": selected_artist_id or "",
    }


def execute_cleanup(conn, user, selected_artist_id: str) -> dict:
    preview = preview_cleanup(conn, user, selected_artist_id)
    if not preview["founder_artist"]:
        raise RuntimeError("Choose the Crybaby artist record that should be kept")

    shop_id = preview["shop"]["id"]
    keep_artist_id = preview["founder_artist"]["id"]
    remove_artist_ids = [row["id"] for row in preview["remove_artists"]]
    test_customer_ids = [row["id"] for row in preview["test_customers"]]
    test_lead_ids = [row["id"] for row in preview["test_leads"]]

    opening_ids = []
    if remove_artist_ids and _column_exists(conn, "openings", "artist_id"):
        marks = ",".join("?" for _ in remove_artist_ids)
        rows = core.db_fetchall(
            conn,
            f"SELECT id FROM openings WHERE shop_id=? AND artist_id IN ({marks})",
            [shop_id, *remove_artist_ids],
        )
        opening_ids = [row["id"] for row in rows]

    if opening_ids:
        if _column_exists(conn, "google_booking_events", "booking_id") and _column_exists(conn, "bookings", "opening_id"):
            marks = ",".join("?" for _ in opening_ids)
            core.db_execute(
                conn,
                f"DELETE FROM google_booking_events WHERE booking_id IN (SELECT id FROM bookings WHERE opening_id IN ({marks}))",
                opening_ids,
            )
        _delete_by_ids(conn, "bookings", "opening_id", opening_ids)
        _delete_by_ids(conn, "offers", "opening_id", opening_ids)
        _delete_by_ids(conn, "openings", "id", opening_ids)

    _delete_by_ids(conn, "artist_calendar_connections", "artist_id", remove_artist_ids)
    _delete_by_ids(conn, "founder_sim_artist_portfolios", "artist_id", remove_artist_ids)
    removed_artists = _delete_by_ids(conn, "artists", "id", remove_artist_ids)

    removed_leads = _delete_by_ids(conn, "concierge_leads", "id", test_lead_ids)

    for table in (
        "bookings",
        "offers",
        "customer_suppressions",
        "demand_profiles",
        "demand_signals",
        "enrichment_context",
        "enrichment_locations",
    ):
        _delete_by_ids(conn, table, "customer_id", test_customer_ids)
    removed_customers = _delete_by_ids(conn, "customers", "id", test_customer_ids)

    for table in (
        "founder_sim_customer_learning",
        "founder_sim_outcomes",
        "founder_sim_metrics",
        "founder_sim_recommendations",
        "founder_sim_runs",
    ):
        if _column_exists(conn, table, "shop_id"):
            core.db_execute(conn, f"DELETE FROM {table} WHERE shop_id=?", (shop_id,))

    if _column_exists(conn, "events", "entity_id"):
        core.db_execute(conn, "DELETE FROM events WHERE entity_id LIKE ?", (SIM_PREFIX + "%",))

    conn.commit()

    remaining_artists = core.db_fetchall(
        conn,
        "SELECT id,name FROM artists WHERE shop_id=? ORDER BY name",
        (shop_id,),
    )
    remaining_test_customers = core.db_fetchall(
        conn,
        "SELECT id,name,phone,email FROM customers WHERE shop_id=?",
        (shop_id,),
    )
    remaining_test_customers = [row for row in remaining_test_customers if _customer_is_test(row)]

    remaining_test_leads = []
    if _table_exists(conn, "concierge_leads"):
        rows = core.db_fetchall(
            conn,
            "SELECT id,customer_id,source,profile_json FROM concierge_leads WHERE shop_id=?",
            (shop_id,),
        )
        remaining_test_leads = [row for row in rows if _lead_is_test(row, set())]

    return {
        "shop_name": preview["shop"]["name"],
        "kept_artist_id": keep_artist_id,
        "kept_artist_name": preview["founder_artist"]["name"],
        "removed_artists": removed_artists,
        "removed_test_customers": removed_customers,
        "removed_test_concierge_leads": removed_leads,
        "removed_artist_openings": len(opening_ids),
        "remaining_artists": [dict(row) for row in remaining_artists],
        "remaining_test_customers": len(remaining_test_customers),
        "remaining_test_concierge_leads": len(remaining_test_leads),
    }


def _e(value) -> str:
    return html.escape(str(value or ""), quote=True)


def _page(preview: dict, result: dict | None = None, error: str = "") -> str:
    founder = preview.get("founder_artist")
    artist_options = "".join(
        f"<label class='artist-option'><input type='radio' name='keep_artist_id' value='{_e(row['id'])}' {'checked' if founder and row['id'] == founder['id'] else ''} required><span><b>{_e(row.get('name') or 'Unnamed artist')}</b><small>{_e(row.get('email') or '')}<br><code>{_e(row['id'])}</code></small></span></label>"
        for row in preview["artists"]
    ) or "<p>No artist records were found.</p>"

    artist_rows = "".join(
        f"<li>{_e(row['name'])} <code>{_e(row['id'])}</code></li>"
        for row in preview["remove_artists"]
    ) or "<li>None</li>"
    customer_rows = "".join(
        f"<li>{_e(row['name'])} <code>{_e(row['id'])}</code></li>"
        for row in preview["test_customers"][:100]
    ) or "<li>None</li>"

    result_html = ""
    if result:
        result_html = f"""
        <section class='ok'><h2>Cleanup completed</h2>
        <p>Kept artist: <b>{_e(result['kept_artist_name'])}</b></p>
        <p>Removed artists: <b>{result['removed_artists']}</b> · Test customers: <b>{result['removed_test_customers']}</b> · Test Concierge leads: <b>{result['removed_test_concierge_leads']}</b></p>
        <p>Remaining artists: <b>{len(result['remaining_artists'])}</b> · Remaining detected test customers: <b>{result['remaining_test_customers']}</b> · Remaining detected test leads: <b>{result['remaining_test_concierge_leads']}</b></p></section>"""
    error_html = f"<section class='bad'><b>{_e(error)}</b></section>" if error else ""

    if founder:
        keep_summary = f"<p><b>{_e(founder['name'])}</b> <code>{_e(founder['id'])}</code></p>"
        removal_summary = f"<section class='card'><h2>Other Crybaby artists to remove ({len(preview['remove_artists'])})</h2><ul>{artist_rows}</ul></section>"
    else:
        keep_summary = "<p>We could not safely determine which artist record is yours. Select it below.</p>"
        removal_summary = ""

    return f"""<!doctype html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>Crybaby Cleanup · Empty Chair</title>
    <style>
    body{{margin:0;background:#080a08;color:#f0eadf;font-family:Inter,system-ui,sans-serif}}main{{max-width:880px;margin:auto;padding:28px}}h1{{font-size:38px;margin:6px 0 8px}}h2{{font-size:18px}}.ey{{color:#d8ff45;font:700 11px ui-monospace,monospace;letter-spacing:.12em}}.card,.ok,.bad{{border:1px solid #30362e;background:#0f120f;padding:18px;margin:14px 0}}.ok{{border-color:#7aa321}}.bad{{border-color:#b94d4d}}code{{color:#aab3a7;font-size:11px}}ul{{line-height:1.7}}input[type=text]{{width:100%;box-sizing:border-box;background:#090b09;color:#fff;border:1px solid #3a4237;padding:13px;margin:8px 0 12px}}button{{background:#d8ff45;color:#10130f;border:0;padding:13px 16px;font-weight:900;cursor:pointer}}a{{color:#d8ff45}}.artist-option{{display:flex;gap:12px;align-items:flex-start;border:1px solid #30362e;padding:14px;margin:10px 0;cursor:pointer}}.artist-option input{{margin-top:5px;transform:scale(1.25)}}.artist-option span{{display:block}}.artist-option small{{display:block;color:#aab3a7;margin-top:4px;line-height:1.4}}
    </style></head><body><main>
    <div class='ey'>FOUNDER MAINTENANCE</div><h1>Crybaby Cleanup</h1><p>Signed-in shop: <b>{_e(preview['shop']['name'])}</b></p>{error_html}{result_html}
    <section class='card'><h2>Choose the artist record to keep</h2>{keep_summary}<form method='post'>{artist_options}</section>
    {removal_summary}
    <section class='card'><h2>Detected sim/test customers ({len(preview['test_customers'])})</h2><ul>{customer_rows}</ul><p>Detected sim/test Concierge leads: <b>{len(preview['test_leads'])}</b></p></section>
    <section class='card'><h2>Run cleanup</h2><p>This only affects the signed-in Crybaby shop. The artist you select is preserved. Real customers not matching the test/simulation markers are left alone.</p>
    <label>Type <b>{CONFIRM_PHRASE}</b> to confirm.</label><input type='text' name='confirmation' autocomplete='off' required><button type='submit'>Clean Crybaby Data</button></form></section>
    <p><a href='/'>← Back to Empty Chair</a></p></main></body></html>"""


@core.app.get("/admin/crybaby-cleanup", response_class=HTMLResponse)
def crybaby_cleanup_screen(request: Request):
    user, redirect = core.login_required_redirect(request)
    if redirect:
        return redirect
    conn = core.connect()
    try:
        preview = preview_cleanup(conn, user)
        conn.rollback()
        return HTMLResponse(_page(preview), headers={"Cache-Control": "no-store"})
    except Exception as exc:
        conn.rollback()
        return HTMLResponse(
            f"<html><body style='background:#080a08;color:#fff;font-family:system-ui;padding:30px'><h1>Crybaby cleanup unavailable</h1><pre>{_e(type(exc).__name__ + ': ' + str(exc))}</pre><a style='color:#d8ff45' href='/'>Back</a></body></html>",
            status_code=403,
            headers={"Cache-Control": "no-store"},
        )
    finally:
        conn.close()


@core.app.post("/admin/crybaby-cleanup", response_class=HTMLResponse)
def crybaby_cleanup_execute(
    request: Request,
    confirmation: str = Form(...),
    keep_artist_id: str = Form(...),
):
    user, redirect = core.login_required_redirect(request)
    if redirect:
        return redirect
    conn = core.connect()
    try:
        preview = preview_cleanup(conn, user, keep_artist_id)
        if str(confirmation or "").strip().upper() != CONFIRM_PHRASE:
            conn.rollback()
            return HTMLResponse(
                _page(preview, error="Confirmation phrase did not match. Nothing was deleted."),
                status_code=400,
                headers={"Cache-Control": "no-store"},
            )
        result = execute_cleanup(conn, user, keep_artist_id)
        refreshed = preview_cleanup(conn, user, keep_artist_id)
        conn.rollback()
        return HTMLResponse(_page(refreshed, result=result), headers={"Cache-Control": "no-store"})
    except Exception as exc:
        conn.rollback()
        try:
            preview = preview_cleanup(conn, user, keep_artist_id)
            conn.rollback()
            return HTMLResponse(
                _page(preview, error=type(exc).__name__ + ": " + str(exc)),
                status_code=500,
                headers={"Cache-Control": "no-store"},
            )
        except Exception:
            return HTMLResponse(
                f"<html><body style='background:#080a08;color:#fff;font-family:system-ui;padding:30px'><h1>Crybaby cleanup failed</h1><pre>{_e(type(exc).__name__ + ': ' + str(exc))}</pre><a style='color:#d8ff45' href='/'>Back</a></body></html>",
                status_code=500,
                headers={"Cache-Control": "no-store"},
            )
    finally:
        conn.close()
