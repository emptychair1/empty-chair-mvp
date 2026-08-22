"""M4 operating-intelligence control plane."""
import json
import uuid
from fastapi import Form, Request
from fastapi.responses import JSONResponse
import app as core
import m4_runtime
import m4_integration
import m4_synthetic_demo  # noqa: F401
DEMO_SHOP_ID="shop_live_demo"

def _opening_context(conn,shop_id,opening_id):
    opening=core.db_fetchone(conn,"SELECT * FROM openings WHERE id=? AND shop_id=? LIMIT 1",(opening_id,shop_id))
    if not opening:return None,None,[]
    artist=core.db_fetchone(conn,"SELECT * FROM artists WHERE id=? AND shop_id=? LIMIT 1",(opening["artist_id"],shop_id))
    customers=core.db_fetchall(conn,"SELECT * FROM customers WHERE shop_id=? AND communication_consent=1",(shop_id,))
    return opening,artist,customers

def _concierge_profiles(conn,shop_id):
    try:
        rows=core.db_fetchall(conn,"SELECT customer_id,profile_json,m4_confidence FROM concierge_leads WHERE shop_id=?",(shop_id,))
        out={}
        for r in rows:
            try:p=json.loads(r["profile_json"] or "{}")
            except Exception:p={}
            out[r["customer_id"]]={"profile":p,"confidence":int(r["m4_confidence"] or 0)}
        return out
    except Exception:return {}

def _round_optional(value,digits=3):
    return round(float(value),digits) if value is not None else None

def _rank(opening,artist,customers,concierge=None):
    ranked=[];artist_dict=dict(artist) if artist else {};concierge=concierge or {}
    for customer in customers:
        try:
            c=dict(customer);enrich=concierge.get(customer["id"],{});p=enrich.get("profile",{})
            if p.get("styles"):c["preferred_styles"]=p["styles"]
            if p.get("artist_vibe"):c["preferred_artists"]=(c.get("preferred_artists") or "")+" "+p["artist_vibe"]
            result=m4_runtime.score(c,dict(opening))
            decision=m4_integration.m4_recovery_breakdown(c,dict(opening),artist_dict)
            queue=float(decision["score"])
            signals=[k for k in ("styles","placement","budget","timing","short_notice","artist_vibe","travel","location","project") if p.get(k)]
            enrichment_points=min(5.0,len(signals)*.5)
            cold_start=bool(p) and int(c.get("appointment_count") or 0)==0 and int(c.get("completed_count") or 0)==0
            exploration_bonus=min(4.0,float(enrich.get("confidence",0))/25.0) if cold_start else 0.0
            queue+=enrichment_points+exploration_bonus
            why=list(decision.get("why") or result.get("why") or [])
            ranked.append({
                "customer_id":customer["id"],
                "name":c.get("name"),
                "booking_probability":round(float(decision.get("booking_probability",0)),4),
                "incremental_uplift":round(float(decision.get("incremental_uplift",0)),4),
                "confidence":round(float(decision.get("confidence",0)),4),
                "expected_value":round(float(decision.get("expected_value",0)),2) if decision.get("expected_value") is not None else None,
                "style_fit":round(float(decision.get("style_fit",0)),3),
                "budget_fit":_round_optional(decision.get("budget_fit")),
                "placement_fit":_round_optional(decision.get("placement_fit")),
                "distance_fit":_round_optional(decision.get("distance_fit")),
                "timing_fit":_round_optional(decision.get("timing_fit")),
                "short_notice_fit":_round_optional(decision.get("short_notice_fit")),
                "practical_score":_round_optional(decision.get("practical_score")),
                "practical_score_weight":round(float(decision.get("practical_weight",0)),3),
                "artist_affinity":round(float(decision.get("artist_affinity",0)),3),
                "tattoo_dna_match":_round_optional(decision.get("tattoo_dna_match")),
                "demand_graph_confidence":round(float(decision.get("demand_graph_confidence",0)),3),
                "dna_score_weight":round(float(decision.get("dna_weight",0)),3),
                "base_queue_score":round(float(decision.get("base_score",queue)),2),
                "queue_score":round(float(queue),2),
                "why":why,
                "concierge_enriched":bool(p),
                "concierge_confidence":enrich.get("confidence",0),
                "concierge_signals":signals,
                "cold_start_exploration":cold_start,
                "tattoo_dna":decision.get("tattoo_dna") or {},
                "artist_dna":decision.get("artist_dna") or {},
                "practical_fit":decision.get("practical_fit") or {},
                "contextual":decision.get("contextual") or {},
            })
        except Exception:continue
    ranked.sort(key=lambda x:(x["queue_score"],x["expected_value"] or 0,x["confidence"]),reverse=True)
    top=ranked[:8]
    seen={x["customer_id"] for x in top}
    enriched=[x for x in ranked if x.get("concierge_enriched") and x["customer_id"] not in seen][:4]
    return top+enriched

@core.app.get("/api/m4/operator/status")
def status(request:Request):
    user=core.get_current_user(request)
    if not user:return JSONResponse({"error":"Sign in first."},status_code=401)
    conn=core.connect()
    try:
        openings=core.db_fetchall(conn,"SELECT * FROM openings WHERE shop_id=? AND status='OPEN' ORDER BY date,start_time LIMIT 12",(user["shop_id"],));cr=core.db_fetchone(conn,"SELECT COUNT(*) AS n FROM customers WHERE shop_id=?",(user["shop_id"],));ar=core.db_fetchone(conn,"SELECT COUNT(*) AS n FROM artists WHERE shop_id=? AND active=1",(user["shop_id"],));cp=_concierge_profiles(conn,user["shop_id"])
        return JSONResponse({"ok":True,"shop_id":user["shop_id"],"synthetic":user["shop_id"]==DEMO_SHOP_ID,"dataset":{"customers":int(cr["n"] if cr else 0),"artists":int(ar["n"] if ar else 0),"concierge_enriched":len(cp)},"openings":[dict(o) for o in openings]},headers={"Cache-Control":"no-store, no-cache, must-revalidate, max-age=0","Pragma":"no-cache"})
    finally:conn.close()

@core.app.post("/api/m4/operator/preview")
def preview(request:Request,opening_id:str=Form(...)):
    user=core.get_current_user(request)
    if not user:return JSONResponse({"error":"Sign in first."},status_code=401)
    conn=core.connect()
    try:
        opening,artist,customers=_opening_context(conn,user["shop_id"],opening_id)
        if not opening:return JSONResponse({"error":"Opening not found for this shop."},status_code=404)
        if opening["status"]!="OPEN":return JSONResponse({"error":"Only OPEN openings can be previewed."},status_code=409)
        cp=_concierge_profiles(conn,user["shop_id"]);ranked=_rank(opening,artist,customers,cp)
        return JSONResponse({"ok":True,"synthetic":user["shop_id"]==DEMO_SHOP_ID,"opening":dict(opening),"artist":dict(artist) if artist else None,"consented_candidates":len(customers),"concierge_enriched_candidates":len([c for c in customers if c["id"] in cp]),"m4_top_candidates":ranked,"ranking_model":"incrementality + behavior + Tattoo DNA × Artist DNA + budget + placement + distance + timing + short notice + artist preference","execution":"preview_only","guardrails":["shop ownership","communication consent","calendar safety on live activation","contact cooldown","sequential offers","demo delivery suppression" if user["shop_id"]==DEMO_SHOP_ID else "production delivery safeguards"]},headers={"Cache-Control":"no-store, no-cache, must-revalidate, max-age=0","Pragma":"no-cache"})
    finally:conn.close()

def _simulate_demo_activation(opening_id,preview):
    if not preview:return None
    top=preview[0];offer_id=f"demo_m4_offer_{uuid.uuid4().hex[:10]}";now=core.now_iso();conn=core.connect()
    try:
        core.db_execute(conn,"INSERT INTO offers(id,opening_id,customer_id,score,rank,channel,sent_at,expires_at,status) VALUES (?,?,?,?,?,?,?,?,?)",(offer_id,opening_id,top["customer_id"],top["queue_score"],1,"synthetic",now,now,"SENT"));core.db_execute(conn,"UPDATE openings SET status='RECOVERY_ACTIVE' WHERE id=? AND shop_id=? AND status='OPEN'",(opening_id,DEMO_SHOP_ID));conn.commit()
    finally:conn.close()
    core.event("m4.synthetic_operator_activated","opening",opening_id,json.dumps({"offer_id":offer_id,"customer_id":top["customer_id"],"queue_score":top["queue_score"],"tattoo_dna_match":top.get("tattoo_dna_match"),"practical_score":top.get("practical_score"),"external_delivery":False}));return offer_id

@core.app.post("/api/m4/operator/activate")
def activate(request:Request,opening_id:str=Form(...)):
    user=core.get_current_user(request)
    if not user:return JSONResponse({"error":"Sign in first."},status_code=401)
    conn=core.connect()
    try:
        opening,artist,customers=_opening_context(conn,user["shop_id"],opening_id)
        if not opening:return JSONResponse({"error":"Opening not found for this shop."},status_code=404)
        if opening["status"]!="OPEN":return JSONResponse({"error":"Opening is no longer OPEN."},status_code=409)
        ranked=_rank(opening,artist,customers,_concierge_profiles(conn,user["shop_id"]))
    finally:conn.close()
    try:
        synthetic=user["shop_id"]==DEMO_SHOP_ID;offer_id=_simulate_demo_activation(opening_id,ranked) if synthetic else core.start_recovery_campaign(opening_id);core.event("m4.operator_activated","opening",opening_id,json.dumps({"offer_id":offer_id,"candidate_preview":ranked[:3],"synthetic":synthetic,"ranking_model":"demand_graph_v1"}));return JSONResponse({"ok":bool(offer_id),"synthetic":synthetic,"external_delivery":False if synthetic else None,"opening_id":opening_id,"offer_id":offer_id,"m4_top_candidates":ranked,"ranking_model":"demand_graph_v1","message":"Synthetic recovery activated. M4 selected the top modeled customer using behavior, DNA and practical-fit intelligence; no SMS or email was sent." if synthetic and offer_id else "M4 handed this opening to Empty Chair's guarded recovery engine. The production queue now uses the same Demand Graph scoring." if offer_id else "The recovery engine did not activate an offer; existing safety or eligibility rules may have blocked it."},headers={"Cache-Control":"no-store, no-cache, must-revalidate, max-age=0","Pragma":"no-cache"})
    except Exception as exc:core.event("m4.operator_activation_failed","opening",opening_id,json.dumps({"error":str(exc)}));return JSONResponse({"error":str(exc)},status_code=409)
