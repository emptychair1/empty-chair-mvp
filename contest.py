"""Contest Intelligence: review Concierge contest entrants and record owner decisions."""

from __future__ import annotations

import html
import json
import os

from fastapi import Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

import app as core
import concierge_leads


def _e(value) -> str:
    return html.escape(str(value or ""), quote=True)


def _ensure_decisions_table(conn) -> None:
    core.db_execute(
        conn,
        """
        CREATE TABLE IF NOT EXISTS contest_decisions (
            lead_id TEXT PRIMARY KEY,
            shop_id TEXT NOT NULL,
            decision TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """,
    )
    conn.commit()


def _is_contest(profile: dict, source: str) -> bool:
    mode = str(profile.get("acquisition_mode") or "").strip().lower()
    source_text = str(source or "").strip().lower()
    return mode == "contest" or "contest" in source_text


def _review_score(profile: dict) -> tuple[int, list[str]]:
    """Evidence-only completeness/fit score for review ordering, not win probability."""
    score = 0
    reasons: list[str] = []
    project = str(profile.get("project") or "").strip()
    placement = str(profile.get("placement") or "").strip()
    styles = str(profile.get("styles") or "").strip()
    size = str(profile.get("size") or "").strip()

    if project:
        score += 4
        reasons.append("clear tattoo concept")
        if len(project) >= 60:
            score += 2
            reasons.append("detailed idea")
    if placement and placement.lower() not in {"unknown", "not sure", "unsure"}:
        score += 2
        reasons.append("placement provided")
    if size:
        score += 1
        reasons.append("size provided")
    if styles:
        score += 1
        reasons.append("style signal provided")

    return score, reasons


def _load_entries(conn, shop_id: str):
    concierge_leads._ensure_table(conn)
    _ensure_decisions_table(conn)
    rows = core.db_fetchall(
        conn,
        """
        SELECT l.*, c.name, c.phone, c.email, c.communication_consent,
               c.preferred_styles, c.preferred_artists,
               d.decision AS contest_decision
        FROM concierge_leads l
        LEFT JOIN customers c ON c.id=l.customer_id AND c.shop_id=l.shop_id
        LEFT JOIN contest_decisions d ON d.lead_id=l.id AND d.shop_id=l.shop_id
        WHERE l.shop_id=?
        ORDER BY l.created_at DESC
        LIMIT 500
        """,
        (shop_id,),
    )
    entries = []
    for row in rows:
        item = dict(row)
        try:
            profile = json.loads(item.get("profile_json") or "{}")
        except Exception:
            profile = {}
        if not _is_contest(profile, item.get("source")):
            continue
        score, reasons = _review_score(profile)
        item["profile"] = profile
        item["review_score"] = score
        item["review_reasons"] = reasons
        entries.append(item)
    entries.sort(key=lambda x: (x["review_score"], x.get("created_at") or ""), reverse=True)
    return entries


def _render(request: Request, user, shop, entries) -> HTMLResponse:
    recommendation = entries[0] if entries else None
    winner = next((entry for entry in entries if entry.get("contest_decision") == "winner"), None)
    followup_status = str(request.query_params.get("followup") or "").strip().lower()
    followup_messages = {
        "sent": ("ok", "SMS sent. The entrant received a secure link to finish the missing information."),
        "complete": ("ok", "No follow-up needed. This entrant already has the information M4 needs."),
        "no-consent": ("warn", "Not sent. This entrant is missing a phone number or SMS communication consent."),
        "sms-unavailable": ("warn", "Follow-up created, but no real SMS was sent because live SMS is unavailable."),
        "missing": ("warn", "No matching contest entrant was found for that follow-up request."),
        "error": ("error", "Follow-up failed. Nothing was sent. Check the server log before trying again."),
    }
    banner = ""
    if followup_status in followup_messages:
        tone, message = followup_messages[followup_status]
        banner = f'<div class="followup-banner {tone}"><b>FOLLOW-UP RESULT</b><span>{_e(message)}</span></div>'
    sms_live = os.getenv("EMPTY_CHAIR_SMS_LIVE", "false").lower() == "true"
    sms_state = "SMS LIVE" if sms_live else "SMS OFF"
    sms_class = "live" if sms_live else "off"

    cards = []
    for index, entry in enumerate(entries, start=1):
        profile = entry.get("profile") or {}
        name = _e(entry.get("name") or "Contest entrant")
        project = _e(profile.get("project") or "No concept description captured.")
        placement = _e(profile.get("placement") or "Not provided")
        size = _e(profile.get("size") or "Not provided")
        styles = _e(profile.get("styles") or entry.get("preferred_styles") or "Not provided")
        created = _e(str(entry.get("created_at") or "")[:16].replace("T", " "))
        decision = str(entry.get("contest_decision") or "pending")
        reason_text = ", ".join(entry.get("review_reasons") or []) or "limited information captured"
        lead_id = _e(entry.get("id"))
        consent = "Contact OK" if entry.get("communication_consent") else "No marketing opt-in"
        cards.append(
            f"""
            <article class="contest-card {'selected' if decision == 'winner' else ''}">
              <div class="card-top"><div><div class="rank">ENTRY {index:02d}</div><h2>{name}</h2></div><span class="status status-{_e(decision)}">{_e(decision.replace('_',' '))}</span></div>
              <div class="concept">{project}</div>
              <div class="facts"><span><b>Placement</b>{placement}</span><span><b>Size</b>{size}</span><span><b>Style</b>{styles}</span><span><b>Permission</b>{consent}</span></div>
              <div class="evidence"><b>M4 review evidence:</b> {_e(reason_text)}. This is review ordering, not a win probability.</div>
              <div class="meta">Submitted {created}</div>
              <form class="actions" method="post" action="/contest/{lead_id}/decision">
                <button name="decision" value="request_info" class="ask" type="submit">Ask remaining info</button>
                <button name="decision" value="winner" class="win" type="submit">Choose winner</button>
                <button name="decision" value="runner_up" type="submit">Runner-up</button>
                <button name="decision" value="archive" type="submit">Archive</button>
                <button name="decision" value="pending" type="submit">Reset</button>
              </form>
            </article>
            """
        )

    if winner:
        hero_title = f"Winner selected: {_e(winner.get('name') or 'Contest entrant')}"
        hero_copy = "You made the artistic decision. M4 will keep the remaining entries visible for follow-up decisions."
    elif recommendation:
        hero_title = f"Review {_e(recommendation.get('name') or 'this entrant')} first"
        reasons = ", ".join(recommendation.get("review_reasons") or []) or "the strongest available information"
        hero_copy = f"M4 puts this entry first because it has {_e(reasons)}. You still choose the winner."
    else:
        hero_title = "No contest entries yet"
        hero_copy = "Contest submissions captured through Concierge will appear here automatically."

    body = "".join(cards) if cards else '<div class="empty">No contest entrants found for this studio.</div>'
    shop_name = _e(shop["name"] if shop else "Studio")
    html_doc = f"""<!doctype html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Contest · Empty Chair</title>
<link rel="stylesheet" href="/static/style.css"><link rel="stylesheet" href="/static/mobile.css"><style>
:root{{--signal:#b8ff24;--cream:#f4efe5;--muted:#8c9387;--line:#2a3028;--panel:#0e110e}}
body{{margin:0;background:#080a08;color:var(--cream);font-family:Inter,system-ui,sans-serif}}.page{{min-height:100vh;padding:28px 24px 90px;max-width:1180px;margin:0 auto}}.topbar{{display:flex;justify-content:space-between;align-items:end;gap:18px;padding-bottom:18px;border-bottom:1px solid var(--line)}}.eyebrow,.rank{{font:900 11px ui-monospace,monospace;letter-spacing:.12em;color:var(--signal)}}h1{{margin:4px 0 0;font-family:Bangers,Impact,sans-serif;font-size:48px;text-transform:uppercase}}.sub{{color:var(--muted);font-size:13px}}.sms-state{{display:inline-flex;margin-top:8px;border:1px solid #3b4239;padding:5px 8px;font:900 10px ui-monospace,monospace;letter-spacing:.08em}}.sms-state.live{{border-color:var(--signal);color:var(--signal)}}.sms-state.off{{border-color:#a46f26;color:#ffc76b}}.followup-banner{{display:flex;gap:14px;align-items:center;margin:18px 0 0;padding:14px 16px;border:1px solid #424a40;background:#111411}}.followup-banner b{{font:900 10px ui-monospace,monospace;letter-spacing:.1em;white-space:nowrap}}.followup-banner span{{font-size:13px;line-height:1.45}}.followup-banner.ok{{border-color:var(--signal);box-shadow:inset 4px 0 0 var(--signal)}}.followup-banner.ok b{{color:var(--signal)}}.followup-banner.warn{{border-color:#a46f26;box-shadow:inset 4px 0 0 #ffc76b}}.followup-banner.warn b{{color:#ffc76b}}.followup-banner.error{{border-color:#8f3636;box-shadow:inset 4px 0 0 #ff6b6b}}.followup-banner.error b{{color:#ff8d8d}}.hero{{margin:20px 0;border:1px solid #394333;background:#0b0e0b;padding:22px;box-shadow:inset 4px 0 0 var(--signal)}}.hero h2{{font-size:25px;margin:0 0 8px}}.hero p{{margin:0;color:#b5bcaf;line-height:1.55}}.summary{{display:grid;grid-template-columns:repeat(3,1fr);gap:8px;margin-bottom:20px}}.metric{{border:1px solid var(--line);background:#0a0c0a;padding:14px}}.metric b{{display:block;font-size:26px}}.metric span{{color:var(--muted);font-size:10px;text-transform:uppercase;letter-spacing:.08em}}.grid{{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px}}.contest-card{{border:1px solid var(--line);background:var(--panel);padding:18px}}.contest-card.selected{{border-color:var(--signal);box-shadow:inset 0 0 0 1px var(--signal)}}.card-top{{display:flex;justify-content:space-between;gap:12px;align-items:flex-start}}.card-top h2{{margin:4px 0 0;font-size:21px}}.status{{border:1px solid #384037;padding:5px 7px;font:800 9px ui-monospace,monospace;text-transform:uppercase;color:#b7bdb3}}.status-winner{{border-color:var(--signal);color:var(--signal)}}.concept{{font-size:18px;line-height:1.45;margin:18px 0;padding:14px;background:#090b09;border-left:3px solid var(--signal)}}.facts{{display:grid;grid-template-columns:1fr 1fr;gap:8px}}.facts span{{border:1px solid #252b24;padding:10px;color:#c8cec3;font-size:12px}}.facts b{{display:block;color:#777f74;font-size:9px;text-transform:uppercase;margin-bottom:4px}}.evidence{{color:#9da598;font-size:11px;line-height:1.5;margin-top:14px}}.meta{{color:#687066;font-size:10px;margin-top:12px}}.actions{{display:grid;grid-template-columns:repeat(4,1fr);gap:6px;margin-top:16px;padding-top:14px;border-top:1px solid #252b24}}.actions button{{min-height:42px;background:#111511;border:1px solid #353c34;color:#d9ded4;font-weight:800;font-size:10px;cursor:pointer;text-transform:uppercase}}.actions .ask{{grid-column:1/-1;border-color:var(--signal);color:var(--signal)}}.actions .win{{background:var(--signal);border-color:var(--signal);color:#0a0c09}}.empty{{border:1px dashed var(--line);padding:30px;color:var(--muted)}}.back{{color:var(--cream);text-decoration:none;font-weight:800}}@media(max-width:760px){{.page{{padding:20px 16px 100px}}h1{{font-size:40px}}.topbar{{align-items:start;flex-direction:column}}.followup-banner{{align-items:flex-start;flex-direction:column;gap:5px}}.grid{{grid-template-columns:1fr}}.summary{{grid-template-columns:repeat(3,1fr)}}.actions{{grid-template-columns:1fr 1fr}}.facts{{grid-template-columns:1fr}}}}
</style></head><body><main class="page"><header class="topbar"><div><div class="eyebrow">DEMAND ENGINE · CONTEST INTELLIGENCE</div><h1>Contest</h1><div class="sub">{shop_name} · Real contest entries captured by Concierge.</div><div class="sms-state {sms_class}">{sms_state}</div></div><a class="back" href="/">← App</a></header>
{banner}
<section class="hero"><div class="eyebrow">M4 RECOMMENDATION</div><h2>{hero_title}</h2><p>{hero_copy}</p></section>
<section class="summary"><div class="metric"><b>{len(entries)}</b><span>Entrants</span></div><div class="metric"><b>{sum(1 for e in entries if e.get('contest_decision') == 'winner')}</b><span>Winner</span></div><div class="metric"><b>{sum(1 for e in entries if e.get('contest_decision') == 'runner_up')}</b><span>Runner-up</span></div></section>
<section class="grid">{body}</section></main></body></html>"""
    return HTMLResponse(html_doc, headers={"Cache-Control": "no-store, no-cache, must-revalidate"})


@core.app.get("/contest", response_class=HTMLResponse)
def contest_page(request: Request):
    user, redirect = core.login_required_redirect(request)
    if redirect:
        return redirect
    conn = core.connect()
    try:
        shop = core.db_fetchone(conn, "SELECT * FROM shops WHERE id=?", (user["shop_id"],))
        entries = _load_entries(conn, user["shop_id"])
        return _render(request, user, shop, entries)
    except Exception as exc:
        conn.rollback()
        return HTMLResponse(
            "<!doctype html><html><body style='background:#080a08;color:#f4efe5;font-family:system-ui;padding:30px'><h1>Contest could not load</h1><pre>" + _e(type(exc).__name__ + ": " + str(exc)) + "</pre><a style='color:#b8ff24' href='/'>Back to app</a></body></html>",
            status_code=503,
            headers={"Cache-Control": "no-store"},
        )
    finally:
        conn.close()


@core.app.post("/contest/{lead_id}/decision")
def contest_decision(request: Request, lead_id: str, decision: str = Form(...)):
    user, redirect = core.login_required_redirect(request)
    if redirect:
        return redirect
    allowed = {"winner", "runner_up", "archive", "pending", "request_info"}
    if decision not in allowed:
        return RedirectResponse(url="/contest", status_code=303)

    conn = core.connect()
    try:
        entries = _load_entries(conn, user["shop_id"])
        entry_ids = {str(entry.get("id")) for entry in entries}
        if lead_id not in entry_ids:
            conn.rollback()
            return RedirectResponse(url="/contest", status_code=303)

        if decision == "request_info":
            conn.close()
            conn = None
            try:
                import contest_followup_v2

                status = contest_followup_v2.request_info(user["shop_id"], lead_id)
                return RedirectResponse(url=f"/contest?followup={status}", status_code=303)
            except Exception as exc:
                print(f"Contest follow-up failed for {lead_id}: {type(exc).__name__}: {exc}", flush=True)
                return RedirectResponse(url="/contest?followup=error", status_code=303)

        if decision == "winner":
            core.db_execute(conn, "DELETE FROM contest_decisions WHERE shop_id=? AND decision='winner'", (user["shop_id"],))

        if decision == "pending":
            core.db_execute(conn, "DELETE FROM contest_decisions WHERE lead_id=? AND shop_id=?", (lead_id, user["shop_id"]))
        else:
            if getattr(core, "USE_POSTGRES", False):
                core.db_execute(
                    conn,
                    """
                    INSERT INTO contest_decisions(lead_id,shop_id,decision,updated_at)
                    VALUES (?,?,?,?)
                    ON CONFLICT (lead_id) DO UPDATE SET
                      shop_id=EXCLUDED.shop_id,
                      decision=EXCLUDED.decision,
                      updated_at=EXCLUDED.updated_at
                    """,
                    (lead_id, user["shop_id"], decision, core.now_iso()),
                )
            else:
                core.db_execute(
                    conn,
                    "INSERT OR REPLACE INTO contest_decisions(lead_id,shop_id,decision,updated_at) VALUES (?,?,?,?)",
                    (lead_id, user["shop_id"], decision, core.now_iso()),
                )
        conn.commit()
        return RedirectResponse(url="/contest", status_code=303)
    except Exception:
        if conn is not None:
            conn.rollback()
        raise
    finally:
        if conn is not None:
            conn.close()


@core.app.get("/concierge/contest-followup/{token}", response_class=HTMLResponse)
def contest_followup_page(token: str):
    try:
        import contest_followup_v2

        body, status_code = contest_followup_v2.render_followup(token)
        if body is None:
            return HTMLResponse("Entry follow-up link not found.", status_code=404)
        return HTMLResponse(body, status_code=status_code, headers={"Cache-Control": "no-store"})
    except Exception as exc:
        return HTMLResponse(
            "<!doctype html><html><body style='background:#080a08;color:#f4efe5;font-family:system-ui;padding:32px'><h1>Follow-up temporarily unavailable</h1><p>" + _e(type(exc).__name__ + ": " + str(exc)) + "</p></body></html>",
            status_code=503,
            headers={"Cache-Control": "no-store"},
        )


@core.app.post("/concierge/contest-followup/{token}", response_class=HTMLResponse)
async def contest_followup_submit(request: Request, token: str):
    try:
        import contest_followup_v2

        form = await request.form()
        status = contest_followup_v2.submit_followup(token, form)
        if status == "missing":
            return HTMLResponse("Entry follow-up link not found.", status_code=404)
        return HTMLResponse(
            "<!doctype html><html><body style='background:#080a08;color:#f4efe5;font-family:system-ui;padding:32px'><h1>Done.</h1><p>Your contest entry has been updated. Thanks.</p></body></html>",
            headers={"Cache-Control": "no-store"},
        )
    except Exception as exc:
        return HTMLResponse(
            "<!doctype html><html><body style='background:#080a08;color:#f4efe5;font-family:system-ui;padding:32px'><h1>Could not update entry</h1><p>" + _e(type(exc).__name__ + ": " + str(exc)) + "</p></body></html>",
            status_code=503,
            headers={"Cache-Control": "no-store"},
        )
