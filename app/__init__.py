import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LEGACY_APP = ROOT / "app.py"

spec = importlib.util.spec_from_file_location("empty_chair_legacy_app", LEGACY_APP)
if spec is None or spec.loader is None:
    raise RuntimeError("Could not load legacy app.py")

legacy = importlib.util.module_from_spec(spec)
sys.modules["empty_chair_legacy_app"] = legacy
spec.loader.exec_module(legacy)

# Expose the legacy module under the name `app` while feature modules import it.
sys.modules["app"] = legacy

import features  # noqa: E402,F401
import pwa  # noqa: E402,F401
import m4_dashboard  # noqa: E402,F401
import demand_acquisition  # noqa: E402,F401
import demand_channels  # noqa: E402,F401
import demand_compliance  # noqa: E402,F401
import demand_launch  # noqa: E402,F401
import demand_shortlinks  # noqa: E402,F401
import demand_ui  # noqa: E402,F401
import hunter_operator  # noqa: E402,F401

app = legacy.app
