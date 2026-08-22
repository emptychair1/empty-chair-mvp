"""Public, read-only sales walkthrough for the future-demand story."""

from fastapi import Request
from fastapi.responses import HTMLResponse

import app as core


app = core.app


@app.get("/future-demand-demo", response_class=HTMLResponse)
def future_demand_demo(request: Request):
    return core.templates.TemplateResponse(
        request=request,
        name="future_demand_demo.html",
        context={},
    )
