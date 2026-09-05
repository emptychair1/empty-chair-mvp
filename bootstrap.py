"""Empty Chair 2.0 production bootstrap.

Render imports only the headless 2.0 application plus its phone/PWA surface.
Legacy 1.x modules remain in the repository for history/rollback and are never
imported in production.
"""
from v2_app import app
import v2_pwa  # noqa: F401,E402

print("Empty Chair 2.0 bootstrap loaded")
