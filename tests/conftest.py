import os


# Set isolation before pytest imports any application module. Several unit
# tests import Calendar helpers during collection, which also import app.py.
os.environ["EMPTY_CHAIR_DB"] = "test_empty_chair.db"
os.environ["EMPTY_CHAIR_DEMO_MODE"] = "true"
os.environ["EMPTY_CHAIR_SESSION_SECRET"] = "test-secret"
os.environ["EMPTY_CHAIR_WORKER_ENABLED"] = "false"
os.environ.pop("DATABASE_URL", None)
