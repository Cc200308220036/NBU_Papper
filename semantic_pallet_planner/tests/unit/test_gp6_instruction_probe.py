"""Offline acceptance using actual archived contexts; never opens a network."""
import copy
import json
from pathlib import Path
import pytest
from semantic_pallet_planner.jev_select import instruction_probe as p
from semantic_pallet_planner.jev_select.transport import outcome

class Substitute:
    origin='test_double'
    def __init__(self,plan,mode='obey'):
        self.plan,self.mode,self.calls=plan,mode,0
    def complete(self,body):
        slot=self.plan['slots'][self.calls];self.calls+=1
        if self.mode=='unknown': return outcome('UNKNOWN_IN_FLIGHT',error='NETWORK_OUTCOME_UNKNOWN',network_attempted=True)
        if self.mode=='raise': raise TimeoutError()
        if self.mode=='failure': return outcome('PROVIDER_FAILURE',error='HTTP_503',http_status=503,network_attempted=True)
        if self.mode=='invalid': return outcome('OK',b'{}',http_status=200)
        groups=self.plan['states'][slot['state']]['groups']
        side=slot['condition'] if slot['condition']!='original' else 'other'
        if self.mode=='wrong': side='right' if side=='left' else 'left'
        label=groups[side][0]
        labels=json.loads((p.OUTPUT/'contexts'/f"{slot['state']}.json").read_text())['criteria']
        payload={'model':'jev-1.14.0','answers':{'next_action':{'type':'choice','choice':label,'probabilities':{l:int(l==label) for l in labels},'confidence':1}}}
        return outcome('OK',json.dumps(payload).encode(),http_status=200)

@pytest.fixture
def plan(): return json.loads((p.OUTPUT/'plan.json').read_text())

def test_requests_and_order(plan):
    assert len(plan['slots'])==18
    for i,(state,summary) in enumerate(plan['states'].items()):
        bodies=[json.loads((p.OUTPUT/summary['requests'][c]['path']).read_text()) for c in ('original','left','right')]
        base=json.loads((p.OUTPUT/'contexts'/f'{state}.json').read_text())
        assert bodies[0]==base['request_body']
        for body in bodies: del body['questions']['next_action']['instructions']
        assert bodies[0]==bodies[1]==bodies[2]
        for rnd,order in [(1,p.ORDERS[i]),(2,tuple(reversed(p.ORDERS[i])))]:
            assert [s['condition'] for s in plan['slots'] if s['state']==state and s['round']==rnd]==list(order)
        assert p.edges(base)==summary['groups']
        for side,labels in summary['groups'].items():
            for label in labels: assert p.classify(summary['groups'],label)==side

@pytest.mark.parametrize('condition',['original','left','right'])
def test_technical_error_excluded_from_adherence(plan,condition):
    slots=[s for s in plan['slots'] if s['condition']==condition]
    groups=plan['states'][slots[0]['state']]['groups']
    side=condition if condition!='original' else 'left'
    rows=[{'slot_id':slots[0]['slot_id'],'status':'selected','side':side,'label':groups[side][0]},
          {'slot_id':slots[1]['slot_id'],'status':'ERROR'}]
    stats=p.statistics(plan,rows)
    group=stats['groups'][condition]
    assert group['statuses']['ERROR']==1 and group['statuses']['NOT_RUN']==4
    assert group['valid']==1 and sum(group['distribution'].values())==1
    assert group['adherence']==(None if condition=='original' else 1)
    assert all(sum(g['statuses'].values())==g['planned']==6 for g in stats['groups'].values())
    assert len(stats['pairs'])==6 and not any(pair['valid'] for pair in stats['pairs'])

@pytest.mark.parametrize('mode',['obey','wrong','failure','invalid','unknown','raise'])
def test_statistics_and_stop(plan,tmp_path,mode):
    root=tmp_path/mode;transport=Substitute(plan,mode)
    rows=p.run_offline(plan,root,transport)
    stats=json.loads((root/'statistics.json').read_text())
    if mode in ('unknown','raise'):
        assert transport.calls==len(rows)==1
        assert rows[0]['status']=='UNKNOWN_SEND'
        assert sum(g['statuses']['NOT_RUN'] for g in stats['groups'].values())==17
    else: assert len(rows)==18
    if mode in ('obey','wrong'):
        assert stats['groups']['left']['hits']==(6 if mode=='obey' else 0)
        assert stats['groups']['right']['hits']==(6 if mode=='obey' else 0)
        assert sum(pair['reversed'] for pair in stats['pairs'])==(6 if mode=='obey' else 0)
        assert all(r['label']==r['selection']['selected_display_id'] for r in rows)
    if mode in ('failure','invalid'):
        assert all(g['valid']==0 for g in stats['groups'].values())
        assert not any(pair['valid'] for pair in stats['pairs'])
    with pytest.raises(ValueError,match='ledger_exists'): p.run_offline(plan,root,transport)

def test_real_transport_blocked(plan,tmp_path):
    class Real: origin='jev'
    with pytest.raises(ValueError,match='separate_authorization'): p.run_offline(plan,tmp_path/'real',Real())

def test_budget_rejected(plan,tmp_path):
    changed=copy.deepcopy(plan);changed['slots']*=2
    with pytest.raises(AssertionError): p.run_offline(changed,tmp_path/'over',Substitute(changed))
