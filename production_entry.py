"""Production ASGI entrypoint.

Imports the full Empty Chair bootstrap first, then registers public routes that
must exist on the exact app object served by Uvicorn.
"""

from fastapi import Request
from fastapi.responses import HTMLResponse

import bootstrap
import crybaby_cleanup_once  # noqa: F401,E402
import crybaby_cleanup_fk_patch  # noqa: F401,E402
import customer_bulk_delete  # noqa: F401,E402
import pwa_branding  # noqa: F401,E402
import contest  # noqa: F401,E402
import contest_runtime_fix  # noqa: F401,E402
import demand_tattoo_finder  # noqa: F401,E402
import demand_shortlinks  # noqa: F401,E402
import concierge_campaign_repair  # noqa: F401,E402
import demand_content  # noqa: F401,E402
import content_scheduler  # noqa: F401,E402
import demand_read_api  # noqa: F401,E402
import global_404  # noqa: F401,E402


app = bootstrap.app


@app.get("/future-demand-demo", response_class=HTMLResponse)
def future_demand_demo(request: Request):
    return bootstrap.core.templates.TemplateResponse(
        request=request,
        name="future_demand_demo.html",
        context={},
    )
