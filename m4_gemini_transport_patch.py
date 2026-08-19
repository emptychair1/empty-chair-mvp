"""Targeted transport corrections layered over the deployed M4 smooth meeting.

Keeps the proven audio/transcript page intact while correcting generation ownership
and adding native Gemini Live session resumption/context compression. Transcript
reconstruction remains a fallback only when no resumable Gemini session handle exists.
"""
from fastapi import Request
from fastapi.responses import HTMLResponse

import app as core
import m4_gemini_smooth as original

_OLD_RESET = "function resetAudio(reason='reset'){generation++;evt('generation_invalidated',{reason,new_generation:generation},generation);"
_NEW_RESET = "function resetAudio(reason='reset'){let invalidated=responseGeneration;if(invalidated||invalidated===0)evt('generation_invalidated',{reason,invalidated_generation:invalidated},invalidated);generation++;"
_OLD_ACK = "if(sc.interrupted){evt('gemini_interrupted_ack',{pendingUserEnd,phase});resetAudio('gemini_interrupted_ack');bargeInPending=false;"
_NEW_ACK = "if(sc.interrupted){evt('gemini_interrupted_ack',{pendingUserEnd,phase});bargeInPending=false;"

_STATE_TARGET = "let eventSeq=0,eventBuffer=[],eventFlushTimer=null,bargeInPending=false,pendingUserEnd=false,cancelAckTimer=null;"
_STATE_REPLACEMENT = _STATE_TARGET + "\nlet resumptionKey='m4GeminiResume:'+sessionId,resumptionHandle=sessionStorage.getItem(resumptionKey)||'';"

_SETUP_TARGET = "realtimeInputConfig:{automaticActivityDetection:{disabled:true}},inputAudioTranscription:{},outputAudioTranscription:{},systemInstruction:"
_SETUP_REPLACEMENT = "realtimeInputConfig:{automaticActivityDetection:{disabled:true}},sessionResumption:(resumptionHandle?{handle:resumptionHandle}:{}),contextWindowCompression:{slidingWindow:{}},inputAudioTranscription:{},outputAudioTranscription:{},systemInstruction:"

_RECEIVE_TARGET = "if(d.setupComplete){started=true;phase='idle';"
_RECEIVE_REPLACEMENT = "if(d.sessionResumptionUpdate){let u=d.sessionResumptionUpdate;if(u.resumable&&u.newHandle){resumptionHandle=u.newHandle;sessionStorage.setItem(resumptionKey,resumptionHandle);evt('session_resumption_handle',{resumable:true});}else evt('session_resumption_handle',{resumable:false});return;}if(d.setupComplete){started=true;phase='idle';"

_HISTORY_TARGET = "if(history.length){let recap="
_HISTORY_REPLACEMENT = "if(history.length&&!resumptionHandle){let recap="


def _replace_required(body: str, old: str, new: str, label: str) -> str:
    if old not in body:
        raise RuntimeError(f'M4 transport patch target {label} was not found')
    return body.replace(old, new, 1)


def _patched_html(response: HTMLResponse) -> HTMLResponse:
    body = response.body.decode('utf-8')
    body = _replace_required(body, _OLD_RESET, _NEW_RESET, 'resetAudio')
    body = _replace_required(body, _OLD_ACK, _NEW_ACK, 'interruption acknowledgement')
    body = _replace_required(body, _STATE_TARGET, _STATE_REPLACEMENT, 'resumption state')
    body = _replace_required(body, _SETUP_TARGET, _SETUP_REPLACEMENT, 'Gemini setup')
    body = _replace_required(body, _RECEIVE_TARGET, _RECEIVE_REPLACEMENT, 'session resumption update')
    body = _replace_required(body, _HISTORY_TARGET, _HISTORY_REPLACEMENT, 'reconnect fallback')
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
