"""JN2-B control/label tests; fabricated outcomes never count as training suffixes."""
import copy
from functools import lru_cache
from pathlib import Path
import tempfile
import pytest
from semantic_pallet_planner.jev_select import packaging_comparisons as c
from semantic_pallet_planner.jev_select import packaging_counterfactual as f
from semantic_pallet_planner.jev_select.contracts import digest,JevSelectError,validate_schema
from semantic_pallet_planner.jev_select.ledger import read,write

A=c.REPO/c.A_DEFAULT


def metric(volume=.5,items=5,mass=.5,height=200,envelope=.6,complete=False):
    return {'version':'jev_training_branch_metrics_v1','stable_complete':complete,
            'loading':{'placed_volume_ratio':volume,'placed_item_ratio':items/10,'placed_mass_ratio':mass,'placed_items':items,'placed_mass_kg':mass*100},
            'actual_height_mm':height,'envelope_utilization':envelope,'fixed_container_utilization':volume/2,
            'branch_metrics':{},'category':'EMPTY_POOL','monitor_statuses':{},'cost':{}}


def receipt(m=None,category='EMPTY_POOL'):
    return {'status':{'category':category},'metrics':metric() if m is None else m}


@pytest.mark.parametrize('change,label',[
 ({},'neutral'),({'volume':.6},'improved'),({'volume':.4},'degraded'),
 ({'volume':.6,'height':210},'trade_off'),({'volume':.4,'height':190},'trade_off'),
 ({'envelope':.7,'height':190},'improved'),({'envelope':.5,'height':210},'degraded'),
 ({'volume':.5+1e-10},'neutral'),({'complete':True,'volume':.4},'trade_off'),
 ({'height':190,'envelope':.5},'trade_off')])
def test_frozen_label_boundaries(change,label):
    valid,actual,reasons,delta=c.classify(receipt(),receipt(metric(**change)))
    assert valid and not reasons and actual==label
    assert delta['placed_volume_ratio']==metric(**change)['loading']['placed_volume_ratio']-.5


@pytest.mark.parametrize('category',['ERROR','TECHNICAL_LIMIT','CANCELED','NOT_RUN','UNASSESSABLE','COMMIT_FAILURE','SELECTION_FAILURE'])
def test_invalid_not_causal_label(category):
    valid,label,reasons,delta=c.classify(receipt(),receipt(metric(volume=.9),category))
    assert not valid and label=='invalid' and reasons and delta['placed_volume_ratio']==.4
    assert c.classify(receipt(),{'metrics':'NOT_RUN','status':{'category':category}})[3]=='NOT_AVAILABLE'


def test_empty_volume_na_and_public_utilization_not_ranking():
    r=receipt(metric(volume=0,items=0,mass=0,height='NA',envelope='NA'))
    assert c.classify(r,r)[1]=='neutral'
    a=receipt();b=copy.deepcopy(a);b['metrics']['fixed_container_utilization']=.99
    assert c.classify(a,b)[1]=='neutral'


def test_matrix_outcome_independent_two_sources():
    matrix=c.decision_matrix(A)
    assert [e['decision_id'] for e in matrix]==['J0000_D0000','J0000_D0005','J0003_D0000','J0003_D0003']
    assert [e['mode'] for e in matrix]==['REUSE_A','NEW','NEW','NEW']
    assert len({e['source_group'] for e in matrix})==2


@lru_cache(maxsize=1)
def saved_payloads():
    ap=read(A/'branch_plan.json');result={}
    for e in c.decision_matrix(A):
        s=f.restore_training_fork(c.REPO/ap['parent_identity']['parent'],e['decision_id'])
        t=read(c.REPO/s['field_evidence']['task']);cfg=copy.deepcopy(ap['config'])
        cfg['runtime_identity']['task_identity']=digest(t)
        # Explicitly synthetic strategy credential, not used to execute a suffix.
        if e['mode']!='REUSE_A':cfg['runtime_identity']['strategy_identity']=digest(['SYNTHETIC_CONTROL_ONLY',t['task_id']])
        result[e['decision_id']]={'snapshot':s,'task':t,'config':cfg,'selection':f.interventions(s)}
    return result


@pytest.fixture
def prepared(monkeypatch):
    with tempfile.TemporaryDirectory(dir=c.REPO/'semantic_pallet_planner/outputs',prefix='.JN2B_CONSTRUCTED_') as tmp:
        root=Path(tmp)/'collection';calls=[]
        def fake_worker(root,command,*,decision=None,child=None):
            if command=='identity':value={'source_digest':digest(read(A/'source_manifest.json')),'environment':read(A/'environment.json')['execution_environment'],'monitor':read(A/'branch_plan.json')['config']['stability_monitor']}
            elif command=='audit-a':value={'status':'PASS_CONSTRUCTED_CONTROL_STUB'}
            elif command=='snapshot':value=copy.deepcopy(saved_payloads()[decision])
            elif command=='run':
                calls.append(child.name);p=read(child/'branch_plan.json')
                for jid in p['branch_order']:
                    job=child/'branches'/jid;b=read(job/'binding.json');status={'state':'FINISHED','category':'EMPTY_POOL','active_wall_s':1.,'error':None}
                    write(job/'status.json',status)
                    m=metric();m['category']='EMPTY_POOL'
                    r=f.seal({'version':'jev_branch_receipt_v1','job_id':jid,'plan_digest':digest(p),'binding_digest':digest(b),'fork_digest':p['fork_digest'],
                        'first':b['first'],'continuation':p['continuation'],'status':status,'checkpoint_digest':None,'metrics':m,'model_calls':0,'comparison_labels':'DEFERRED_TO_JN2_B'})
                    write(job/'branch_receipt.json',r)
                value={'branches':[{'category':'EMPTY_POOL'}]*3}
            else:value={'status':'PASS_CONSTRUCTED_CONTROL_STUB'}
            return {'status':'OK','command':command,'value':value,'guard_counts':{}}
        monkeypatch.setattr(c,'worker',fake_worker)
        p=c.prepare(A,root)
        yield root,p,calls,fake_worker


def test_plan_freeze_budget_and_resealed_input_reject(prepared):
    root,p,_,_=prepared
    assert p['budget']['A_used']==3 and p['budget']['B_registered']==9 and p['budget']['total_registered']==12
    c.validate_plan(root)
    payload_path=root/'inputs/F01.json';payload=read(payload_path);payload['value']['snapshot']['state']['arrival_count']+=1;write(payload_path,payload)
    with pytest.raises(JevSelectError):c.validate_plan(root)


@pytest.mark.parametrize('field',['decision','budget','root','watchdog','label','source'])
def test_resigned_plan_or_unplanned_task_reject(prepared,field):
    root,p,_,_=prepared;p=copy.deepcopy(p)
    if field=='decision':p['entries'][1]['decision_id']='TEST_SOURCE_D0000'
    elif field=='budget':p['budget']['B_registered']=12
    elif field=='root':p['root']+='COPY'
    elif field=='watchdog':p['watchdog']['max_events']=8
    elif field=='label':p['label_rule']['absolute_equivalence']['ratio']=.5
    else:p['entries'][1]['source_group']='TEST_SOURCE'
    f.seal(p);write(root/'comparison_plan.json',p);write(root/'plan_anchor.json',{'plan_digest':digest(p),'root':c.rel(root)})
    with pytest.raises(JevSelectError):c.validate_plan(root)


def test_pause_resume_reuse_and_full_denominator(prepared):
    root,p,calls,fake=prepared
    out=c.run(root,stop_after_groups=1)
    assert calls==['F01'] and out['budget']['cumulative_started']==6 and out['labels']['invalid']==4
    assert read(root/'batch_status.json')['state']=='PAUSED'
    out=c.run(root,resume=True)
    assert calls==['F01','F02','F03'] and out['budget']['cumulative_started']==12 and out['comparisons']==8
    assert len(read(root/'batch_history.json'))==2
    assert len(list((root/'comparisons').glob('*.json')))==8
    assert c.records(root,p)==[read(root/'comparisons'/f"{r['comparison_id']}.json") for r in c.records(root,p)]
    assert all('J0000_D0000' not in x for x in calls)


@pytest.mark.parametrize('failure',['ERROR','CANCELED','TECHNICAL_LIMIT'])
def test_failure_stops_remaining_and_no_retry(prepared,monkeypatch,failure):
    root,p,calls,real=prepared
    def failed(root,command,**kw):
        if command=='run':
            child=kw['child'];calls.append(child.name)
            if failure=='CANCELED':raise KeyboardInterrupt()
            if failure=='ERROR':raise RuntimeError('CONSTRUCTED_FAILURE')
            status=read(child/'branches/B00/status.json');status.update(state='FINISHED',category='TECHNICAL_LIMIT');write(child/'branches/B00/status.json',status)
            return {'status':'OK','value':{'branches':[{'category':'TECHNICAL_LIMIT'}]},'guard_counts':{}}
        return real(root,command,**kw)
    monkeypatch.setattr(c,'worker',failed)
    out=c.run(root)
    assert calls==['F01'] and read(root/'batch_status.json')['state']=='STOPPED'
    if failure=='TECHNICAL_LIMIT':assert read(root/'forks/F01/branches/B00/branch_receipt.json')['status']['category']=='TECHNICAL_LIMIT'
    assert out['budget']['cumulative_started']<=4 and out['labels']['invalid']==6
    assert all((root/f'forks/F0{i}/branches/B0{j}/branch_receipt.json').exists() for i in (1,2,3) for j in (0,1,2))
    before=list(calls)
    # Terminal batch may validate but may not dispatch more suffixes.
    monkeypatch.setattr(c,'validate',lambda *a,**kw:{'status':'PASS_CONTROL_ONLY'})
    assert c.run(root,resume=True)==out and calls==before


def test_schema_refuses_invalid_benefit_label():
    parent=read(A/'branches/B00/branch_receipt.json');alt=read(A/'branches/B01/branch_receipt.json');s=read(A/'fork_snapshot.json');ap=read(A/'branch_plan.json')
    e={'group_id':'F00','source_group':ap['source_group'],'task_id':'TASK','decision_id':ap['decision_id'],'fork_digest':ap['fork_digest'],'first_actions':ap['selection']['branches'],'native_probability_complete':True}
    row=c.comparison_record(e,s,parent,alt,'ref','alt',digest(ap['source_manifest']))
    assert row['label']=='neutral'
    row['comparison_valid']=False;row['invalid_reasons']=[{'side':'alternative','category':'UNASSESSABLE'}]
    with pytest.raises(JevSelectError):validate_schema('packaging_comparison_record_v1',f.seal(row))
    bad=copy.deepcopy(alt);bad['fork_digest']=digest('WRONG');f.seal(bad)
    with pytest.raises(JevSelectError):c.comparison_record(e,s,parent,bad,'ref','alt',digest(ap['source_manifest']))


def test_actual_frozen_package_identity_isolation():
    # Real archived imports and environment preflight, but no branch execution.
    before=f.file_manifest(A)
    with tempfile.TemporaryDirectory(dir=c.REPO/'semantic_pallet_planner/outputs',prefix='.JN2B_IDENTITY_') as tmp:
        root=Path(tmp);write(root/'parent_reference.json',c.checked_manifest(A));c.stage_runtime(A,root)
        result=c.worker(root,'identity')
        assert result['value']['source_digest']==digest(read(A/'source_manifest.json'))
        assert result['value']['source_digest']!=digest(c.source_manifest())
        assert all(v==0 for v in result['guard_counts'].values())
    assert before==f.file_manifest(A)


def test_unknown_start_stops_without_dispatch(prepared):
    root,p,calls,_=prepared
    write(root/'group_status/F01.json',{'state':'RUNNING','error':None})
    out=c.run(root)
    assert not calls and out['labels']['invalid']==6
    assert read(root/'group_status/F01.json')['error']=='UNKNOWN_START_NO_IMPLICIT_RETRY'


def test_empty_collection_and_no_improvement_are_not_ready():
    p={'execution_source_manifest':{},'analysis_source_manifest':{}}
    summary={'eligible_improved_pairs':[],'experience_input_status':'NOT_READY','labels':{k:0 for k in ('improved','neutral','degraded','trade_off','invalid')},
             'valid':0,'invalid':0,'source_groups':[],'coverage':{},'coverage_gaps':{},'budget':{'rows':[]}}
    result=c.dataset_receipt(p,summary,[],'FINISHED')
    assert result['experience_input_status']=='NOT_READY' and result['records']==[]
    summary['labels']['trade_off']=1
    assert c.dataset_receipt(p,summary,[],'FINISHED')['experience_input_status']=='NOT_READY'


def test_saved_record_recompute_rejects_resigned_outer_tamper(tmp_path,monkeypatch):
    # Real A receipts are read only. Only the newly derived comparison is edited.
    ap=read(A/'branch_plan.json');payload={'value':{'snapshot':read(A/'fork_snapshot.json')}}
    e={'group_id':'F00','decision_id':ap['decision_id'],'source_group':ap['source_group'],'task_id':read(A/'task.private.json')['task_id'],
       'mode':'REUSE_A','location':c.rel(A),'fork_digest':ap['fork_digest'],'first_actions':ap['selection']['branches'],
       'native_probability_complete':True,'coverage_gaps':[]}
    p={'version':c.VERSION,'entries':[e],'budget':{'B_registered':0},'execution_source_manifest':ap['source_manifest'],'analysis_source_manifest':c.source_manifest()}
    write(tmp_path/'inputs/F00.json',payload);write(tmp_path/'batch_status.json',{'state':'FINISHED'})
    monkeypatch.setattr(c,'validate_plan',lambda *a,**kw:p)
    out=c.derive(tmp_path,p);assert out['labels']['neutral']==1 and out['labels']['trade_off']==1
    c.validate(tmp_path,deep=False)
    path=tmp_path/'comparisons/F00_B02.json';row=read(path);row['label']='improved';row['delta']['placed_items']=99
    write(path,f.seal(row));write(tmp_path/'delivery_manifest.json',{'files_sha256':f.file_manifest(tmp_path)})
    with pytest.raises(JevSelectError,match='resigned_record_changed'):c.validate(tmp_path,deep=False)


def test_category_gap_remains_in_dataset(prepared,monkeypatch):
    root,p,calls,_=prepared
    # Testing the summary's legal missing-category representation, not changing
    # an actual frozen plan or expanding any candidate pool.
    p=copy.deepcopy(p);p['entries'][0]['coverage_gaps']=['CROSS_BOX_SELECTION']
    write(root/'batch_status.json',{'state':'PAUSED'})
    out=c.derive(root,p)
    assert out['coverage_gaps']['F00']==['CROSS_BOX_SELECTION'] and out['comparisons']==8
    assert read(root/'comparison_dataset_receipt.json')['experience_input_status']=='NOT_READY'
