"""M4-driven contest follow-up: Concierge collects missing signals; Apprentice sends the SMS."""

from __future__ import annotations

import html
import json
import secrets

from fastapi import Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

import app as core
import contest
import m4_active_learning
import notifications


def _e(value) -> str:
    return html.escape(str(value or ""), quote=True)


def _ensure_table(conn) -> None:
    core.db_execute(
        conn,
        """
        CREATE TABLE IF NOT EXISTS contest_followups (
            token TEXT PRIMARY KEY,
            lead_id TEXT NOT NULL,
            shop_id TEXT NOT NULL,
            requested_fields_json TEXT NOT NULL DEFAULT '[]',
            status TEXT NOT NULL DEFAULT 'pending',
            created_at TEXT NOT NULL,
            completed_at TEXT
        )
        """,
    )
    conn.commit()


def _profile(row) -> dict:
    try:
        return json.loads(row["profile_json"] or "{}")
    except Exception:
        return {}


def _missing_questions(profile: dict) -> list[dict]:
    ranked = m4_active_learning.rank_missing_questions(profile)
    extras = []
    if not str(profile.get("placement") or "").strip():
        extras.append({"key": "placement", "ask": "Where on your body do you want the tattoo?", "placeholder": "Forearm, calf, upper arm…", "options": [], "information_value": 2.0, "reason": "Placement is necessary to judge feasibility and composition."})
    if not str(profile.get("size") or "").strip():
        extras.append({"key": "size", "ask": "About how large do you want it?", "placeholder": "Palm-size, 4 inches, full forearm…", "options": [], "information_value": 1.9, "reason": "Size is necessary to judge feasibility and detail."})
    combined = extras + ranked
    seen = set()
    result = []
    for item in combined:
        if item["key"] in seen:
            continue
        seen.add(item["key"])
        result.append(item)
    return result


def _load_lead(conn, shop_id: str, lead_id: str):
    return core.db_fetchone(
        conn,
        """
        SELECT l.*, c.name, c.phone, c.email, c.communication_consent
        FROM concierge_leads l
        LEFT JOIN customers c ON c.id=l.customer_id AND c.shop_id=l.shop_id
        WHERE l.id=? AND l.shop_id=?
        LIMIT 1
        """,
        (lead_id, shop_id),
    )


def _followup_url(token: str) -> str:
    return f"{core.PUBLIC_BASE_URL.rstrip('/')}/concierge/contest-followup/{token}"


def _send_apprentice_sms(row, token: str, count: int) -> bool:
    first = str(row["name"] or "there").strip().split()[0] or "there"
    body = (
        f"Hey {first} — Empty Chair Concierge needs {count} quick detail"
        f"{'s' if count != 1 else ''} to finish your tattoo contest entry. "
        f"Complete it here: {_followup_url(token)}"
    )
    sent = notifications._send_text(row["phone"], body)
    core.event(
        "apprentice.contest_followup.sent" if sent else "apprentice.contest_followup.not_sent",
        "concierge_lead",
        row["id"],
        json.dumps({"requested_count": count, "sms_live": notifications.SMS_LIVE}),
    )
    return bool(sent)


@core.app.post("/contest/{lead_id}/request-info")
def request_contest_info(request: Request, lead_id: str):
    user, redirect = core.login_required_redirect(request)
    if redirect:
        return redirect
    conn = core.connect()
    try:
        _ensure_table(conn)
        row = _load_lead(conn, user["shop_id"], lead_id)
        if not row:
            return RedirectResponse("/contest", status_code=303)
        profile = _profile(row)
        questions = _missing_questions(profile)
        if not questions:
            core.event("m4.contest_followup.not_needed", "concierge_lead", lead_id, "{}")
            return RedirectResponse("/contest?followup=complete", status_code=303)
        if not row["phone"] or not row["communication_consent"]:
            core.event("m4.contest_followup.blocked", "concierge_lead", lead_id, json.dumps({"reason": "no_sms_consent_or_phone"}))
            return RedirectResponse("/contest?followup=no-consent", status_code=303)

        token = secrets.token_urlsafe(24)
        now = core.now_iso()
        fields = [q["key"] for q in questions]
        core.db_execute(
            conn,
            "INSERT INTO contest_followups(token,lead_id,shop_id,requested_fields_json,status,created_at,completed_at) VALUES (?,?,?,?,?,?,NULL)",
            (token, lead_id, user["shop_id"], json.dumps(fields), "pending", now),
        )
        conn.commit()
        sent = _send_apprentice_sms(row, token, len(fields))
        core.event(
            "m4.contest_followup.requested",
            "concierge_lead",
            lead_id,
            json.dumps({"fields": fields, "sms_sent": sent}),
        )
        return RedirectResponse("/contest?followup=sent" if sent else "/contest?followup=sms-unavailable", status_code=303)
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


@core.app.get("/concierge/contest-followup/{token}", response_class=HTMLResponse)
def contest_followup_page(token: str):
    conn = core.connect()
    try:
        _ensure_table(conn)
        row = core.db_fetchone(
            conn,
            """
            SELECT f.*, l.profile_json, c.name
            FROM contest_followups f
            JOIN concierge_leads l ON l.id=f.lead_id AND l.shop_id=f.shop_id
            LEFT JOIN customers c ON c.id=l.customer_id AND c.shop_id=l.shop_id
            WHERE f.token=? LIMIT 1
            """,
            (token,),
        )
        if not row:
            return HTMLResponse("Entry follow-up link not found.", status_code=404)
        if row["status"] == "completed":
            return HTMLResponse("<!doctype html><html><body style='background:#080a08;color:#f4efe5;font-family:system-ui;padding:32px'><h1>You're all set.</h1><p>Your contest entry is complete.</p></body></html>")
        profile = _profile(row)
        try:
            requested = json.loads(row["requested_fields_json"] or "[]")
        except Exception:
            requested = []
        questions = [q for q in _missing_questions(profile) if q["key"] in requested]
        blocks = []
        for q in questions:
            key = _e(q["key"])
            options = q.get("options") or []
            if options:
                option_html = "".join(f"<option value='{_e(v)}'>{_e(v)}</option>" for v in options)
                field = f"<select name='{key}'><option value=''>Choose…</option>{option_html}</select>"
            else:
                field = f"<input name='{key}' placeholder='{_e(q.get('placeholder') or '')}'>"
            blocks.append(f"<label><span>{_e(q['ask'])}</span>{field}</label>")
        name = _e(row["name"] or "there")
        return HTMLResponse(f"""<!doctype html><html><head><meta name='viewport' content='width=device-width,initial-scale=1'><title>Finish your contest entry · Empty Chair</title><style>body{{margin:0;background:#080a08;color:#f4efe5;font-family:Inter,system-ui,sans-serif}}main{{max-width:620px;margin:auto;padding:28px 20px 70px}}.ey{{color:#b8ff24;font:900 11px ui-monospace,monospace;letter-spacing:.12em}}h1{{font-size:38px;margin:7px 0 10px}}p{{color:#a9b0a4;line-height:1.55}}form{{margin-top:24px}}label{{display:block;margin:16px 0}}label span{{display:block;font-weight:800;margin-bottom:7px}}input,select{{box-sizing:border-box;width:100%;min-height:50px;padding:12px;background:#0e110e;color:#f4efe5;border:1px solid #343b33;font-size:16px}}button{{width:100%;min-height:52px;margin-top:14px;border:0;background:#b8ff24;color:#090b09;font-weight:950;font-size:15px}}</style></head><body><main><div class='ey'>EMPTY CHAIR // CONCIERGE</div><h1>One more thing, {name}.</h1><p>M4 found a few missing details that will help Josh review your contest entry fairly. Answer only what is still missing.</p><form method='post' action='/concierge/contest-followup/{_e(token)}'>{''.join(blocks)}<button type='submit'>Finish my entry</button></form></main></body></html>""", headers={"Cache-Control": "no-store"})
    finally:
        conn.close()


@core.app.post("/concierge/contest-followup/{token}")
async def contest_followup_submit(request: Request, token: str):
    form = await request.form()
    conn = core.connect()
    try:
        _ensure_table(conn)
        row = core.db_fetchone(
            conn,
            """
            SELECT f.*, l.profile_json, l.customer_id
            FROM contest_followups f
            JOIN concierge_leads l ON l.id=f.lead_id AND l.shop_id=f.shop_id
            WHERE f.token=? LIMIT 1
            """,
            (token,),
        )
        if not row:
            return HTMLResponse("Entry follow-up link not found.", status_code=404)
        profile = _profile(row)
        try:
            requested = set(json.loads(row["requested_fields_json"] or "[]"))
        except Exception:
            requested = set()
        changed = {}
        for key in requested:
            value = str(form.get(key) or "").strip()
            if value:
                profile[key] = value
                changed[key] = value
        core.db_execute(conn, "UPDATE concierge_leads SET profile_json=?, updated_at=? WHERE id=? AND shop_id=?", (json.dumps(profile), core.now_iso(), row["lead_id"], row["shop_id"]))
        if changed.get("styles"):
            core.db_execute(conn, "UPDATE customers SET preferred_styles=?, updated_at=? WHERE id=? AND shop_id=?", (changed["styles"], core.now_iso(), row["customer_id"], row["shop_id"]))
        core.db_execute(conn, "UPDATE contest_followups SET status='completed', completed_at=? WHERE token=?", (core.now_iso(), token))
        conn.commit()
        core.event("concierge.contest_followup.completed", "concierge_lead", row["lead_id"], json.dumps({"fields": sorted(changed.keys())}))
        return HTMLResponse("<!doctype html><html><body style='background:#080a08;color:#f4efe5;font-family:system-ui;padding:32px'><h1>Done.</h1><p>Your contest entry has been updated. Thanks.</p></body></html>")
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# Add an M4 → Concierge → Apprentice action to each contest card without duplicating Contest logic.
_original_render = contest._render


def _render_with_followup(request, user, shop, entries):
    response = _original_render(request, user, shop, entries)
    if not isinstance(response, HTMLResponse):
        return response
    body = response.body.decode("utf-8")
    for entry in entries:
        lead_id = _e(entry.get("id") or "")
        marker = f'<form class="actions" method="post" action="/contest/{lead_id}/decision">'
        followup = f'<form method="post" action="/contest/{lead_id}/request-info" style="margin-top:8px"><button type="submit" style="width:100%;min-height:42px;background:#171b16;border:1px solid #b8ff24;color:#b8ff24;font-weight:900;text-transform:uppercase;cursor:pointer">Ask remaining info</button></form>'
        body = body.replace(marker, followup + marker, 1)
    return HTMLResponse(body, status_code=response.status_code, headers=dict(response.headers))


contest._render = _render_with_followup
print("Contest M4 Concierge follow-up loaded", flush=True)
