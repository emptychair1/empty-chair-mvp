"""Empty Chair 2.0 production bootstrap.

Render must import only the headless 2.0 application. Legacy modules remain in the
repository for history/rollback but are intentionally not imported.
"""
from v2_app import app

print("Empty Chair 2.0 bootstrap loaded")
