from fastapi import Request
from fastapi.responses import HTMLResponse
import app as core
import m4_runtime

app=core.app

@app.get('/m4',response_class=HTMLResponse)
def m4_page(request:Request):
    user,redirect=core.login_required_redirect(request)
    if redirect:return redirect
    conn=core.connect()
    shop=core.db_fetchone(conn,'SELECT * FROM shops WHERE id=? LIMIT 1',(user['shop_id'],))
    customers=[dict(r) for r in core.db_fetchall(conn,'SELECT * FROM customers WHERE shop_id=?',(user['shop_id'],))]
    openings=[dict(r) for r in core.db_fetchall(conn,"SELECT o.*,a.name AS artist_name FROM openings o JOIN artists a ON a.id=o.artist_id WHERE o.shop_id=? AND o.status IN ('OPEN','RECOVERY_ACTIVE','NO_RECOVERY') ORDER BY o.date,o.start_time",(user['shop_id'],))]
    conn.close()
    live=openings[0] if openings else None
    ranked=m4_runtime.rank(customers,live,10) if live else []
    consented=sum(1 for c in customers if c.get('communication_consent'))
    expected=sum(r['expected_value'] for r in ranked)
    avg_conf=sum(r['confidence'] for r in ranked)/len(ranked) if ranked else 0
    styles={}
    for c in customers:
        if not c.get('communication_consent'):continue
        for style in str(c.get('preferred_styles') or '').split(','):
            style=style.strip()
            if style:styles[style]=styles.get(style,0)+1
    demand=sorted(styles.items(),key=lambda x:x[1],reverse=True)[:8]
    return core.templates.TemplateResponse(request=request,name='m4.html',context={'user':user,'shop':shop,'opening':live,'ranked':ranked,'consented':consented,'expected':expected,'avg_conf':avg_conf,'demand':demand,'model':m4_runtime.MODEL})
