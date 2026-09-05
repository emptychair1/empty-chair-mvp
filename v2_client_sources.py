"""Client-source setup for Empty Chair 2.0.

Keeps the product headless while giving artists practical ways to seed the ready bench:
phone contacts, Facebook/Instagram connection, manual entry, or CSV/vCard upload.
"""
from __future__ import annotations

import json
import secrets
from fastapi import File, Form, Request, UploadFile
from fastapi.responses import JSONResponse, RedirectResponse

import v2_app as core


def _drop_route(path: str, methods: set[str]):
    kept = []
    for route in core.app.router.routes:
        route_methods = set(getattr(route, "methods", set()) or set())
        if getattr(route, "path", None) == path and methods.issubset(route_methods):
            continue
        kept.append(route)
    core.app.router.routes[:] = kept


_drop_route("/setup/clients", {"GET"})


def _insert_client(artist_id: str, name: str, phone: str, email: str = "") -> bool:
    name = (name or "").strip()
    phone = core.clean_phone(phone or "")
    email = (email or "").strip()
    if not name or not phone:
        return False
    existing = core.one(
        "SELECT id FROM clients WHERE artist_id=? AND phone=? LIMIT 1",
        (artist_id, phone),
    )
    if existing:
        core.run(
            "UPDATE clients SET name=?,email=CASE WHEN ?<>'' THEN ? ELSE email END WHERE id=?",
            (name, email, email, existing["id"]),
        )
        return False
    core.run(
        "INSERT INTO clients(id,artist_id,name,phone,email,styles,budget_cents,short_notice,completed_count,no_show_count,created_at) VALUES(?,?,?,?,?,'',0,1,0,0,?)",
        (secrets.token_hex(16), artist_id, name, phone, email, core.utcnow()),
    )
    return True


@core.app.get("/setup/clients")
def clients_page(request: Request):
    artist = core.current_artist(request)
    if not artist:
        return RedirectResponse("/setup")
    count = core.one("SELECT COUNT(*) AS n FROM clients WHERE artist_id=?", (artist["id"],))["n"]
    body = f'''
<h1>WHO CAN WE CALL?</h1>
<p class="big">{count}</p>
<p class="dim">clients ready</p>
<div class="space"></div>
<div class="stack">
  <button type="button" id="phone-contacts">[ + ] PHONE CONTACTS</button>
  <a class="button" href="/setup/clients/meta">[ f ] FACEBOOK + INSTAGRAM</a>
  <a class="button" href="/setup/clients/manual">[ + ] ADD MANUALLY</a>
  <a class="button" href="/setup/clients/file">[ ↑ ] CSV / CONTACT FILE</a>
</div>
<div class="space"></div>
<p class="dim center" id="contact-status"></p>
{('<a class="button" href="/setup/armed">ARM EMPTY CHAIR</a>' if int(count) > 0 else '<div class="button quiet">ADD AT LEAST ONE CLIENT TO ARM</div>')}
'''
    script = '''<script>
const btn=document.getElementById('phone-contacts');
const status=document.getElementById('contact-status');
btn?.addEventListener('click', async()=>{
  if(!('contacts' in navigator) || !navigator.contacts?.select){
    location.href='/setup/clients/file?contacts=1';
    return;
  }
  try{
    const picked=await navigator.contacts.select(['name','tel','email'],{multiple:true});
    if(!picked?.length){status.textContent='No contacts selected.';return;}
    status.textContent='Importing '+picked.length+' contact'+(picked.length===1?'':'s')+'...';
    const r=await fetch('/setup/clients/phone',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({contacts:picked})});
    const j=await r.json();
    if(!r.ok) throw new Error(j.error||'Import failed');
    location.reload();
  }catch(e){status.textContent='Contact picker unavailable. Opening file import...';setTimeout(()=>location.href='/setup/clients/file?contacts=1',700);}
});
</script>'''
    return core.page("Clients", body, script=script)


@core.app.post("/setup/clients/phone")
async def phone_contacts_import(request: Request):
    artist = core.current_artist(request)
    if not artist:
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    try:
        payload = await request.json()
        contacts = payload.get("contacts") or []
        imported = 0
        for item in contacts[:1000]:
            names = item.get("name") or []
            tels = item.get("tel") or []
            emails = item.get("email") or []
            name = names[0] if isinstance(names, list) and names else ""
            email = emails[0] if isinstance(emails, list) and emails else ""
            if isinstance(tels, list):
                for phone in tels:
                    if _insert_client(artist["id"], str(name), str(phone), str(email)):
                        imported += 1
                    break
        core.event("clients.imported.phone", artist["id"], {"count": imported})
        return {"ok": True, "imported": imported}
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)


@core.app.get("/setup/clients/manual")
def manual_page(request: Request):
    if not core.current_artist(request):
        return RedirectResponse("/setup")
    return core.page("Add client", '''
<h1>ADD A CLIENT</h1>
<form method="post" class="stack">
<label>name<input name="name" autocomplete="name" required></label>
<label>mobile<input name="phone" autocomplete="tel" inputmode="tel" required></label>
<label>email // optional<input name="email" type="email" autocomplete="email"></label>
<button>ADD CLIENT</button>
</form>
<div class="space"></div><a class="button quiet" href="/setup/clients">BACK</a>
''')


@core.app.post("/setup/clients/manual")
def manual_post(request: Request, name: str = Form(...), phone: str = Form(...), email: str = Form("")):
    artist = core.current_artist(request)
    if not artist:
        return RedirectResponse("/setup")
    _insert_client(artist["id"], name, phone, email)
    core.event("clients.imported.manual", artist["id"], {"count": 1})
    return RedirectResponse("/setup/clients", status_code=303)


@core.app.get("/setup/clients/file")
def file_page(request: Request, contacts: int = 0):
    if not core.current_artist(request):
        return RedirectResponse("/setup")
    note = '<p class="dim">On iPhone, export/share contacts as a .vcf file here when direct contact picking is unavailable.</p>' if contacts else ''
    return core.page("Import clients", f'''
<h1>IMPORT CLIENTS</h1>{note}
<form method="post" action="/setup/clients/upload" enctype="multipart/form-data" class="stack">
<label>CSV<input type="file" name="file" accept=".csv,text/csv" required></label>
<small>columns: name, phone, email, styles, budget, short_notice, completed_count, no_show_count</small>
<button>IMPORT CSV</button>
</form>
<div class="space"></div>
<form method="post" action="/setup/clients/vcard" enctype="multipart/form-data" class="stack">
<label>CONTACT FILE // VCF<input type="file" name="file" accept=".vcf,text/vcard,text/x-vcard" required></label>
<button>IMPORT CONTACT FILE</button>
</form>
<div class="space"></div><a class="button quiet" href="/setup/clients">BACK</a>
''')


@core.app.post("/setup/clients/vcard")
async def vcard_upload(request: Request, file: UploadFile = File(...)):
    artist = core.current_artist(request)
    if not artist:
        return RedirectResponse("/setup")
    text = (await file.read()).decode("utf-8", errors="replace")
    imported = 0
    for block in text.replace("\r", "").split("END:VCARD"):
        if "BEGIN:VCARD" not in block:
            continue
        name = ""
        phones = []
        email = ""
        for line in block.split("\n"):
            if line.startswith("FN:"):
                name = line[3:].strip()
            elif line.startswith("TEL") and ":" in line:
                phones.append(line.split(":", 1)[1].strip())
            elif line.startswith("EMAIL") and ":" in line and not email:
                email = line.split(":", 1)[1].strip()
        for phone in phones[:1]:
            if _insert_client(artist["id"], name, phone, email):
                imported += 1
    core.event("clients.imported.vcard", artist["id"], {"count": imported})
    return RedirectResponse("/setup/clients", status_code=303)


@core.app.get("/setup/clients/meta")
def meta_page(request: Request):
    if not core.current_artist(request):
        return RedirectResponse("/setup")
    return core.page("Facebook + Instagram", '''
<h1>FACEBOOK + INSTAGRAM</h1>
<p>Connect your professional Meta accounts so Empty Chair can bring in people who have actually given you usable contact information.</p>
<div class="space"></div>
<div class="error">META CONNECTION SETUP REQUIRED</div>
<p class="dim">Facebook and Instagram do not expose a general downloadable phone/email list of followers or everyone in your DMs. We can sync eligible leads/contacts from supported business surfaces once Meta OAuth and permissions are configured.</p>
<div class="space"></div>
<a class="button quiet" href="/setup/clients">BACK</a>
''')
