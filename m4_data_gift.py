"""Privacy-first, zero-retention customer-data gift.

The uploaded CSV is processed only in request memory. Raw bytes, parsed rows, and
returned CSV are never written to Empty Chair's database, filesystem, logs, or M4
relationship memory by this module. The response is an attachment owned by the caller.
"""
import csv
import io
import re

from fastapi import File, Request, UploadFile
from fastapi.responses import JSONResponse, Response

import app as core

MAX_BYTES = 5 * 1024 * 1024
MAX_ROWS = 50000


def _clean(value):
    return " ".join((value or "").strip().split())


def _normalize_phone(value):
    raw = _clean(value)
    digits = re.sub(r"\D", "", raw)
    if len(digits) == 10:
        return "+1" + digits
    if len(digits) == 11 and digits.startswith("1"):
        return "+" + digits
    return raw


def _normalize_email(value):
    return _clean(value).lower()


def _enrich(rows, fieldnames):
    lowered = {name.lower().strip(): name for name in fieldnames}
    email_key = next((lowered[k] for k in ("email", "email_address", "e-mail") if k in lowered), None)
    phone_key = next((lowered[k] for k in ("phone", "phone_number", "mobile", "cell") if k in lowered), None)
    first_key = next((lowered[k] for k in ("first_name", "firstname", "first") if k in lowered), None)
    last_key = next((lowered[k] for k in ("last_name", "lastname", "last") if k in lowered), None)
    name_key = next((lowered[k] for k in ("name", "full_name", "customer_name") if k in lowered), None)

    extra = ["ec_normalized_email", "ec_normalized_phone", "ec_display_name", "ec_contactable"]
    output_fields = list(fieldnames) + [x for x in extra if x not in fieldnames]
    enriched = []
    for source in rows:
        row = {k: _clean(v) for k, v in source.items()}
        email = _normalize_email(row.get(email_key, "")) if email_key else ""
        phone = _normalize_phone(row.get(phone_key, "")) if phone_key else ""
        if name_key:
            display = _clean(row.get(name_key, ""))
        else:
            display = _clean(" ".join(x for x in (row.get(first_key, "") if first_key else "", row.get(last_key, "") if last_key else "") if x))
        row["ec_normalized_email"] = email
        row["ec_normalized_phone"] = phone
        row["ec_display_name"] = display
        row["ec_contactable"] = "yes" if email or phone else "no"
        enriched.append(row)
    return output_fields, enriched


@core.app.post("/api/data-gift/enrich")
async def data_gift_enrich(request: Request, file: UploadFile = File(...)):
    user = core.get_current_user(request)
    if not user:
        return JSONResponse({"error": "Sign in first."}, status_code=401)
    filename = file.filename or "customers.csv"
    if not filename.lower().endswith(".csv"):
        return JSONResponse({"error": "The data gift currently accepts CSV files only."}, status_code=400)
    raw = await file.read(MAX_BYTES + 1)
    await file.close()
    if len(raw) > MAX_BYTES:
        return JSONResponse({"error": "CSV is larger than the 5 MB zero-retention processing limit."}, status_code=413)
    try:
        text = raw.decode("utf-8-sig")
        reader = csv.DictReader(io.StringIO(text))
        if not reader.fieldnames:
            raise ValueError("CSV has no header row")
        rows = []
        for row in reader:
            rows.append(row)
            if len(rows) > MAX_ROWS:
                return JSONResponse({"error": "CSV exceeds the 50,000-row processing limit."}, status_code=413)
        fields, enriched = _enrich(rows, reader.fieldnames)
        out = io.StringIO(newline="")
        writer = csv.DictWriter(out, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(enriched)
        payload = out.getvalue().encode("utf-8")
    except (UnicodeDecodeError, csv.Error, ValueError) as exc:
        return JSONResponse({"error": f"Could not process CSV: {exc}"}, status_code=400)
    finally:
        raw = b""

    stem = re.sub(r"[^A-Za-z0-9._-]+", "_", filename.rsplit(".", 1)[0]) or "customers"
    return Response(
        content=payload,
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{stem}_empty_chair_enriched.csv"',
            "Cache-Control": "no-store, no-cache, must-revalidate, private",
            "Pragma": "no-cache",
            "Expires": "0",
            "X-Empty-Chair-Data-Retention": "none-by-this-endpoint",
            "X-Content-Type-Options": "nosniff",
        },
    )


@core.app.get("/api/data-gift/capabilities")
def data_gift_capabilities(request: Request):
    user = core.get_current_user(request)
    if not user:
        return JSONResponse({"error": "Sign in first."}, status_code=401)
    return {
        "enrichment_available": True,
        "processing": "request_memory_only",
        "raw_data_persisted_by_endpoint": False,
        "parsed_data_persisted_by_endpoint": False,
        "result_persisted_by_endpoint": False,
        "written_to_m4_memory": False,
        "response_cache": "no-store",
        "scope": "Guarantees describe this endpoint's application behavior only; infrastructure/provider retention must be separately verified before broader claims."
    }
