"""Ensure Empty Chair feature routes are registered on every Python startup.

Render services created before render.yaml changes can retain an older saved
Start Command such as ``uvicorn app:app``. Importing ``features`` here makes
those additive routes available whether Render launches ``app:app`` or
``features:app``.
"""

try:
    import features  # noqa: F401
except Exception as exc:
    # Never prevent the core application from starting if an optional feature
    # route has an import-time problem. The exception remains visible in logs.
    print(f"Empty Chair feature registration failed: {exc}")
