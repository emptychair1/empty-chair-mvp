"""Final deterministic M4 operator route.

Loaded last by bootstrap. Wraps v2 with:
- the exact production logo asset plus text fallback;
- a visible build marker so deployed code is obvious;
- preview fallback across available openings so one bad opening cannot stop the run;
- no dependency on narration completing before reasoning advances.
"""
from fastapi import Request
from fastapi.responses import HTMLResponse

import app as core
import m4_operator_v2

BUILD = "M4-OPERATOR-V3"


def page(request: Request):
    user, redirect = core.login_required_redirect(request)
    if redirect:
        return redirect

    html = m4_operator_v2._HTML

    html = html.replace(
        '<img src="/static/D8F5F51D-90EE-45DE-9D95-DB078BDEB87E.png?v=4" alt="Empty Chair">',
        '<img src="/static/D8F5F51D-90EE-45DE-9D95-DB078BDEB87E.png?v=m4v3" alt="Empty Chair" onerror="this.style.display=\'none\';this.nextElementSibling.style.display=\'block\'"><span class="logo-fallback" style="display:none;font:400 30px var(--brand);color:var(--cream)">EMPTY CHAIR</span>',
    )

    html = html.replace(
        '<span>RANK · EXPLAIN · ACT · LEARN</span>',
        '<span>RANK · EXPLAIN · ACT · LEARN · <b style="color:var(--cream-dim)">M4-OPERATOR-V3</b></span>',
    )

    old = "const p=await preview(selected);const ranked=p.m4_top_candidates||[];if(!ranked.length)throw Error('No eligible customer candidates');"
    new = "let p=null,ranked=[],chosen=selected,lastPreviewError='';const ordered=[...(data.openings||[])].sort((a,b)=>Number(b.price||0)-Number(a.price||0));for(const candidateOpening of ordered){try{const attempt=await preview(candidateOpening);const attemptRanked=attempt.m4_top_candidates||[];if(attemptRanked.length){p=attempt;ranked=attemptRanked;chosen=candidateOpening;break}lastPreviewError='No eligible customer candidates for '+(candidateOpening.style||candidateOpening.id)}catch(err){lastPreviewError=(err&&err.message?err.message:String(err));log.textContent+='\\nSkipping opening '+(candidateOpening.style||candidateOpening.id)+': '+lastPreviewError}}if(!ranked.length)throw Error(lastPreviewError||'No eligible customer candidates across open chair inventory');document.querySelectorAll('.opening').forEach(x=>x.classList.toggle('active',x.dataset.id===chosen.id));"
    html = html.replace(old, new)

    html = html.replace(
        "voice.textContent='M4 VOICE // speaking';",
        "voice.textContent='M4 VOICE // custom Voice Design · '+(j.voice_id||'unknown');",
    )

    return HTMLResponse(
        html,
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
            "X-M4-Operator-Build": BUILD,
        },
    )


def install():
    replaced = False
    for route in core.app.routes:
        if getattr(route, "path", None) == "/m4-operator-live" and getattr(route, "methods", None) and "GET" in route.methods:
            route.endpoint = page
            replaced = True
    return replaced
