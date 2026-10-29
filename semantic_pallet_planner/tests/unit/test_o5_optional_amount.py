"""Optional monetary caps do not disable request budgets, token bounds or unknown stops."""
import copy
import pytest
from test_o5_s2_remote import decision,setup_budget
from semantic_pallet_planner.o5.common import O5Error,read,atomic,digest,offline_guard
from semantic_pallet_planner.o5.remote_config import TEMPLATE,LEGACY_TEMPLATE,validate,require_cost,gaps,charge,amount_policy
from semantic_pallet_planner.o5.remote_experiment import fixture_profile,FixtureWire,prepare,execute_fixture,verify
from semantic_pallet_planner.o5.remote_transport import prepare_body,ChatHTTPTransport
from semantic_pallet_planner.o5.remote_budget import Budget
from semantic_pallet_planner.o5.remote_authorized import authorization


def unlimited():
    p=fixture_profile();p['amount_policy']='unlimited'
    p['pricing']={k:None for k in p['pricing']}
    for k in ('preflight_amount','pilot_amount','total_amount'):p['limits'][k]=None
    return validate(p)


def test_default_unlimited_gaps_exclude_all_money_fields():
    assert amount_policy(TEMPLATE)=='unlimited'
    missing=gaps(TEMPLATE)
    assert 'provider' in missing and 'token_bound.per_image_tokens' in missing
    assert not any(x.startswith(('pricing.','limits.')) for x in missing)
    assert require_cost(unlimited())
    assert charge(unlimited(),100,40) is None


def test_legacy_v1_stays_capped_even_with_missing_prices():
    p=fixture_profile();p.pop('amount_policy');p['schema_version']=LEGACY_TEMPLATE['schema_version']
    assert validate(p)==p and amount_policy(p)=='capped'
    p['pricing']['currency']=None
    with pytest.raises(O5Error,match='COST_NOT_FROZEN'):require_cost(p)


def test_new_profiles_need_explicit_policy_no_downgrade():
    p=unlimited();p.pop('amount_policy')
    with pytest.raises(O5Error,match='REMOTE_SCHEMA_ERROR'):validate(p)
    p=unlimited();p['amount_policy']='whatever'
    with pytest.raises(O5Error,match='INVALID_REMOTE_PROFILE'):validate(p)


def test_unknown_cost_attempt_replay_and_totals(decision,tmp_path):
    req,step,cfg=decision;p=unlimited();body,b=prepare_body(req,step,cfg,p)
    assert b['maximum_amount'] is None
    budget=setup_budget(tmp_path,p);wire=FixtureWire();t=ChatHTTPTransport(p,wire)
    receipt,i,e=budget.attempt('j',req,body,b,False,t)
    assert e is None and receipt['usage']['prompt_tokens']==100
    row=budget.rows('j')[0]
    assert row['reserved_amount'] is None and row['accounted_amount'] is None and row['cost_basis']=='UNKNOWN'
    total=budget.totals()
    assert total['total'] is None and total['known_subtotal']['total']=='0' and total['unknown_attempts']['total']==1
    assert total['currency'] is None and total['amount_policy']=='unlimited'
    resumed=Budget(budget.root,p,'IDENTITY',budget.jobs,True)
    resumed.attempt('j',req,body,b,False,t)
    assert len(wire.calls)==1
    # Even without prices, replacing unknown with zero is corruption.
    d=read(budget.path);d['attempts'][0]['accounted_amount']='0';atomic(budget.path,d)
    with pytest.raises(O5Error,match='REMOTE_COST_CHANGED'):resumed.load()


@pytest.mark.parametrize('event',[TimeoutError('unconfirmed'),(500,{},b'error')])
def test_unknown_prices_keep_transport_errors_and_unknown_halt(decision,tmp_path,event):
    req,step,cfg=decision;p=unlimited();body,b=prepare_body(req,step,cfg,p)
    budget=setup_budget(tmp_path,p);wire=FixtureWire([event]);t=ChatHTTPTransport(p,wire)
    if isinstance(event,BaseException):
        with pytest.raises(O5Error,match='UNKNOWN_IN_FLIGHT'):budget.attempt('j',req,body,b,False,t)
        with pytest.raises(O5Error,match='UNKNOWN_IN_FLIGHT'):budget.attempt('j',req,body,b,True,t)
    else:
        assert budget.attempt('j',req,body,b,False,t)[2]=='HTTP_500'
    assert len(wire.calls)==1 and budget.totals()['total'] is None


def test_unlimited_with_known_prices_ignores_amount_caps_but_estimates_cost(decision,tmp_path):
    req,step,cfg=decision;p=fixture_profile();p['amount_policy']='unlimited'
    for k in ('preflight_amount','pilot_amount','total_amount'):p['limits'][k]='0'
    body,b=prepare_body(req,step,cfg,p);budget=setup_budget(tmp_path,p)
    t=ChatHTTPTransport(p,FixtureWire());budget.attempt('j',req,body,b,False,t)
    assert float(budget.totals()['total'])>0 and t.calls==1


def test_unlimited_does_not_disable_request_or_input_limits(decision,tmp_path):
    req,step,cfg=decision;p=unlimited();body,b=prepare_body(req,step,cfg,p)
    budget=setup_budget(tmp_path,p,{'j':{'phase':'pilot','attempt_limit':1}});t=ChatHTTPTransport(p,FixtureWire())
    budget.attempt('j',req,body,b,False,t)
    with pytest.raises(O5Error,match='ATTEMPT_BUDGET_EXHAUSTED'):budget.attempt('j',req,body,b,True,t)
    p['token_bound']['per_image_tokens']=12000
    with pytest.raises(O5Error,match='INPUT_BOUND_EXCEEDED'):prepare_body(req,step,cfg,p)


def test_optional_authorization_omits_money_but_binds_policy_account_plan(tmp_path):
    p=unlimited();plan={'profile':p}
    auth={'schema_version':'o5_s2_operator_authorization_v2','amount_policy':'unlimited',
          'plan_digest':digest(plan),'profile_digest':digest(p),'account_id':p['account_id'],
          'campaign_path':str(tmp_path/'campaign'),'stage':'preflight','instruction_reference':'OFFLINE_TEST'}
    path=tmp_path/'auth.json';atomic(path,auth)
    assert authorization(plan,path,'preflight')==auth
    for k,v in [('amount_policy','capped'),('account_id','other'),('plan_digest','other'),('stage_amount','1')]:
        atomic(path,{**auth,k:v})
        with pytest.raises(O5Error):authorization(plan,path,'preflight')
    atomic(path,{**auth,'schema_version':'o5_s2_operator_authorization_v1'})
    with pytest.raises(O5Error,match='AUTHORIZATION_AMOUNT_POLICY_MISMATCH'):authorization(plan,path,'preflight')


def test_optional_unknown_cost_full_fixture_verify_no_network(tmp_path):
    with offline_guard():
        prepare(None,tmp_path/'plan',unlimited(),fixture=True)
        execute_fixture(tmp_path/'plan',tmp_path/'run',max_jobs=1,stop_after=2)
        completed=execute_fixture(tmp_path/'plan',tmp_path/'run',resume=True)
        checked=verify(tmp_path/'run')
        assert completed['status']=='PASS' and checked['status']=='PASS'
        assert checked['budget']['total'] is None and checked['budget']['unknown_attempts']['total']==34
        assert checked['new_api_attempts']==0


def test_capped_profile_still_requires_currency_price_and_limits():
    p=unlimited();p['amount_policy']='capped'
    with pytest.raises(O5Error,match='COST_NOT_FROZEN'):require_cost(p)


def test_optional_profile_can_omit_pricing_and_amount_fields(decision,tmp_path):
    req,step,cfg=decision;p=unlimited();p.pop('pricing')
    for k in ('preflight_amount','pilot_amount','total_amount'):p['limits'].pop(k)
    before=copy.deepcopy(p)
    normalized=require_cost(p)
    assert normalized['pricing']['currency'] is None and p==before
    body,bound=prepare_body(req,step,cfg,p)
    assert bound['maximum_amount'] is None
    budget=setup_budget(tmp_path,p);t=ChatHTTPTransport(p,FixtureWire())
    budget.attempt('j',req,body,bound,False,t)
    assert budget.totals()['total'] is None


def test_legacy_campaign_remains_v1_and_capped(decision,tmp_path):
    req,step,cfg=decision;p=fixture_profile();p.pop('amount_policy');p['schema_version']=LEGACY_TEMPLATE['schema_version']
    body,bound=prepare_body(req,step,cfg,p);budget=setup_budget(tmp_path,p)
    t=ChatHTTPTransport(p,FixtureWire());budget.attempt('j',req,body,bound,False,t)
    assert read(budget.path)['schema_version']=='o5_s2_attempt_ledger_v1'
    Budget(budget.root,p,'IDENTITY',budget.jobs,True).attempt('j',req,body,bound,False,t)
    assert t.calls==1 and budget.totals()['total'] is not None
    changed={**p,'schema_version':TEMPLATE['schema_version'],'amount_policy':'unlimited'}
    with pytest.raises(O5Error,match='REMOTE_LEDGER_IDENTITY_CHANGED'):Budget(budget.root,changed,'IDENTITY',budget.jobs,True)
