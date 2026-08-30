"""Foreign-key aware delete patch for the authenticated Crybaby cleanup tool.

The cleanup already scopes deletion to the signed-in Crybaby shop and explicit
sim/test records. This patch makes each targeted delete remove dependent rows
first, following PostgreSQL foreign-key metadata, instead of disabling
constraints or guessing table order.
"""

from __future__ import annotations

import re

import app as core
import crybaby_cleanup_once as cleanup

_ORIGINAL_DELETE_BY_IDS = cleanup._delete_by_ids
_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _safe_ident(value: str) -> str:
    text = str(value or "")
    if not _IDENT.fullmatch(text):
        raise RuntimeError(f"Unsafe database identifier: {text!r}")
    return text


def _fk_children(conn, parent_table: str):
    if not getattr(core, "USE_POSTGRES", False):
        return []
    return core.db_fetchall(
        conn,
        """
        SELECT
            tc.table_name AS child_table,
            kcu.column_name AS child_column,
            ccu.column_name AS parent_column
        FROM information_schema.table_constraints tc
        JOIN information_schema.key_column_usage kcu
          ON tc.constraint_name = kcu.constraint_name
         AND tc.constraint_schema = kcu.constraint_schema
        JOIN information_schema.constraint_column_usage ccu
          ON tc.constraint_name = ccu.constraint_name
         AND tc.constraint_schema = ccu.constraint_schema
        WHERE tc.constraint_type = 'FOREIGN KEY'
          AND tc.table_schema = 'public'
          AND ccu.table_schema = 'public'
          AND ccu.table_name = ?
        ORDER BY tc.table_name, kcu.ordinal_position
        """,
        (parent_table,),
    )


def _distinct_parent_values(conn, table: str, filter_column: str, ids: list[str], parent_column: str):
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
    return [row["value"] for row in rows if row.get("value") is not None]


def _delete_with_dependencies(conn, table: str, column: str, ids: list[str], _path=None) -> int:
    if not ids or not cleanup._column_exists(conn, table, column):
        return 0

    if not getattr(core, "USE_POSTGRES", False):
        return _ORIGINAL_DELETE_BY_IDS(conn, table, column, ids)

    table = _safe_ident(table)
    column = _safe_ident(column)
    path = set(_path or set())
    signature = (table, column, tuple(sorted(str(v) for v in ids)))
    if signature in path:
        raise RuntimeError(f"Crybaby cleanup refused: cyclic foreign-key dependency at {table}.{column}")
    path.add(signature)

    for fk in _fk_children(conn, table):
        child_table = _safe_ident(fk["child_table"])
        child_column = _safe_ident(fk["child_column"])
        parent_column = _safe_ident(fk["parent_column"])
        parent_values = _distinct_parent_values(conn, table, column, ids, parent_column)
        if parent_values:
            _delete_with_dependencies(
                conn,
                child_table,
                child_column,
                parent_values,
                path,
            )

    return _ORIGINAL_DELETE_BY_IDS(conn, table, column, ids)


cleanup._delete_by_ids = _delete_with_dependencies
print("Crybaby cleanup FK dependency patch loaded", flush=True)
