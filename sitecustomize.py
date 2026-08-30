"""Register Empty Chair additive routes and notification integrations at startup.

Render services created before render.yaml changes can retain an older saved
Start Command such as ``uvicorn app:app``. Importing these modules here keeps
features and customer notifications active regardless of which app entrypoint
Render launches.
"""

try:
    import features  # noqa: F401
except Exception as exc:
    # Never prevent the core application from starting if an optional feature
    # route has an import-time problem. The exception remains visible in logs.
    print(f"Empty Chair feature registration failed: {exc}")

try:
    import notifications  # noqa: F401
except Exception as exc:
    # Notification failures should be visible without taking down the app.
    print(f"Empty Chair notification registration failed: {exc}")

try:
    import demand_content  # noqa: F401
    import content_scheduler  # noqa: F401
except Exception as exc:
    # Content routes must still register when Render retains a legacy uvicorn
    # entrypoint such as app:app or bootstrap:app.
    print(f"Empty Chair content route registration failed: {exc}")
