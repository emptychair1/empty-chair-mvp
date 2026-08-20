"""CSV data-gift path for The Meeting.

Parses an anonymized appointment-history CSV in memory, derives customer-level
behavioral features, returns a grounded M4 explanation, and gives the owner an
enriched CSV they can keep. The uploaded raw file is not written to disk.
"""
import base64
import csv
import io
from collections import Counter, defaultdict
from datetime import datetime, timezone

from fastapi import File, Form, Request, UploadFile
from fastapi.responses import JSONResponse

import app as core
import meeting_v2 as meeting
import m4_analysis_email


def _date(value):
    try:
        return datetime.fromisoformat((value or "").strip()).date()
    except Exception:
        return None


def _money(value):
    try:
        return float((value or "0").replace("$", "").replace(",", ""))
    except Exception:
        return 0.0


def _completed(row):
    return (row.get("status") or "").strip().lower() in {"completed", "rescheduled"}


def _analyze(rows):
    completed = [r for r in rows if _completed(r)]
    customers = defaultdict(list)
    artist_counts = Counter()
    style_counts = Counter()
    artist_customer = defaultdict(Counter)
    style_customer = defaultdict(Counter)
    revenue = 0.0

    for r in completed:
        cid = (r.get("customer_id") or "").strip() or "unknown"
        artist = (r.get("artist_id") or "").strip() or "unknown"
        style = (r.get("style") or "").strip() or "unknown"
        customers[cid].append(r)
        artist_counts[artist] += 1
        style_counts[style] += 1
        artist_customer[cid][artist] += 1
        style_customer[cid][style] += 1
        revenue += _money(r.get("amount_paid"))

    repeat_customers = {cid: appts for cid, appts in customers.items() if len(appts) >= 2}
    repeat_rate = (len(repeat_customers) / len(customers) * 100.0) if customers else 0.0
    today = datetime.now(timezone.utc).date()
    features = {}
    intervals = []
    strong_affinity = []
    reactivation = []

    for cid, appts in customers.items():
        dates = sorted(d for d in (_date(a.get("appointment_date")) for a in appts) if d)
        visit_count = len(appts)
        total_spend = sum(_money(a.get("amount_paid")) for a in appts)
        avg_ticket = total_spend / visit_count if visit_count else 0.0
        top_artist, artist_n = artist_customer[cid].most_common(1)[0]
        top_style, style_n = style_customer[cid].most_common(1)[0]
        artist_affinity = artist_n / visit_count if visit_count else 0.0
        style_affinity = style_n / visit_count if visit_count else 0.0
        days_since = (today - dates[-1]).days if dates else None
        return_window = None
        if len(dates) >= 2:
            gaps = [(dates[i] - dates[i - 1]).days for i in range(1, len(dates))]
            return_window = round(sum(gaps) / len(gaps)) if gaps else None
            if return_window:
                intervals.append(return_window)
        due_ratio = (days_since / return_window) if (days_since is not None and return_window and return_window > 0) else 0.0
        due = bool(return_window and days_since is not None and due_ratio >= 0.85)
        if due:
            reactivation.append((cid, days_since, return_window))
        if visit_count >= 2 and artist_affinity >= 0.67:
            strong_affinity.append((cid, top_artist, artist_n, visit_count))

        # Transparent heuristic, not a probability claim. 0-100 indicates relative
        # reactivation priority using only observed repeat behavior, recency, and affinity.
        score = 0
        reasons = []
        if visit_count >= 2:
            score += min(35, 15 + (visit_count - 2) * 5)
            reasons.append(f"{visit_count} completed visits")
        if return_window and days_since is not None:
            if due_ratio >= 1.0:
                score += 40
                reasons.append(f"past observed return rhythm ({days_since}d vs {return_window}d)")
            elif due_ratio >= 0.85:
                score += 30
                reasons.append(f"near observed return rhythm ({days_since}d vs {return_window}d)")
            elif due_ratio >= 0.65:
                score += 15
        if artist_affinity >= 0.67 and visit_count >= 2:
            score += 15
            reasons.append(f"{artist_affinity:.0%} artist affinity to {top_artist}")
        if style_affinity >= 0.60 and visit_count >= 2:
            score += 10
            reasons.append(f"{style_affinity:.0%} style affinity to {top_style}")
        score = min(100, score)

        features[cid] = {
            "m4_visit_count": visit_count,
            "m4_repeat_customer": "yes" if visit_count >= 2 else "no",
            "m4_days_since_last_visit": "" if days_since is None else days_since,
            "m4_observed_return_window_days": "" if not return_window else return_window,
            "m4_preferred_artist": top_artist,
            "m4_artist_affinity": f"{artist_affinity:.2f}",
            "m4_preferred_style": top_style,
            "m4_style_affinity": f"{style_affinity:.2f}",
            "m4_avg_completed_ticket": f"{avg_ticket:.2f}",
            "m4_reactivation_score": score,
            "m4_likely_due_for_return": "yes" if due else "no",
            "m4_reactivation_reason": "; ".join(reasons) if reasons else "insufficient repeat history",
            "m4_signal_basis": "derived from uploaded appointment history only",
        }

    avg_ticket_all = revenue / len(completed) if completed else 0.0
    median_like_interval = sorted(intervals)[len(intervals) // 2] if intervals else 0
    return {
        "records": len(rows),
        "completed": len(completed),
        "customers": len(customers),
        "repeat_customers": len(repeat_customers),
        "repeat_rate": repeat_rate,
        "strong_affinity": strong_affinity,
        "reactivation": reactivation,
        "avg_ticket": avg_ticket_all,
        "typical_return_days": round(median_like_interval) if median_like_interval else 0,
        "top_artists": artist_counts.most_common(3),
        "top_styles": style_counts.most_common(3),
        "features": features,
    }


def _enriched_csv(rows, features):
    original_fields = list(rows[0].keys()) if rows else []
    m4_fields = [
        "m4_visit_count", "m4_repeat_customer", "m4_days_since_last_visit",
        "m4_observed_return_window_days", "m4_preferred_artist", "m4_artist_affinity",
        "m4_preferred_style", "m4_style_affinity", "m4_avg_completed_ticket",
        "m4_reactivation_score", "m4_likely_due_for_return", "m4_reactivation_reason",
        "m4_signal_basis",
    ]
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=original_fields + [f for f in m4_fields if f not in original_fields])
    writer.writeheader()
    for row in rows:
        enriched = dict(row)
        cid = (row.get("customer_id") or "").strip() or "unknown"
        enriched.update(features.get(cid, {f: "" for f in m4_fields}))
        writer.writerow(enriched)
    return output.getvalue()


def _response(a):
    affinity_n = len(a["strong_affinity"])
    react_n = len(a["reactivation"])
    top_style = a["top_styles"][0][0] if a["top_styles"] else "no dominant style"
    top_artist = a["top_artists"][0][0] if a["top_artists"] else "no dominant artist"
    ticket = f"${a['avg_ticket']:,.0f}" if a["avg_ticket"] else "not enough clean revenue data to calculate"

    lines = [
        f"I found {a['records']} appointment records covering {a['customers']} anonymized customers.",
        f"{a['repeat_customers']} returned at least once, or {a['repeat_rate']:.0f}% of the customers represented in this sample.",
    ]
    if affinity_n:
        lines.append(f"{affinity_n} repeat customers show a strong same-artist preference. {top_artist} appears most often in the completed history.")
    if a["typical_return_days"]:
        lines.append(f"The middle of the observed repeat-booking intervals is about {a['typical_return_days']} days, and {react_n} customers are near or beyond their own observed return rhythm.")
    lines.append(f"The average completed ticket in this file is {ticket}. The most common style is {top_style}.")
    lines.append("Now the gift: I added a behavioral layer to your own file. Every row comes back with M4 fields for visit count, repeat status, days since last visit, observed return rhythm, artist and style affinity, average ticket, a transparent reactivation score, whether the client appears due to return, and the evidence behind that signal.")
    lines.append("Those M4 fields are derived from this uploaded history; they are not facts from an outside database and the reactivation score is a prioritization heuristic, not a probability. The original columns remain intact.")
    lines.append("Your enriched CSV is ready to download. Keep it whether you work with us or not. You gave me appointment history; I am giving it back with more economic meaning than it had when it arrived.")
    lines.append("That does not prove every open slot is recoverable. It does show there are customer-level signals you can actually act on. I think I've earned Josh's bet. Josh can explain what it would take to let me work on that here.")
    return "\n\n".join(lines)


@core.app.post("/api/meeting-v2/data-gift")
async def meeting_v2_data_gift(request: Request, session_id: str = Form(...), data_file: UploadFile = File(...)):
    user = core.get_current_user(request)
    if not user:
        return JSONResponse({"error": "Sign in first."}, status_code=401)
    sid = (session_id or "").strip()
    if not sid:
        return JSONResponse({"error": "session_id required"}, status_code=400)
    name = (data_file.filename or "").lower()
    if not name.endswith(".csv"):
        return JSONResponse({"error": "For this test, upload a CSV file."}, status_code=400)
    raw = await data_file.read()
    if not raw:
        return JSONResponse({"error": "The CSV is empty."}, status_code=400)
    if len(raw) > 2_000_000:
        return JSONResponse({"error": "Keep the test CSV under 2 MB."}, status_code=400)
    try:
        text = raw.decode("utf-8-sig")
        rows = list(csv.DictReader(io.StringIO(text)))
        required = {"appointment_date", "customer_id", "artist_id", "status"}
        if not rows or not required.issubset(set(rows[0].keys())):
            return JSONResponse({"error": "CSV needs appointment_date, customer_id, artist_id, and status columns."}, status_code=400)
        analysis = _analyze(rows)
        enriched_text = _enriched_csv(rows, analysis["features"])
        answer = _response(analysis)
        state, _ = meeting._load_session(user, sid)
        meeting._save_session(user, sid, state, "[An anonymized CSV sample was uploaded for the data gift.]", answer)
        audio64 = meeting._speak(answer)
        m4_analysis_email.schedule_latest_two(user)
        safe_stem = (data_file.filename or "customer_history.csv").rsplit(".", 1)[0]
        return JSONResponse({
            "ok": True,
            "m4_text": answer,
            "audio_base64": audio64,
            "analysis": {k: v for k, v in analysis.items() if k != "features"},
            "enriched_csv_base64": base64.b64encode(enriched_text.encode("utf-8-sig")).decode("ascii"),
            "enriched_filename": f"{safe_stem}_M4_enriched.csv",
            "privacy": "The uploaded CSV is parsed in memory for this request and this handler does not write the raw uploaded file to disk. The meeting transcript and derived response are still persisted by the existing Meeting diagnostics system."
        }, headers={"Cache-Control": "no-store"})
    except UnicodeDecodeError:
        return JSONResponse({"error": "CSV must be UTF-8 encoded."}, status_code=400)
    except Exception as exc:
        print(f"M4 data gift failed: {type(exc).__name__}: {exc}", flush=True)
        return JSONResponse({"error": str(exc)}, status_code=503)
