"""Durable behavioral state for isolated M4 prospect meetings.

This is a deterministic controller above the language model. Explicit prospect
corrections become durable meeting constraints rather than prompt suggestions.
"""
from __future__ import annotations

import json
import re
import uuid

from fastapi import Request
from fastapi.responses import JSONResponse

import app as core
import m4_prospect_transcript as transcript

LEAD = re.compile(r"\b(take over|show me|prove it|stop asking|do not ask|don't ask|you tell me|don't make me lead|do not make me lead|start talking about solutions)\b", re.I)
PROOF = re.compile(r"\b(prove it|prove that|synthetic data|make up (?:some )?(?:sort of )?data|show me what you would actually do)\b", re.I)
NO_QUESTIONS = re.compile(r"\b(stop asking|do not ask|don't ask|no more questions|stop (?:with )?the questions)\b", re.I)
NO_PITCH = re.compile(r"\b(sales pitch|stop pitching|pitching me|snake oil|buzzwords?|vaporware)\b", re.I)
CONTINUE = re.compile(r"^(?:i['’]?m back[,. ]*)?continue[.! ]*$", re.I)


def _ensure_table(conn):
    transcript._ensure_table(conn)
    core.db_execute(conn, """
        CREATE TABLE IF NOT EXISTS m4_prospect_behavior_state (
            id TEXT PRIMARY KEY,
            shop_id TEXT NOT NULL,
            user_id TEXT NOT NULL,
            session_id TEXT NOT NULL,
            mode TEXT NOT NULL DEFAULT 'DISCOVERY',
            question_budget INTEGER,
            no_permission_seeking INTEGER NOT NULL DEFAULT 0,
            no_sales_pitch INTEGER NOT NULL DEFAULT 0,
            proof_requested INTEGER NOT NULL DEFAULT 0,
            synthetic_data_authorized INTEGER NOT NULL DEFAULT 0,
            continue_exact_thread INTEGER NOT NULL DEFAULT 0,
            constraints_json TEXT NOT NULL DEFAULT '[]',
            last_prospect_text TEXT NOT NULL DEFAULT '',
            updated_at TEXT NOT NULL,
            UNIQUE(user_id, shop_id, session_id)
        )
    """)


def default_state(session_id=''):
    return {
        'session_id': session_id,
        'mode': 'DISCOVERY',
        'question_budget': None,
        'no_permission_seeking': False,
        'no_sales_pitch': False,
        'proof_requested': False,
        'synthetic_data_authorized': False,
        'continue_exact_thread': False,
        'constraints': [],
        'last_prospect_text': '',
    }


def _decode(row, session_id):
    if not row:
        return default_state(session_id)
    state = dict(row)
    state['session_id'] = session_id
    for key in ('no_permission_seeking','no_sales_pitch','proof_requested','synthetic_data_authorized','continue_exact_thread'):
        state[key] = bool(state.get(key))
    try:
        state['constraints'] = json.loads(state.pop('constraints_json') or '[]')
    except Exception:
        state['constraints'] = []
    state.pop('id', None); state.pop('shop_id', None); state.pop('user_id', None); state.pop('updated_at', None)
    return state


def get_state(user, session_id):
    conn = core.connect()
    try:
        _ensure_table(conn)
        row = core.db_fetchone(conn, """
            SELECT * FROM m4_prospect_behavior_state
            WHERE user_id=? AND shop_id=? AND session_id=?
        """, (user['id'], user['shop_id'], session_id))
        return _decode(row, session_id)
    finally:
        conn.close()


def absorb_text(state, text):
    text = (text or '').strip()
    constraints = set(state.get('constraints') or [])
    if LEAD.search(text):
        state['mode'] = 'LEAD'
        state['question_budget'] = 0
        state['no_permission_seeking'] = True
        constraints.add('lead_without_permission_seeking')
    if PROOF.search(text):
        state['mode'] = 'PROOF'
        state['proof_requested'] = True
        state['question_budget'] = 0
        state['no_permission_seeking'] = True
        constraints.add('quantitative_proof')
        if re.search(r"synthetic|make up", text, re.I):
            state['synthetic_data_authorized'] = True
            constraints.add('synthetic_data_authorized')
    if NO_QUESTIONS.search(text):
        state['question_budget'] = 0
        state['no_permission_seeking'] = True
        constraints.add('no_questions')
    if NO_PITCH.search(text):
        state['no_sales_pitch'] = True
        constraints.add('no_sales_pitch')
    state['continue_exact_thread'] = bool(CONTINUE.match(text))
    if state['continue_exact_thread']:
        constraints.add('continue_exact_thread')
    state['constraints'] = sorted(constraints)
    state['last_prospect_text'] = text
    return state


def save_state(user, session_id, state):
    conn = core.connect()
    try:
        _ensure_table(conn)
        now = core.now_iso()
        row = core.db_fetchone(conn, "SELECT id FROM m4_prospect_behavior_state WHERE user_id=? AND shop_id=? AND session_id=?", (user['id'], user['shop_id'], session_id))
        vals = (
            state.get('mode') or 'DISCOVERY', state.get('question_budget'), int(bool(state.get('no_permission_seeking'))),
            int(bool(state.get('no_sales_pitch'))), int(bool(state.get('proof_requested'))), int(bool(state.get('synthetic_data_authorized'))),
            int(bool(state.get('continue_exact_thread'))), json.dumps(state.get('constraints') or []), state.get('last_prospect_text') or '', now,
        )
        if row:
            core.db_execute(conn, """UPDATE m4_prospect_behavior_state SET mode=?,question_budget=?,no_permission_seeking=?,no_sales_pitch=?,proof_requested=?,synthetic_data_authorized=?,continue_exact_thread=?,constraints_json=?,last_prospect_text=?,updated_at=? WHERE id=?""", vals + (row['id'],))
        else:
            core.db_execute(conn, """INSERT INTO m4_prospect_behavior_state(id,shop_id,user_id,session_id,mode,question_budget,no_permission_seeking,no_sales_pitch,proof_requested,synthetic_data_authorized,continue_exact_thread,constraints_json,last_prospect_text,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", (str(uuid.uuid4()), user['shop_id'], user['id'], session_id) + vals)
        conn.commit()
    finally:
        conn.close()


def absorb(user, session_id, text):
    state = absorb_text(get_state(user, session_id), text)
    save_state(user, session_id, state)
    return state


def runtime_directive(state):
    """Compact high-priority content injected only between completed turns."""
    rules = []
    if state.get('question_budget') == 0:
        rules.append('QUESTION BUDGET IS ZERO. Do not ask a question unless progress is literally impossible without one.')
    if state.get('no_permission_seeking'):
        rules.append('Do not ask permission, approval, or whether an idea sounds useful. Take the next useful step.')
    if state.get('no_sales_pitch'):
        rules.append('Sales language is rejected. Demonstrate reasoning or useful work; do not pitch features.')
    if state.get('proof_requested'):
        rules.append('Proof is requested. Use numbers, arithmetic, explicit assumptions, and bounded conclusions.')
    if state.get('synthetic_data_authorized'):
        rules.append('Synthetic data is explicitly authorized. Label every invented fact synthetic and never imply it describes this shop.')
    if state.get('continue_exact_thread'):
        rules.append('Continue the exact unresolved intellectual thread. Do not recap, restart discovery, greet, or ask where you were.')
    if not rules:
        return ''
    return 'M4 LIVE BEHAVIOR CONTROLLER — HARD CONSTRAINTS FOR THE NEXT RESPONSE:\n- ' + '\n- '.join(rules)


@core.app.post('/api/m4/prospect-behavior')
async def prospect_behavior(request: Request):
    user = core.get_current_user(request)
    if not user:
        return JSONResponse({'error':'Sign in first.'}, status_code=401)
    data = await request.json()
    sid = str(data.get('session_id') or '').strip()
    text = str(data.get('text') or '')
    if not sid:
        return JSONResponse({'error':'session_id required'}, status_code=400)
    state = absorb(user, sid, text)
    return JSONResponse({'ok':True,'state':state,'directive':runtime_directive(state)}, headers={'Cache-Control':'no-store'})


@core.app.get('/api/m4/prospect-behavior/{session_id}')
def prospect_behavior_get(request: Request, session_id: str):
    user = core.get_current_user(request)
    if not user:
        return JSONResponse({'error':'Sign in first.'}, status_code=401)
    state = get_state(user, session_id)
    return JSONResponse({'state':state,'directive':runtime_directive(state)}, headers={'Cache-Control':'no-store'})
