"""Render entrypoint for Hunter Watchtower with safe public diagnostics."""
from __future__ import annotations

from typing import Any

from hunter.watchtower_service import SCHEMA, _worker_state, app


@app.get("/diagnostics")
def diagnostics() -> dict[str, Any]:
    return {
        "schema": SCHEMA,
        "browser_started": _worker_state.get("browser_started"),
        "authenticated": _worker_state.get("authenticated"),
        "last_heartbeat": _worker_state.get("last_heartbeat"),
        "last_error": _worker_state.get("last_error"),
    }
