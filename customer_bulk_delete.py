"""Authenticated bulk deletion for the Customer Intelligence list."""

from __future__ import annotations

import re

from fastapi import Request
from fastapi.responses import HTMLResponse, RedirectResponse

import app as core

_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _safe_ident(value: str) -> str:
    text = str(value or "")
    if not _IDENT.fullmatch(text):
        raise RuntimeError(f"Unsafe database identifier: {text!r}")
    return text


def _column_exists(conn, table: str, column: str) -> bool:
    table = _safe_ident(table)
    column = _safe_ident(column)
    if getattr(core, "USE_POSTGRES", False):
        row = core.db_fetchone(
            conn,
            """
            SELECT 1
            FROM information_schema.columns
            WHERE table_schema='public' AND table_name=? AND column_name=?
            LIMIT 1
            """,
            (table, column),
        )
        return bool(row)
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return any(str(row[1]) == column for row in rows)


def _fk_children(conn, parent_table: str):
    parent_table = _safe_ident(parent_table)
    if getattr(core, "USE_POSTGRES", False):
        return core.db_fetchall(
            conn,
            """
            SELECT
                child.relname AS child_table,
                child_att.attname AS child_column,
                parent_att.attname AS parent_column
            FROM pg_constraint con
            JOIN pg_class child ON child.oid = con.conrelid
            JOIN pg_class parent ON parent.oid = con.confrelid
            JOIN pg_namespace child_ns ON child_ns.oid = child.relnamespace
            JOIN pg_namespace parent_ns ON parent_ns.oid = parent.relnamespace
            JOIN LATERAL unnest(con.conkey, con.confkey) WITH ORDINALITY
              AS keys(child_attnum, parent_attnum, ord) ON TRUE
            JOIN pg_attribute child_att
              ON child_att.attrelid = child.oid
             AND child_att.attnum = keys.child_attnum
            JOIN pg_attribute parent_att
              ON parent_att.attrelid = parent.oid
             AND parent_att.attnum = keys.parent_attnum
            WHERE con.contype='f'
              AND child_ns.nspname='public'
              AND parent_ns.nspname='public'
              AND parent.relname=?
            ORDER BY child.relname, keys.ord
            """,
            (parent_table,),
        )

    tables = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
    ).fetchall()
    children = []
    for row in tables:
        child_table = _safe_ident(row[0])
        for fk in conn.execute(f"PRAGMA foreign_key_list({child_table})").fetchall():
            if str(fk[2]) == parent_table:
                children.append(
                    {
                        "child_table": child_table,
                        "child_column": str(fk[3]),
                        "parent_column": str(fk[4]),
                    }
                )
    return children


def _parent_values(conn, table: str, filter_column: str, ids: list[str], parent_column: str):
    if not ids:
        return []
    table = _safe_ident(table)
    filter_column = _safe_ident(filter_column)
    parent_column = _safe_ident(parent_column)
    marks = ",".join("?" for _ in ids)
    rows = core.db_fetchall(
        conn,
        f"SELECT DISTINCT {parent_column} AS value FROM {table} WHERE {filter_column} IN ({marks}) AND {parent_column} IS NOT NULL",
        ids,
    )
    values = []
    for row in rows:
        if isinstance(row, dict):
            value = row.get("value")
        else:
            try:
                value = row["value"]
            except Exception:
                value = row[0]
        if value is not None:
            values.append(value)
    return values


def _delete_recursive(conn, table: str, column: str, ids: list[str], path=None) -> int:
    if not ids or not _column_exists(conn, table, column):
        return 0

    table = _safe_ident(table)
    column = _safe_ident(column)
    signature = (table, column, tuple(sorted(str(v) for v in ids)))
    active = set(path or set())
    if signature in active:
        raise RuntimeError(f"Customer deletion refused: cyclic foreign-key dependency at {table}.{column}")
    active.add(signature)

    for fk in _fk_children(conn, table):
        child_table = _safe_ident(fk["child_table"])
        child_column = _safe_ident(fk["child_column"])
        parent_column = _safe_ident(fk["parent_column"])
        values = _parent_values(conn, table, column, ids, parent_column)
        if values:
            _delete_recursive(conn, child_table, child_column, values, active)

    marks = ",".join("?" for _ in ids)
    cursor = core.db_execute(conn, f"DELETE FROM {table} WHERE {column} IN ({marks})", ids)
    return int(cursor.rowcount or 0)


@core.app.post("/customers/delete-selected")
async def delete_selected_customers(request: Request):
    user, redirect = core.login_required_redirect(request)
    if redirect:
        return redirect

    form = await request.form()
    requested = []
    seen = set()
    for value in form.getlist("customer_ids"):
        customer_id = str(value or "").strip()
        if customer_id and customer_id not in seen:
            requested.append(customer_id)
            seen.add(customer_id)

    if not requested:
        return RedirectResponse("/customers", status_code=303)

    conn = core.connect()
    try:
        owned = []
        for customer_id in requested:
            row = core.db_fetchone(
                conn,
                "SELECT id FROM customers WHERE id=? AND shop_id=?",
                (customer_id, user["shop_id"]),
            )
            if row:
                owned.append(customer_id)

        if len(owned) != len(requested):
            conn.rollback()
            return HTMLResponse(
                "<h1>Customer deletion refused</h1><p>One or more selected customers do not belong to this shop.</p><p><a href='/customers'>Back to customers</a></p>",
                status_code=403,
                headers={"Cache-Control": "no-store"},
            )

        _delete_recursive(conn, "customers", "id", owned)
        conn.commit()
        return RedirectResponse("/customers", status_code=303)
    except Exception as exc:
        conn.rollback()
        return HTMLResponse(
            "<h1>Customer deletion failed</h1><pre>" + type(exc).__name__ + ": " + str(exc) + "</pre><p><a href='/customers'>Back to customers</a></p>",
            status_code=409,
            headers={"Cache-Control": "no-store"},
        )
    finally:
        conn.close()
