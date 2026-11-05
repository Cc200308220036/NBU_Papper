"""JN4-A admission/control tests. All orders constructed; no model transport."""
import copy
from pathlib import Path
import pytest
from semantic_pallet_planner.jev_select import packaging_source_audit as a
from semantic_pallet_planner.jev_select import packaging_evaluation_plan as p
from semantic_pallet_planner.jev_select.contracts import JevSelectError,canonical,digest,validate_schema

REPO=Path(__file__).resolve().parents[3]


def order(rows, identity):
    return {'properties':{'id':identity},'item_sequence':{str(i+1):{
        'length/mm':r[0],'width/mm':r[1],'height/mm':r[2],'weight/kg':r[3]}
        for i,r in enumerate(rows)}}


def test_rotation_reorder_and_transitive_alias_component():
    rows=[(20,30,10,1),(50,40,20,2)]
    raw={'a':order(rows,'A'),'b':order([(30,20,10,1),(40,50,20,2)][::-1],'B'),
         'c':order([(70,80,30,3)],'C')}
    result=a.audit_sources(raw,{'A':[{'status':'TRAIN_DEV_OR_REAL_RUN'}]},[['b','C']])
    assert len(result['components'])==1
    assert result['components'][0]['raw_keys']==['a','b','c']
    assert not result['components'][0]['strict_test_eligible']


def test_ninety_percent_multiset_near_duplicate_and_mass():
    rows=[(20+i,30,10,1) for i in range(10)]
    near=rows[:-1]+[(900,900,900,90)]
    mass=[(x,y,z,m+9) for x,y,z,m in rows]
    groups,edges,_=a.components({'a':order(rows,'A'),'b':order(near,'B'),'c':order(mass,'C')})
    assert sorted(map(len,groups.values()))==[1,2]
    assert any(e['reason']=='near_multiset_90pct' for e in edges)


def test_absent_hit_static_read_never_becomes_unseen():
    result=a.audit_sources({'a':order([(20,30,10,1)],'A')},{})
    c=result['components'][0]
    assert c['exposure_status']=='UNKNOWN_EXPOSURE' and c['assigned_split']=='excluded'
    assert c['current_access']['kind']=='STATIC_SOURCE_AUDIT'
    assert result['strict_test_source_count']==0


@pytest.mark.parametrize('rows',[
    [{'component':'a','split':'train','exposure_status':'TRAIN_DEV_OR_REAL_RUN'},
     {'component':'a','split':'dev','exposure_status':'TRAIN_DEV_OR_REAL_RUN'}],
    [{'component':'a','split':'test','exposure_status':'UNKNOWN_EXPOSURE'}],
    [{'component':'a','split':'test','exposure_status':'HISTORICAL_TEST'}],
    [{'component':'a','split':'test','exposure_status':'TRAIN_DEV_OR_REAL_RUN'}],
    [{'component':'a','split':'test','exposure_status':'VERIFIED_UNSEEN'}],
])
def test_reject_cross_split_and_unattested_test(rows):
    with pytest.raises(JevSelectError):a.validate_partition(rows)


def test_candidate_lists_are_not_exposure(tmp_path):
    q=tmp_path/'exposure_manifest.json'
    q.write_text('{"candidate_new_sources":[{"source_order_key":"001"}],"source_orders":[{"source_order_id":"002"}],"scope":"legacy"}')
    e,_,_,errors=a.exposure_records([q],tmp_path)
    assert '001' not in e and e['002'][0]['status']=='UNKNOWN_EXPOSURE' and not errors


def test_parent_control_exact_length_review_and_tamper():
    e=a.load(REPO/'semantic_pallet_planner/outputs/JEV_JN3_20261104_02/contrast_snapshot.json')
    c=p.build_control(e);p.validate_control(c,e)
    assert len(c['entries'])==len(e['cards'])==2
    for row,card in zip(c['entries'],e['cards']):
        assert len(canonical(row['public_fragment']))==len(canonical(card['public_fragment']))
        assert len(canonical(row['public_fragment']).encode())==len(canonical(card['public_fragment']).encode())
        assert row['public_fragment']['kind']=='UNRELATED_NON_EVIDENCE'
    changed=copy.deepcopy(c);changed['entries'][0]['public_fragment']['text']='fake'
    changed['snapshot_digest']=digest({k:v for k,v in changed.items() if k!='snapshot_digest'})
    with pytest.raises(JevSelectError):p.validate_control(changed,e)
    changed=copy.deepcopy(c);changed['review_status']='PENDING'
    with pytest.raises(JevSelectError):p.validate_control(changed,e)


def test_six_method_budget_is_count_based_and_bounded():
    b=p.budget_for_tasks([{'task_id':'constructed','items':[{}, {}, {}]}])
    assert b['natural_job_slots']==6 and b['remote_job_slots']==4
    assert b['shared_batch_max_sends']==12
    assert [j['max_sends'] for j in b['jobs']]==[0,0,3,3,3,3]
    assert p.budget_for_tasks([])['shared_batch_max_sends']==0
    with pytest.raises(JevSelectError):p.budget_for_tasks([],2)
    with pytest.raises(JevSelectError):p.budget_for_tasks([{'task_id':'x','items':[] }])


def test_new_blocked_schema_rejects_ready_unknown_fields_and_old_plan():
    plan={'version':p.VERSION,'status':'NOT_READY','JN4_B_admitted':False,
          'frozen_at':'2026-11-05','method_registry':p.REGISTRY,'artifacts':{},'external_refs':{},
          'snapshots':{'T':'t','E':'e','control':'c'},'matrix':p.budget_for_tasks([]),
          'blockers':['missing attestation'],'plan_digest':'0'*64}
    validate_schema('evaluation_plan_blocked_v1',plan)
    for key,value in [('JN4_B_admitted',True),('status','READY'),('version','jev_memory_order_plan_v1'),('extra',True)]:
        bad=copy.deepcopy(plan);bad[key]=value
        with pytest.raises(JevSelectError):validate_schema('evaluation_plan_blocked_v1',bad)


def test_blocked_plan_integrity_and_execution_refusal(tmp_path):
    from semantic_pallet_planner.jev_select.experiment import source_manifest
    e_path='semantic_pallet_planner/outputs/JEV_JN3_20261104_02/contrast_snapshot.json'
    t_path='semantic_pallet_planner/outputs/JEV_JN3_20261104_01/trajectory_snapshot.json'
    def save(name,value):
        q=tmp_path/name;q.parent.mkdir(parents=True,exist_ok=True);q.write_text(canonical(value))
    save('source_manifest.json',source_manifest());save('split_manifest.json',{'assignments':[]})
    save('control.json',p.build_control(a.load(REPO/e_path)))
    plan={'version':p.VERSION,'status':'NOT_READY','JN4_B_admitted':False,'frozen_at':'2026-11-05',
        'method_registry':copy.deepcopy(p.REGISTRY),'artifacts':{n:a.sha(tmp_path/n) for n in ['source_manifest.json','split_manifest.json','control.json']},
        'external_refs':{e_path:a.sha(REPO/e_path),t_path:a.sha(REPO/t_path)},
        'snapshots':{'T':t_path,'E':e_path,'control':'control.json'},'matrix':p.budget_for_tasks([]),'blockers':['no verified sources']}
    def seal(value):
        value['plan_digest']=digest({k:v for k,v in value.items() if k!='plan_digest'});save('plan/plan.json',value)
    seal(plan)
    assert p.validate_plan(tmp_path,repo=REPO)['status']=='VALID_BLOCKED_PLAN'
    with pytest.raises(JevSelectError,match='JN4_B_NOT_ADMITTED'):p.validate_plan(tmp_path,repo=REPO,for_execution=True)
    changed=copy.deepcopy(plan);changed['matrix']['jobs']=[{'task_id':'outside'}];seal(changed)
    with pytest.raises(JevSelectError):p.validate_plan(tmp_path,repo=REPO)
    changed=copy.deepcopy(plan);changed['external_refs'][e_path]='0'*64;seal(changed)
    with pytest.raises(JevSelectError):p.validate_plan(tmp_path,repo=REPO)
    changed=copy.deepcopy(plan);changed['method_registry']['unregistered']={};seal(changed)
    with pytest.raises(JevSelectError):p.validate_plan(tmp_path,repo=REPO)
    seal(plan);save('control.json',{})
    with pytest.raises(JevSelectError):p.validate_plan(tmp_path,repo=REPO)
