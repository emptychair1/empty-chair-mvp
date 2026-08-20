import json, math
from pathlib import Path

MODEL = json.loads((Path(__file__).parent / 'm4_trained_model.json').read_text())


def clamp(v, lo=0.0, hi=1.0): return max(lo, min(hi, v))
def sigmoid(x): return 1/(1+math.exp(-max(-30,min(30,x))))

def predict(spec, features):
    z=float(spec['intercept'])+sum(float(c)*float(x) for c,x in zip(spec['coefficients'],features))
    return clamp(sigmoid(z))

def customer_features(customer):
    completed=min(float(customer.get('completed_count') or 0),20)/20
    cancellations=float(customer.get('cancellation_count') or 0)
    no_shows=float(customer.get('no_show_count') or 0)
    appointments=max(1,float(customer.get('appointment_count') or 0))
    fatigue=clamp((cancellations+no_shows)/(appointments+2))
    avg=max(100,float(customer.get('average_spend') or 500))
    styles=str(customer.get('preferred_styles') or '').strip()
    artists=str(customer.get('preferred_artists') or '').strip()
    readiness=clamp(.34 + .18*completed + (.12 if styles else 0) + (.08 if artists else 0) - .20*fatigue)
    return [readiness,fatigue,.50,completed,math.log(avg)/math.log(2500),25/90,1.0,17/24,0.0,0.35,0.35]

def learned_state(customer):
    f=customer_features(customer)
    control=predict(MODEL['models']['control_booking'],f)
    treated=predict(MODEL['models']['treated_booking'],f)
    response=predict(MODEL['models']['response'],f)
    return {'control':control,'treated':treated,'response':response,'uplift':max(0,treated-control)}

def style_fit(customer, opening):
    prefs={s.strip().lower() for s in str(customer.get('preferred_styles') or '').split(',') if s.strip()}
    style=str(opening.get('style') or '').strip().lower()
    if not prefs or not style:return .62
    return 1.0 if style in prefs else .35

def score(customer, opening):
    s=learned_state(customer)
    sf=style_fit(customer,opening)
    price=float(opening.get('price') or 350)
    avg=max(1,float(customer.get('average_spend') or price))
    budget=clamp(1-abs(price-avg)/max(price,avg),.20,1.0)
    fit=.62*sf+.38*budget
    uplift=clamp(s['uplift']*(.55+.65*fit),.001,.75)
    booking=clamp(s['treated']*(.60+.55*fit),.005,.95)
    show=clamp(.88-.06*float(customer.get('no_show_count') or 0),.55,.97)
    expected=uplift*show*price
    confidence=clamp(.52 + .08*min(float(customer.get('completed_count') or 0),4) + (.08 if customer.get('preferred_styles') else 0),.35,.92)
    return {'customer_id':customer.get('id'),'name':customer.get('name'),'model_version':MODEL['model_version'],'booking_probability':booking,'incremental_uplift':uplift,'response_probability':s['response'],'expected_value':expected,'confidence':confidence,'score':expected*(.7+.3*confidence),'style_fit':sf,'budget_fit':budget,'why':[f'learned incremental lift {uplift:.1%}',f'opening fit {fit:.0%}',f'confidence {confidence:.0%}']}

def rank(customers, opening, limit=10):
    rows=[score(dict(c),dict(opening)) for c in customers if c.get('communication_consent')]
    rows.sort(key=lambda r:(r['score'],r['confidence']),reverse=True)
    return rows[:limit]
