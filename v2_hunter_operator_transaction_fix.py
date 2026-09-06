"""Hotfix Hunter operator DB transaction scoping for Empty Chair 2.0.

V2DB uses SET LOCAL search_path, so helper code must not commit before the caller
finishes its queries. This patch replaces Sprint 9's table helper with a no-commit
version; callers already commit after their complete operation.
"""
from __future__ import annotations

import v2_hunter_operator as hunter_operator


def ensure_tables_same_transaction(db) -> None:
    for stmt in (
        hunter_operator.TARGET_TABLE,
        hunter_operator.META_TABLE,
        hunter_operator.AUDIT_TABLE,
    ):
        db.execute(stmt)


hunter_operator.ensure_tables = ensure_tables_same_transaction

print("Hunter operator transaction scope fix loaded", flush=True)
