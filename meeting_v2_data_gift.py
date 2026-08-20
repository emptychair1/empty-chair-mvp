"""CSV data-gift path for The Meeting.

Parses an anonymized appointment-history CSV in memory, derives useful patterns,
returns a grounded M4 explanation, and does not write the uploaded file to disk.
"""
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


def _analyze(rows):
    completed = [r for r in rows if (r.get("status") or "").strip().lower() in {"completed", "rescheduled"}]
    customers = defaultdict(list)
    artist_counts = Counter()
    style_counts = Counter()
    artist_customer = defaultdict(Counter)
    revenue = 0.0

    for r in completed:
        cid = (r.get("customer_id") or "").strip() or "unknown"
        artist = (r.get("artist_id") or "").strip() or "unknown"
        style = (r.get("style") or "").strip() or "unknown"
        customers[cid].append(r)
        artist_counts[artist] += 1
        style_counts[style] += 1
        artist_customer[cid][artist] += 1
        revenue += _money(r.get("amount_paid"))

    repeat_customers = {cid: appts for cid, appts in customers.items() if len(appts) >= 2}
    repeat_rate = (len(repeat_customers) / len(customers) * 100.0) if customers else 0.0

    strong_affinity = []
    for cid, appts in repeat_customers.items():
        top_artist, count = artist_customer[cid].most_common(1)[0]
        if count >= 2 and count / len(appts) >= 0.67:
            strong_affinity.append((cid, top_artist, count, len(appts)))

    intervals = []
    reactivation = []
    today = datetime.now(timezone.utc).date()
    for cid, appts in repeat_customers.items():
        dates = sorted(d for d in (_date(a.get("appointment_date")) for a in appts) if d)
        if len(dates) < 2:
            continue
        gaps = [(dates[i] - dates[i-1]).days for i in range(1, len(dates))]
        avg_gap = sum(gaps) / len(gaps)
        intervals.append(avg_gap)
        days_since = (today - dates[-1]).days
        if avg_gap > 0 and days_since >= avg_gap * 0.85:
            reactivation.append((cid, days_since, round(avg_gap)))

    avg_ticket = revenue / len(completed) if completed else 0.0
    median_like_interval = sorted(intervals)[len(intervals)//2] if intervals else 0

    return {
        "records": len(rows),
        "completed": len(completed),
        "customers": len(customers),
        "repeat_customers": len(repeat_customers),
        "repeat_rate": repeat_rate,
        "strong_affinity": strong_affinity,
        "reactivation": reactivation,
        "avg_ticket": avg_ticket,
        "typical_return_days": round(median_like_interval) if median_like_interval else 0,
        "top_artists": artist_counts.most_common(3),
        "top_styles": style_counts.most_common(3),
    }


def _response(a):
    affinity_n = len(a["strong_affinity"])
    react_n = len(a["reactivation"])
    top_style = a["top_styles"][0][0] if a["top_styles"] else "no dominant style"
    top_artist = a["top_artists"][0][0] if a["top_artists"] else "no dominant artist"
    ticket = f"${a['avg_ticket']:,.0f}" if a["avg_ticket"] else "not enough clean revenue data to calculate"

    lines = [
        f"I found {a['records']} appointment records covering {a['customers']} anonymized customers.",
        f"Of those customers, {a['repeat_customers']} returned at least once, which is {a['repeat_rate']:.0f}% of the customers represented in this sample.",
    ]
    if affinity_n:
        lines.append(f"{affinity_n} repeat customers show a strong preference for the same artist rather than booking randomly. {top_artist} appears most often in the completed history.")
    if a["typical_return_days"]:
        lines.append(f"The middle of the observed repeat-booking intervals is about {a['typical_return_days']} days. {react_n} customers are already near or beyond their own historical return rhythm.")
    lines.append(f"The average completed-ticket value in this file is {ticket}. The most common style in the sample is {top_style}.")
    lines.append("What I added was not more customer data. I added structure to data you already owned: repeat behavior, artist affinity, timing, and a first-pass reactivation signal that can be matched against specific empty chairs.")
    lines.append("That does not prove every open slot is recoverable. It does show that your existing customer history contains usable demand signals that are invisible in a flat appointment export.")
    lines.append("I think I've earned Josh's bet. Josh can explain what it would take to let me work on that here.")
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
        answer = _response(analysis)
        state, _ = meeting._load_session(user, sid)
        meeting._save_session(user, sid, state, "[An anonymized CSV sample was uploaded for the data gift.]", answer)
        audio64 = meeting._speak(answer)
        m4_analysis_email.schedule_latest_two(user)
        return JSONResponse({
            "ok": True,
            "m4_text": answer,
            "audio_base64": audio64,
            "analysis": analysis,
            "privacy": "The uploaded CSV is parsed in memory for this request and this handler does not write the file to disk. The meeting transcript and derived response are still persisted by the existing Meeting diagnostics system."
        }, headers={"Cache-Control": "no-store"})
    except UnicodeDecodeError:
        return JSONResponse({"error": "CSV must be UTF-8 encoded."}, status_code=400)
    except Exception as exc:
        print(f"M4 data gift failed: {type(exc).__name__}: {exc}", flush=True)
        return JSONResponse({"error": str(exc)}, status_code=503)
