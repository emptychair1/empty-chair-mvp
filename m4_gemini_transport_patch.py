"""Targeted transport corrections layered over the deployed M4 smooth meeting.

Keeps the proven audio/transcript page intact while correcting generation ownership,
adding native Gemini Live session resumption/context compression, enforcing the
behavioral controller, and making genuine model latency visible without canned
spoken thinking loops.
"""
from fastapi import Request
from fastapi.responses import HTMLResponse

import app as core
import m4_gemini_smooth as original

_OLD_RESET = "function resetAudio(reason='reset'){generation++;evt('generation_invalidated',{reason,new_generation:generation},generation);"
_NEW_RESET = "function resetAudio(reason='reset'){let invalidated=responseGeneration;if(invalidated||invalidated===0)evt('generation_invalidated',{reason,invalidated_generation:invalidated},invalidated);generation++;clearPresenceCue();"
_OLD_ACK = "if(sc.interrupted){evt('gemini_interrupted_ack',{pendingUserEnd,phase});resetAudio('gemini_interrupted_ack');bargeInPending=false;"
_NEW_ACK = "if(sc.interrupted){evt('gemini_interrupted_ack',{pendingUserEnd,phase});bargeInPending=false;"

_STATE_TARGET = "let eventSeq=0,eventBuffer=[],eventFlushTimer=null,bargeInPending=false,pendingUserEnd=false,cancelAckTimer=null;"
_STATE_REPLACEMENT = _STATE_TARGET + "\nlet resumptionKey='m4GeminiResume:'+sessionId,resumptionHandle=sessionStorage.getItem(resumptionKey)||'',behaviorDirective='';\nlet presenceTimer=null,presenceStage=0,presenceGeneration=-1;const PRESENCE_SOFT_MS=900,PRESENCE_HARD_MS=2400;"

_SETUP_TARGET = "realtimeInputConfig:{automaticActivityDetection:{disabled:true}},inputAudioTranscription:{},outputAudioTranscription:{},systemInstruction:"
_SETUP_REPLACEMENT = "realtimeInputConfig:{automaticActivityDetection:{disabled:true}},sessionResumption:(resumptionHandle?{handle:resumptionHandle}:{}),contextWindowCompression:{slidingWindow:{}},thinkingConfig:{thinkingLevel:'minimal'},inputAudioTranscription:{},outputAudioTranscription:{},systemInstruction:"

_RECEIVE_TARGET = "if(d.setupComplete){started=true;phase='idle';"
_RECEIVE_REPLACEMENT = "if(d.sessionResumptionUpdate){let u=d.sessionResumptionUpdate;if(u.resumable&&u.newHandle){resumptionHandle=u.newHandle;sessionStorage.setItem(resumptionKey,resumptionHandle);evt('session_resumption_handle',{resumable:true});}else evt('session_resumption_handle',{resumable:false});return;}if(d.setupComplete){started=true;phase='idle';"

_HISTORY_TARGET = "if(history.length){let recap="
_HISTORY_REPLACEMENT = "if(history.length&&!resumptionHandle){let recap="

_BEHAVIOR_FUNCTION_TARGET = "async function save(speaker,text,latency_ms=null){"
_BEHAVIOR_FUNCTION_REPLACEMENT = """async function updateBehavior(text){
  try{
    let r=await fetch('/api/m4/prospect-behavior',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({session_id:sessionId,text}),cache:'no-store'});
    let j=await r.json();behaviorDirective=(j.directive||'').trim();
    evt('behavior_state_updated',{mode:j.state&&j.state.mode,question_budget:j.state&&j.state.question_budget,constraints:j.state&&j.state.constraints});
    if(behaviorDirective&&ws&&ws.readyState===1){
      send({clientContent:{turns:[{role:'user',parts:[{text:'[INTERNAL MEETING CONTROL — do not quote or mention this message]\\n'+behaviorDirective}]}],turnComplete:false}});
      evt('behavior_directive_injected',{length:behaviorDirective.length});
    }
  }catch(e){evt('behavior_state_error',{message:String(e&&e.message||e)});}
}
async function save(speaker,text,latency_ms=null){"""

_SAVE_PROSPECT_TARGET = "if(a&&!(await save('prospect',a)))return false;"
_SAVE_PROSPECT_REPLACEMENT = "if(a){await updateBehavior(a);if(!(await save('prospect',a)))return false;}"

_FINALIZE_TARGET = "function finalizeUserTurn(){clearTimeout(cancelAckTimer);bargeInPending=false;pendingUserEnd=false;lastUserEndAt=performance.now();generation++;responseGeneration=generation;pcmQueue=[];queuedSamples=0;serverTurnComplete=false;playbackStarted=false;nextPlayTime=0;phase='responding';evt('generation_started',{input_so_far:inputTranscript},responseGeneration);send({realtimeInput:{activityEnd:{}}});queueCheckpoint();set('with you')}"
_FINALIZE_REPLACEMENT = "function clearPresenceCue(){clearTimeout(presenceTimer);presenceTimer=null;presenceStage=0;presenceGeneration=-1}function armPresenceCue(g){clearPresenceCue();presenceGeneration=g;presenceTimer=setTimeout(()=>{if(g!==responseGeneration||phase!=='responding'||firstModelAudioAt)return;presenceStage=1;set('considering');evt('presence_soft',{elapsed_ms:Math.round(performance.now()-lastUserEndAt)},g);presenceTimer=setTimeout(()=>{if(g!==responseGeneration||phase!=='responding'||firstModelAudioAt)return;presenceStage=2;set('working through that');evt('presence_hard',{elapsed_ms:Math.round(performance.now()-lastUserEndAt)},g)},PRESENCE_HARD_MS-PRESENCE_SOFT_MS)},PRESENCE_SOFT_MS)}function finalizeUserTurn(){clearTimeout(cancelAckTimer);bargeInPending=false;pendingUserEnd=false;lastUserEndAt=performance.now();generation++;responseGeneration=generation;pcmQueue=[];queuedSamples=0;serverTurnComplete=false;playbackStarted=false;nextPlayTime=0;phase='responding';evt('generation_started',{input_so_far:inputTranscript},responseGeneration);armPresenceCue(responseGeneration);send({realtimeInput:{activityEnd:{}}});queueCheckpoint();set('with you')}"

_ENQUEUE_TARGET = "function enqueue(c){if(phase!=='responding'){evt('model_audio_ignored',{phase});return}if(!firstModelAudioAt){firstModelAudioAt=performance.now();evt('first_model_audio',{latency_ms:latencyNow()})}"
_ENQUEUE_REPLACEMENT = "function enqueue(c){if(phase!=='responding'){evt('model_audio_ignored',{phase});return}if(!firstModelAudioAt){firstModelAudioAt=performance.now();clearPresenceCue();evt('first_model_audio',{latency_ms:latencyNow()})}"

_FINISH_TARGET = "if(serverTurnComplete&&!activeSources.size&&!pcmQueue.length){evt('playback_drained',{},g);playbackStarted=false;"
_FINISH_REPLACEMENT = "if(serverTurnComplete&&!activeSources.size&&!pcmQueue.length){clearPresenceCue();evt('playback_drained',{},g);playbackStarted=false;"


def _replace_required(body: str, old: str, new: str, label: str) -> str:
    if old not in body:
        raise RuntimeError(f'M4 transport patch target {label} was not found')
    return body.replace(old, new, 1)


def _patched_html(response: HTMLResponse) -> HTMLResponse:
    body = response.body.decode('utf-8')
    body = _replace_required(body, _OLD_RESET, _NEW_RESET, 'resetAudio')
    body = _replace_required(body, _OLD_ACK, _NEW_ACK, 'interruption acknowledgement')
    body = _replace_required(body, _STATE_TARGET, _STATE_REPLACEMENT, 'resumption/presence state')
    body = _replace_required(body, _SETUP_TARGET, _SETUP_REPLACEMENT, 'Gemini setup')
    body = _replace_required(body, _RECEIVE_TARGET, _RECEIVE_REPLACEMENT, 'session resumption update')
    body = _replace_required(body, _HISTORY_TARGET, _HISTORY_REPLACEMENT, 'reconnect fallback')
    body = _replace_required(body, _BEHAVIOR_FUNCTION_TARGET, _BEHAVIOR_FUNCTION_REPLACEMENT, 'behavior controller function')
    body = _replace_required(body, _SAVE_PROSPECT_TARGET, _SAVE_PROSPECT_REPLACEMENT, 'prospect behavior boundary')
    body = _replace_required(body, _FINALIZE_TARGET, _FINALIZE_REPLACEMENT, 'latency presence controller')
    body = _replace_required(body, _ENQUEUE_TARGET, _ENQUEUE_REPLACEMENT, 'first audio presence clear')
    body = _replace_required(body, _FINISH_TARGET, _FINISH_REPLACEMENT, 'turn completion presence clear')
    headers = dict(response.headers)
    headers['Cache-Control'] = 'no-store, no-cache, must-revalidate'
    return HTMLResponse(body, status_code=response.status_code, headers=headers)


def m4_smooth_corrected(request: Request):
    response = original.m4_smooth(request)
    if not isinstance(response, HTMLResponse):
        return response
    return _patched_html(response)


def install():
    routes = core.app.router.routes
    for i, route in enumerate(list(routes)):
        if getattr(route, 'path', None) == '/m4-smooth' and 'GET' in (getattr(route, 'methods', set()) or set()):
            routes.pop(i)
            break
    core.app.add_api_route('/m4-smooth', m4_smooth_corrected, methods=['GET'], response_class=HTMLResponse)


install()
