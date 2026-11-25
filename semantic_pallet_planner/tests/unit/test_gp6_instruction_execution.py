"""Formal execution gates tested with substitutes; credentials/network forbidden."""
import copy
import json
from pathlib import Path
import pytest
from semantic_pallet_planner.jev_select import instruction_probe_execution as e
from semantic_pallet_planner.jev_select.ledger import exclusive
from semantic_pallet_planner.jev_select.transport import outcome

@pytest.fixture
def setup(tmp_path,monkeypatch):
    monkeypatch.setattr(e,'RUN',tmp_path/'run')
    plan=e.prepare(tmp_path/'package')
    auth={'version':'gp6_instruction_execution_authorization_v1','status':'AUTHORIZED','authorization_id':'SUBSTITUTE_ONLY','approval_reference':'offline fixture, no real permission','plan_digest':e.digest(plan),**{k:plan[k] for k in ('model','endpoint','max_reservations','run_root')}}
    # A real construction or key lookup would fail immediately.
    monkeypatch.setattr('semantic_pallet_planner.jev_select.transport.credential',lambda *a,**kw: pytest.fail('credential accessed'))
    return plan,auth

class Substitute:
    origin='test_double'
    def __init__(self,plan,mode='ok'): self.plan,self.mode,self.calls=plan,mode,0
    def complete(self,body):
        self.calls+=1
        persisted=e.read(e.RUN/'requests.json')
        assert persisted['reservations']==self.calls
        assert persisted['rows'][self.calls-1]['status']=='SENDING'
        if self.mode=='raise': raise TimeoutError()
        if self.mode=='unknown': return outcome('UNKNOWN_IN_FLIGHT',error='NETWORK_OUTCOME_UNKNOWN',network_attempted=True)
        if self.mode=='failure': return outcome('PROVIDER_FAILURE',error='HTTP_503',http_status=503,network_attempted=True)
        if self.mode=='invalid': return outcome('OK',b'{}',http_status=200,network_attempted=True)
        slot=self.plan['slots'][self.calls-1]
        context=e.read(e.probe.OUTPUT/'contexts'/f"{slot['state']}.json")
        label=next(iter(context['criteria']))
        payload={'model':e.MODEL,'answers':{'next_action':{'type':'choice','choice':label,'probabilities':{l:int(l==label) for l in context['criteria']},'confidence':1}}}
        return outcome('OK',json.dumps(payload).encode(),http_status=200,network_attempted=True)

@pytest.mark.parametrize('mode',['ok','unknown','raise','failure','invalid'])
def test_execution(setup,mode):
    plan,auth=setup;transport=Substitute(plan,mode)
    ledger=e.execute(plan,auth,transport_factory=lambda:transport)
    assert ledger['origin']=='test_double'
    assert ledger['reservations']==(1 if mode in ('unknown','raise') else 18)
    if mode in ('unknown','raise'):
        assert ledger['rows'][0]['status']=='UNKNOWN_SEND'
        assert all(r['status']=='NOT_RUN' for r in ledger['rows'][1:])
    if mode=='ok':
        assert all(r['label']==r['selection']['selected_display_id'] for r in ledger['rows'])
    with pytest.raises(ValueError,match='already_started'): e.execute(plan,auth,transport_factory=lambda:pytest.fail('duplicate factory'))

@pytest.mark.parametrize('change',['auth','digest','endpoint','slots','files','config'])
def test_reject_before_factory(setup,change):
    plan,auth=setup
    if change=='auth': auth['status']='PENDING'
    elif change=='digest': auth['plan_digest']='bad'
    elif change=='endpoint': plan['endpoint']='https://invalid'
    elif change=='slots': plan['slots']=list(reversed(plan['slots']))
    elif change=='files': plan['frozen_files'][str(e.probe.OUTPUT/'requests/G01_D0000_left.json')]='bad'
    elif change=='config': plan['transport_config']['model']='bad'
    with pytest.raises(ValueError): e.execute(plan,auth,transport_factory=lambda:pytest.fail('unauthorized factory'))
    assert not (e.RUN/'started.json').exists()

def test_concurrent_lock(setup):
    plan,auth=setup;e.RUN.mkdir()
    with exclusive(e.RUN):
        with pytest.raises(Exception,match='experiment_locked'):
            e.execute(plan,auth,transport_factory=lambda:pytest.fail('locked factory'))
    assert not (e.RUN/'started.json').exists()

def test_body_tamper(setup,monkeypatch,tmp_path):
    plan,auth=setup
    original=e.sha
    target=str(e.probe.OUTPUT/'requests/G01_D0000_left.json')
    monkeypatch.setattr(e,'sha',lambda p:'bad' if str(p)==target else original(p))
    with pytest.raises(ValueError,match='frozen_files_changed'): e.execute(plan,auth,transport_factory=lambda:pytest.fail('tampered factory'))

def test_start_claim_survives_factory_failure(setup):
    plan,auth=setup
    def crash(): raise RuntimeError('fixture')
    with pytest.raises(RuntimeError): e.execute(plan,auth,transport_factory=crash)
    with pytest.raises(ValueError,match='already_started'): e.execute(plan,auth,transport_factory=crash)
