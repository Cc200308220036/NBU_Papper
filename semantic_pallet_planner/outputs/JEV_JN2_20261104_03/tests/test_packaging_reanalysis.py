"""Pure evaluation and saved-evidence tests. Never execute any branch."""
import copy
import json
from pathlib import Path

import pytest

from semantic_pallet_planner.jev_select import packaging_reanalysis as r
from semantic_pallet_planner.jev_select import packaging_comparisons as v1
from semantic_pallet_planner.jev_select.contracts import JevSelectError, digest, validate_schema
from semantic_pallet_planner.jev_select.ledger import read, write


def view(**changes):
    x = {'task_digest':'task-a','data_identity':'data-a',
         'denominators':{'items':10,'mass_kg':100.,'volume_mm3':1000.},
         'category':'EMPTY_POOL','stable_complete':False,'placed_items':5,
         'placed_volume_ratio':.5,'placed_mass_kg':50.,'actual_height_mm':200.,'envelope_utilization':.5}
    x.update(changes); return x


def evaluate(a=None,b=None):
    return r.evaluate(a or view(),b or view(),rule_version=r.RULE_VERSION)


@pytest.mark.parametrize('changes,label,level',[
    ({'placed_volume_ratio':.6,'actual_height_mm':300.},'improved','LOADED_VOLUME'),
    ({'placed_volume_ratio':.4,'actual_height_mm':100.},'degraded','LOADED_VOLUME'),
    ({'placed_volume_ratio':.6,'placed_items':4,'placed_mass_kg':40.,'actual_height_mm':300.,'envelope_utilization':.4},'improved','LOADED_VOLUME'),
    ({'placed_items':6},'improved','COUNT_MASS'),
    ({'placed_mass_kg':51.},'improved','COUNT_MASS'),
    ({'placed_items':4},'degraded','COUNT_MASS'),
    ({'placed_items':4,'placed_mass_kg':51.},'trade_off','COUNT_MASS'),
    ({'placed_items':6,'placed_mass_kg':49.},'trade_off','COUNT_MASS'),
    ({'actual_height_mm':190.},'improved','COMPACTNESS'),
    ({'actual_height_mm':210.},'degraded','COMPACTNESS'),
    ({'actual_height_mm':190.,'envelope_utilization':.4},'trade_off','COMPACTNESS'),
    ({},'neutral','COMPACTNESS'),
])
def test_hierarchy(changes,label,level):
    result=evaluate(b=view(**changes))
    assert result['comparison_valid'] and result['label_v2']==label and result['decisive_level']==level


def test_all_secondary_costs_visible():
    x=evaluate(b=view(placed_volume_ratio=.6,placed_items=4,placed_mass_kg=40.,actual_height_mm=300.,envelope_utilization=.4))
    assert all(s['regressed'] for s in x['secondary_regressions'])


def test_stable_complete_precedes_other_layers():
    # Completion wins even where volume equivalence tolerance absorbs the gap.
    a=view(placed_items=9,placed_mass_kg=100.,placed_volume_ratio=1-5e-10)
    b=view(category='COMPLETE',stable_complete=True,placed_items=10,placed_mass_kg=100.,placed_volume_ratio=1.,actual_height_mm=500.,envelope_utilization=.2)
    x=evaluate(a,b); assert x['label_v2']=='improved' and x['decisive_level']=='STABLE_COMPLETION'
    assert evaluate(b,a)['label_v2']=='degraded'


@pytest.mark.parametrize('category',['ERROR','UNASSESSABLE','CANCELLED','WATCHDOG','NOT_RUN','TECHNICAL_LIMIT','UNKNOWN_SEND'])
def test_invalid_stops(category):
    for side in [0,1]:
        pair=[view(),view(placed_volume_ratio=.6)]; pair[side]['category']=category
        assert evaluate(*pair)['label_v2']=='invalid'


def test_predicted_instability_uses_committed_amount_only():
    # An uncommitted attempt is deliberately absent from the committed view.
    b=view(category='PREDICTED_STATIC_INSTABILITY',placed_volume_ratio=.4,placed_items=4,placed_mass_kg=40.)
    x=evaluate(b=b);assert x['comparison_valid'] and x['label_v2']=='degraded'


@pytest.mark.parametrize('key,value',[
    ('placed_items',5.0),('placed_items',None),('placed_mass_kg',float('nan')),
    ('placed_volume_ratio',float('inf')),('actual_height_mm',float('nan')),
    ('stable_complete',None),('placed_items',11),('placed_volume_ratio',1.1),
    ('placed_items',-1),('data_identity',None),('task_digest','different-task'),
])
def test_bad_metrics(key,value):
    assert evaluate(b=view(**{key:value}))['label_v2']=='invalid'


@pytest.mark.parametrize('key',['items','mass_kg','volume_mm3'])
def test_unequal_denominators(key):
    b=view();b['denominators'][key]+=1
    assert evaluate(b=b)['label_v2']=='invalid'


def test_invalid_denominators():
    for v in [0,float('inf'),None]:
        a=view();a['denominators']['volume_mm3']=v
        assert evaluate(a,a)['label_v2']=='invalid'


def test_compactness_missing_not_neutral():
    x=evaluate(b=view(actual_height_mm=None));assert x['label_v2']=='invalid' and x['metric_gaps']
    x=evaluate(b=view(placed_volume_ratio=.6,actual_height_mm=None))
    assert x['label_v2']=='improved' and x['metric_gaps']


def test_legal_empty_and_invalid_empty():
    a=view(placed_items=0,placed_volume_ratio=0.,placed_mass_kg=0.,actual_height_mm=None,envelope_utilization=None)
    x=evaluate(a,a); assert x['label_v2']=='neutral' and x['compactness_status']=='NOT_APPLICABLE'
    assert evaluate(a,{**a,'placed_mass_kg':1.})['label_v2']=='invalid'


@pytest.mark.parametrize('delta,label',[(.5e-9,'neutral'),(1e-9,'neutral'),(1.1e-9,'improved')])
def test_volume_tolerance(delta,label):
    # Use zero baseline for exact representability of the registered threshold.
    a=view(placed_volume_ratio=0.);b=view(placed_volume_ratio=delta)
    assert evaluate(a,b)['label_v2']==label


@pytest.mark.parametrize('key,tol,level',[('placed_mass_kg',1e-9,'COUNT_MASS'),('actual_height_mm',1e-6,'COMPACTNESS'),('envelope_utilization',1e-9,'COMPACTNESS')])
def test_numeric_tolerances(key,tol,level):
    a=view();b=view();b[key]=a[key]+tol*.5
    assert evaluate(a,b)['label_v2']=='neutral'
    b[key]=a[key]+tol*2
    x=evaluate(a,b);assert x['label_v2']!='neutral' and x['decisive_level']==level


def test_version_dispatch_and_v1_unchanged():
    parent=r.REPO/'semantic_pallet_planner/outputs/JEV_JN2_20261104_02'
    old=read(parent/'comparisons/F00_B02.json');a=old['reference_result'];b=old['alternative_result']
    assert r.evaluate(a,b,rule_version=v1.LABEL_RULE['version'])==v1.classify(a,b)
    assert v1.classify(a,b)[1]=='trade_off'
    with pytest.raises(JevSelectError):r.evaluate(a,b,rule_version='v999')


def test_ids_do_not_determine_labels():
    a=view();b=view(placed_volume_ratio=.6)
    a['comparison_id']=b['comparison_id']='arbitrary-same-id'
    assert evaluate(a,b)['label_v2']=='improved'
    b['placed_volume_ratio']=.4
    assert evaluate(a,b)['label_v2']=='degraded'


def fake_row(**changes):
    e=evaluate(b=view(**changes))
    return {'comparison_id':'arbitrary', 'evaluation':e, 'metric_views':{'reference':view(),'alternative':view(**changes)},
            'evidence_checks':{k:True for k in r.ADMISSION['required_checks'] if k!='no_label_or_order_shortcut'},
            'provenance':{'path':'fixture-only'},'observable_conditions':{'public':'geometry only'},'diagnostics':{}}


def test_compactness_not_loading_candidate():
    x=fake_row(actual_height_mm=190.)
    assert x['evaluation']['label_v2']=='improved' and not r.loading_candidate(x)
    assert not r.review_candidate(x)['approved']


def test_candidate_and_approval_separate():
    x=fake_row(placed_volume_ratio=.6,actual_height_mm=None)
    x['evidence_checks']['metrics_costs_complete']=False
    assert r.loading_candidate(x) and not r.review_candidate(x)['approved']
    x=fake_row(placed_volume_ratio=.6)
    assert r.review_candidate(x)['approved']
    x['evidence_checks']['parent_verified']=False
    assert r.loading_candidate(x) and not r.review_candidate(x)['approved']


def test_shortcut_material_rejected():
    x=fake_row(placed_volume_ratio=.6);x['observable_conditions']={'advice':'C02'}
    assert not r.review_candidate(x)['approved']


def test_empty_summary_not_ready():
    p={'inventory':[],'parent':{},'analysis_source_digest':'a','execution_source_digest':'b','historical_suffixes':12,'parent_verification_digest':'a'}
    outputs=r.summaries([],p);g=outputs['comparison_dataset_receipt_v2.json']
    assert not g['engineering_complete'] and not g['loading_candidates_nonempty'] and not g['JN3_A_input_ready']


def test_receipt_tamper_and_reseal_rejected(tmp_path):
    source=r.REPO/'semantic_pallet_planner/outputs/JEV_JN2_20261104_01'
    import shutil
    for n in ['branch_plan.json','task.private.json']:
        shutil.copyfile(source/n,tmp_path/n)
    job=tmp_path/'branches/B00';job.mkdir(parents=True)
    for n in ['status.json','binding.json','checkpoint.json','branch_receipt.json']:
        shutil.copyfile(source/'branches/B00'/n,job/n)
    r.verify_branch(tmp_path,'B00')
    receipt=read(job/'branch_receipt.json');receipt['metrics']['loading']['placed_items']+=1
    write(job/'branch_receipt.json',r.fork.seal(receipt))
    with pytest.raises(JevSelectError):r.verify_branch(tmp_path,'B00')


def test_original_failed_attempt_not_added_to_derived_metrics(tmp_path):
    # Existing metric implementation's branch totals read committed state only.
    source=r.REPO/'semantic_pallet_planner/outputs/JEV_JN2_20261104_01'
    plan=read(source/'branch_plan.json');task=read(source/'task.private.json')
    cp=read(source/'branches/B00/checkpoint.json');binding=read(source/'branches/B00/binding.json')
    status=read(source/'branches/B00/status.json');status['category']='PREDICTED_STATIC_INSTABILITY'
    cp['reason']='PREDICTED_STATIC_INSTABILITY'
    metrics=r.fork.branch_metrics(task,plan['config'],cp,status,binding['snapshot'])
    assert metrics['branch_metrics']['final']['items']==len(cp['state']['placed_items'])
    assert metrics['loading']['placed_items']==len(cp['state']['placed_items'])


def test_closed_schemas():
    for name in ['packaging_reanalysis_plan_v2','packaging_comparison_record_v2']:
        with pytest.raises(JevSelectError):validate_schema(name,{'unexpected':True})


def test_all_original_pairs_recomputed_without_execution():
    parent=r.REPO/'semantic_pallet_planner/outputs/JEV_JN2_20261104_02'
    pp=read(parent/'comparison_plan.json');rows=[]
    plan={'parent':v1.checked_manifest(parent),'analysis_source_digest':digest(r.source_manifest()),'execution_source_digest':digest(pp['execution_source_manifest'])}
    for item in r.inventory(parent):
        row=r.derive_record(parent,plan,item)
        assert row['original_delta']==read(r.REPO/item['v1_path'])['delta']
        assert row['evaluation']['comparison_valid']
        rows.append(row)
    assert len(rows)==8
    assert {k:sum(x['evaluation']['label_v2']==k for x in rows) for k in ['neutral','improved']}=={'neutral':6,'improved':2}
    candidates=[r.review_candidate(x) for x in rows if r.loading_candidate(x)]
    assert len(candidates)==2 and all(x['approved'] for x in candidates)


def test_saved_v2_record_and_readiness_tamper_rejected(tmp_path, monkeypatch):
    # Controlled fixture uses one original pair; only new derived files mutate.
    parent=r.REPO/'semantic_pallet_planner/outputs/JEV_JN2_20261104_02'
    pp=read(parent/'comparison_plan.json')
    p={'parent':v1.checked_manifest(parent),'analysis_source_digest':digest(r.source_manifest()),
       'execution_source_digest':digest(pp['execution_source_manifest']),
       'inventory':r.inventory(parent)[:1],'historical_suffixes':12,'parent_verification_digest':'fixture',
       'frozen_at_utc':'2026-11-04T00:00:00+00:00'}
    row=r.derive_record(tmp_path,p,p['inventory'][0]);outputs=r.summaries([row],p)
    monkeypatch.setattr(r,'derive',lambda root:([row],outputs))
    write(tmp_path/'analysis_plan.json',p)
    write(tmp_path/'analysis_start_receipt.json',{'plan_digest':digest(p),'analysis_type':r.TYPE,'started_at_utc':p['frozen_at_utc']})
    path=tmp_path/'comparisons_v2'/f"{row['comparison_id']}.json";write(path,row)
    for n,v in outputs.items():write(tmp_path/n,v)
    assert r.validate(tmp_path)['status']=='PASS'
    wrong=copy.deepcopy(row);wrong['evaluation']['label_v2']='improved';write(path,r.fork.seal(wrong))
    with pytest.raises(JevSelectError,match='saved_record_changed'):r.validate(tmp_path)
    write(path,row)
    receipt=copy.deepcopy(outputs['comparison_dataset_receipt_v2.json']);receipt['JN3_A_input_ready']=True
    write(tmp_path/'comparison_dataset_receipt_v2.json',receipt)
    with pytest.raises(JevSelectError,match='saved_comparison_dataset_receipt'):r.validate(tmp_path)


def test_v2_schema_rejects_nested_extra_and_invalid_benefit():
    parent=r.REPO/'semantic_pallet_planner/outputs/JEV_JN2_20261104_02';pp=read(parent/'comparison_plan.json')
    p={'parent':v1.checked_manifest(parent),'analysis_source_digest':digest(r.source_manifest()),'execution_source_digest':digest(pp['execution_source_manifest'])}
    row=r.derive_record(parent,p,r.inventory(parent)[0])
    row['evaluation']['unexpected']='closed'
    with pytest.raises(JevSelectError):validate_schema('packaging_comparison_record_v2',row)
    del row['evaluation']['unexpected'];row['evaluation']['comparison_valid']=False
    with pytest.raises(JevSelectError):validate_schema('packaging_comparison_record_v2',row)
