import m4_runtime
import app as core


def customer(**overrides):
    row={
        'id':'c1','name':'Customer','communication_consent':1,
        'preferred_styles':'realism','preferred_artists':'artist_1',
        'appointment_count':6,'completed_count':5,'cancellation_count':0,
        'no_show_count':0,'average_spend':500,
    }
    row.update(overrides)
    return row


def opening(**overrides):
    row={'id':'o1','artist_id':'artist_1','style':'realism','service':'tattoo','price':500}
    row.update(overrides)
    return row


def test_trained_model_is_loaded():
    assert m4_runtime.MODEL['model_version']=='m4-synth-logit-v1'
    assert m4_runtime.MODEL['training_rows']==80000


def test_strong_fit_outranks_weak_fit():
    strong=customer(id='strong',name='Strong',preferred_styles='realism',average_spend=500,completed_count=6)
    weak=customer(id='weak',name='Weak',preferred_styles='lettering',average_spend=1200,completed_count=0,cancellation_count=3)
    ranked=m4_runtime.rank([weak,strong],opening())
    assert ranked[0]['customer_id']=='strong'
    assert ranked[0]['expected_value']>ranked[1]['expected_value']


def test_nonconsented_customer_is_not_ranked():
    ranked=m4_runtime.rank([customer(communication_consent=0)],opening())
    assert ranked==[]


def test_production_recovery_score_uses_m4_hook():
    artist={'id':'artist_1','name':'Artist One','styles':'realism'}
    score=core.recovery_score(customer(),opening(),artist)
    assert 0 <= score <= 100
    assert core.recovery_score.__module__=='m4_integration'
