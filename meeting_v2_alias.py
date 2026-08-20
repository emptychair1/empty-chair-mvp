"""Stable public route alias for the isolated Meeting v2 subsystem."""
from fastapi import Request
from fastapi.responses import HTMLResponse

import app as core
import meeting_v2


@core.app.get("/meet-m4", response_class=HTMLResponse)
def meet_m4(request: Request):
    return meeting_v2.meeting_v2_page(request)
