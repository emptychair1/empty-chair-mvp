"""Targeted transport correction layered over the deployed M4 smooth meeting.

The original page increments ``generation`` before recording which generation was
invalidated, so telemetry can mark the replacement generation as stale. It also
invalidates a second time when Gemini acknowledges the interruption even though
human barge-in already stopped playback. This wrapper patches those two exact client
behaviors while leaving the rest of the proven audio/transcript page unchanged.
"""
from fastapi import Request
from fastapi.responses import HTMLResponse

import app as core
import m4_gemini_smooth as original

_OLD_RESET = "function resetAudio(reason='reset'){generation++;evt('generation_invalidated',{reason,new_generation:generation},generation);"
_NEW_RESET = "function resetAudio(reason='reset'){let invalidated=responseGeneration;if(invalidated||invalidated===0)evt('generation_invalidated',{reason,invalidated_generation:invalidated},invalidated);generation++;"
_OLD_ACK = "if(sc.interrupted){evt('gemini_interrupted_ack',{pendingUserEnd,phase});resetAudio('gemini_interrupted_ack');bargeInPending=false;"
_NEW_ACK = "if(sc.interrupted){evt('gemini_interrupted_ack',{pendingUserEnd,phase});bargeInPending=false;"


def _patched_html(response: HTMLResponse) -> HTMLResponse:
    body = response.body.decode('utf-8')
    if _OLD_RESET not in body:
        raise RuntimeError('M4 transport patch target resetAudio was not found')
    if _OLD_ACK not in body:
        raise RuntimeError('M4 transport patch target interruption acknowledgement was not found')
    body = body.replace(_OLD_RESET, _NEW_RESET, 1).replace(_OLD_ACK, _NEW_ACK, 1)
    headers = dict(response.headers)
    headers['Cache-Control'] = 'no-store, no-cache, must-revalidate'
    return HTMLResponse(body, status_code=response.status_code, headers=headers)


def m4_smooth_corrected(request: Request):
    response = original.m4_smooth(request)
    if not isinstance(response, HTMLResponse):
        return response
    return _patched_html(response)


def install():
    """Replace only the /m4-smooth GET route after the original module registers it."""
    routes = core.app.router.routes
    for i, route in enumerate(list(routes)):
        if getattr(route, 'path', None) == '/m4-smooth' and 'GET' in (getattr(route, 'methods', set()) or set()):
            routes.pop(i)
            break
    core.app.add_api_route('/m4-smooth', m4_smooth_corrected, methods=['GET'], response_class=HTMLResponse)


install()
