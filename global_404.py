"""Branded global 404 handling for the production app."""
from fastapi import Request
import app as core

@core.app.exception_handler(404)
async def empty_chair_not_found(request: Request, exc):
    return core.templates.TemplateResponse(request=request, name="404.html", context={"request": request}, status_code=404, headers={"Cache-Control": "no-store"})
