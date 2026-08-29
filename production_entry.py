"""Production ASGI entrypoint.

Imports the full Empty Chair bootstrap first, then registers public routes that
must exist on the exact app object served by Uvicorn.
"""

from fastapi import Request
from fastapi.responses import HTMLResponse

import bootstrap
import demand_tattoo_finder  # noqa: F401,E402


app = bootstrap.app


@app.get("/future-demand-demo", response_class=HTMLResponse)
def future_demand_demo(request: Request):
    return bootstrap.core.templates.TemplateResponse(
        request=request,
        name="future_demand_demo.html",
        context={},
    )
