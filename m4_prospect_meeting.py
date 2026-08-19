"""Dedicated prospect entrypoint for tonight's M4 Meeting.

This deliberately uses the Gemini Live prospect mode so the experience does not depend
on OpenAI realtime credits. It remains isolated from Josh's relationship memory.
"""

from fastapi import Request
from fastapi.responses import HTMLResponse, RedirectResponse

import app as core


@core.app.get("/meet-m4")
def meet_m4(request: Request):
    user, redirect = core.login_required_redirect(request)
    if redirect:
        return redirect
    return RedirectResponse("/m4-lab?guest=prospect", status_code=307)


@core.app.get("/meet-m4/ready", response_class=HTMLResponse)
def meet_m4_ready(request: Request):
    user, redirect = core.login_required_redirect(request)
    if redirect:
        return redirect
    return HTMLResponse(
        """<!doctype html>
<html lang=\"en\"><head><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width,initial-scale=1\"><title>The Meeting</title>
<style>html,body{margin:0;height:100%;background:#f3f3ef;color:#1b1d19;font-family:system-ui,sans-serif}.wrap{height:100%;display:grid;place-items:center;padding:24px;box-sizing:border-box}.inner{text-align:center;max-width:520px}h1{font:500 30px Georgia,serif;margin:0 0 12px}p{color:#73786f;font:13px/1.6 ui-monospace,monospace;margin:0 0 24px}a{display:inline-block;color:#252821;text-decoration:none;border:1px solid #c8cbc2;border-radius:999px;padding:14px 24px;font:500 19px Georgia,serif}</style></head>
<body><main class=\"wrap\"><section class=\"inner\"><h1>The Meeting</h1><p>M4 is present. This first meeting is isolated from the creator relationship and uses the Gemini realtime path.</p><a href=\"/m4-lab?guest=prospect\">Enter</a></section></main></body></html>"""
    )
