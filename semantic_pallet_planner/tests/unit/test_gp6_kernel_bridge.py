"""Actual two-contract gate regression; synthetic credentials exist only in /tmp."""
import copy
import io
import json
from pathlib import Path
import subprocess
import sys
import tarfile
from unittest.mock import patch

import pytest
from semantic_pallet_planner.jev_select.contracts import canonical, digest, JevSelectError
from semantic_pallet_planner.jev_select.packaging_geometry_protocol import adapt_task, synthetic_task, sha, TASK_IDS
from semantic_pallet_planner.jev_select.geometry_jev_protocol import (
    prepare_jev_plan, GP6_ORDER, GP6_ENDPOINT, jev_identity_fields, validate_jev_admission)
from semantic_pallet_planner.jev_select.geometry_jev_kernel_bridge import source_delta, target_binding
from semantic_pallet_planner.jev_select.experiment import source_manifest
from semantic_pallet_planner.jev_select.geometry_jev_execution import run_jev_job, GeometryJevRequestLedger
from semantic_pallet_planner.jev_select.geometry_order_meter import metered_jev_run, current_counts
from semantic_pallet_planner.jev_select.stability import exact_adapter, balance_network
from test_gp6_jev_integration import FakeChoiceTransport


def ref(path, value=None):
    if value is not None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(canonical(value))
    return {'path':str(path),'sha256':sha(path.read_bytes())}


@pytest.fixture(scope='module')
def fixture(tmp_path_factory):
    root=tmp_path_factory.mktemp('gp6_bridge')
    assert root.is_relative_to(Path('/tmp'))
    package=root/'historical'/'semantic_pallet_planner'
    archive=subprocess.check_output(['git','archive','1c6c85613','semantic_pallet_planner/src/semantic_pallet_planner'])
    historical=json.loads(Path('semantic_pallet_planner/outputs/GEOM_CANDIDATES_GP5_P2_FINAL_RUNTIME_20261120_01/source_manifest.json').read_bytes())
    with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
        for member in tar.getmembers():
            if not member.isfile():continue
            name=member.name.split('src/semantic_pallet_planner/')[1]
            raw=tar.extractfile(member).read()
            if name in historical['files']:assert sha(raw)==historical['files'][name]
            path=package/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(raw)
    builder=Path('semantic_pallet_planner/tests/fixtures/gp6_kernel_bridge_synthetic.py').resolve()
    result=subprocess.run([sys.executable,'-B','-c',
        'import sys,runpy; sys.path.insert(0,sys.argv.pop(1)); runpy.run_path(sys.argv.pop(1),run_name="__main__")',
        str(package.parent),str(builder),str(root/'SYNTHETIC_ONLY')],capture_output=True,text=True,
        env={'PYTHONDONTWRITEBYTECODE':'1'})
    assert result.returncode==0,result.stderr
    evidence=root/'SYNTHETIC_ONLY'
    monitor=json.loads((evidence/'monitor.json').read_bytes())
    adapted=[]
    for tid in TASK_IDS:
        item={**synthetic_task('K01')['items'][0], 'geometry_id':'SYNTHETIC_ONLY', 'material':'synthetic'}
        original=copy.deepcopy(item)
        item.update(sku_id='SYNTHETIC_ONLY',packaging_profile_id='SYNTHETIC_ONLY',max_top_load_kg=10,
            effective_top_permission_kg=10,physical_provenance='SYNTHETIC_ONLY',
            capacity_provenance='controlled_synthetic_experimental',original_physical=original)
        task={'version':'jev_packaging_load_dataset_v1','task_id':tid,'scenario_id':'SYNTHETIC_ONLY',
            'source_group_id':'SG_901bbb22f834c63f','source_order_key':'SYNTHETIC_ONLY','source_order_id':'SYNTHETIC_ONLY',
            'partition':'train','mode':'controlled_packaging','layer':'controlled_base','buffer_capacity':3,
            'candidate_limits':{'per_box':16,'joint':48},'container':synthetic_task('K01')['container'],
            'arrival_order':[item['item_id']],'mass_distribution':'uniform','centroid_model':'geometric_center',
            'geometry_contract_version':'jev_packaging_geometry_v1','regions':[],'rules':[],'items':[item],
            'feasibility_status':'UNKNOWN','static_screen_status':'STATIC_SCREEN_PASSED',
            'witness':{'status':'NOT_AVAILABLE','candidate_reachability':'NOT_RUN','online_solvability':'NOT_RUN'},
            'runtime_compatibility':'NOT_RUN_TARGET_TWO_REQUIRED'}
        raw=canonical(task).encode();adapted.append(adapt_task(raw,origin='EXPOSED_TRAIN',expected_sha256=sha(raw)))
    plan=prepare_jev_plan(adapted,data_identity=digest('SYNTHETIC_ONLY'),scope=GP6_ORDER,
        request_ledger_path=str(root/'requests'/'requests.json'),call_ledger_path=str(root/'target_calls.json'))
    plan['status']='FROZEN' # temporary fabricated plan, never freeze() or archive as a permit
    target=target_binding(plan,monitor)
    bridge={'version':'geometry_jev_kernel_bridge_v1','status':'APPROVED',
        'evidence_receipt':ref(evidence/'receipt.json'),
        'historical_source_manifest':ref(root/'historical_manifest.json',historical),
        'historical_package_root':str(package),'historical_monitor':ref(evidence/'monitor.json'),'target':target}
    delta=source_delta(historical['files'],source_manifest())
    review={'version':'geometry_jev_kernel_applicability_review_v1','status':'APPROVED',
        **{k:bridge[k] for k in ('evidence_receipt','historical_source_manifest','historical_monitor','target')},
        'diff_digest':digest(delta),'changes':[{**r,'rationale':'SYNTHETIC_ONLY offline contract exercise'} for r in delta],
        'reviewer':'SYNTHETIC_ONLY','conclusion':'SYNTHETIC_ONLY','limitations':'NO PRODUCTION AUTHORITY'}
    bridge['applicability_review']=ref(root/'applicability.json',review)
    approval={'scope':GP6_ORDER,'plan_digest':digest(plan),'status':'APPROVED'}
    admission={**jev_identity_fields(),'version':'geometry_jev_admission_v1',**approval,
        **{k:plan[k] for k in ('source_identity','environment_digest')},'monitor_digest':digest(monitor),
        'authorization':ref(root/'auth.json',approval),'review':ref(root/'scope.json',approval),
        'api_spec_check':ref(root/'api.json',{'status':'VERIFIED','model':plan['model'],'endpoint':GP6_ENDPOINT})}
    return root,plan,monitor,admission,bridge,adapted


def test_positive_both_contracts_and_actual_meter(fixture):
    root,plan,monitor,admission,bridge,_=fixture
    assert validate_jev_admission(plan,monitor,admission,bridge) is True
    # Actual shared meter entry, with only assessment and LP bodies substituted.
    # Neither the bridge nor admission nor historical v17 validation is patched.
    with patch.object(exact_adapter,'assess_candidate',return_value='OFFLINE') as assess, \
         patch.object(balance_network,'linprog',return_value='OFFLINE') as lp:
        with metered_jev_run(plan,job_id='G00',monitor_snapshot=monitor,admission=admission,kernel_receipt=bridge):
            assert exact_adapter.assess_candidate(None,None,None)=='OFFLINE'
            assert balance_network.linprog(None)=='OFFLINE'
            assert current_counts(digest(plan))=={'assessment_entries':1,'solver_calls':1,'test_double_assessments':0}
        assert assess.call_count==lp.call_count==1
    assert not (root/'requests').exists()  # meter needs no model dispatch


@pytest.mark.parametrize('case',[
    'bare_v17','missing','receipt_bytes','review_bytes','completion_bytes','record_bytes','ledger_bytes',
    'target_plan','target_source','target_environment','target_publication','target_monitor','target_algorithm',
    'historical_source','diff_missing','review_binding','no_user_authorization','no_scope_review','no_api_check'])
def test_rejections_before_send_assess_commit(fixture,case):
    root,plan,monitor,admission,bridge,adapted=fixture
    b=copy.deepcopy(bridge);a=copy.deepcopy(admission);restore=None
    if case=='bare_v17':b=json.loads(Path(b['evidence_receipt']['path']).read_bytes())
    elif case=='missing':b=None
    elif case in ('receipt_bytes','review_bytes','completion_bytes','record_bytes','ledger_bytes','historical_source'):
        receipt=json.loads(Path(b['evidence_receipt']['path']).read_bytes())
        path=Path({'receipt_bytes':b['evidence_receipt']['path'],'review_bytes':b['applicability_review']['path'],
            'completion_bytes':receipt['review']['path'],'record_bytes':receipt['records'][0]['path'],
            'ledger_bytes':receipt['counter_log']['path'],
            'historical_source':str(Path(b['historical_package_root'])/'jev_select/geometry_execution.py')}[case])
        restore=(path,path.read_bytes());path.write_bytes(restore[1]+b' ')
    elif case.startswith('target_'):
        key={'plan':'plan_digest','source':'source_identity','environment':'environment_digest',
             'publication':'publication_policy_digest','monitor':'monitor_digest','algorithm':'algorithm_digest'}[case[7:]]
        b['target'][key]='0'*64
    elif case in ('diff_missing','review_binding'):
        review=json.loads(Path(b['applicability_review']['path']).read_bytes())
        if case=='diff_missing':review['changes'].pop()
        else:review['target']['plan_digest']='0'*64
        b['applicability_review']=ref(root/(case+'.json'),review)
    else:
        key={'no_user_authorization':'authorization','no_scope_review':'review','no_api_check':'api_spec_check'}[case]
        a[key]=ref(root/(case+'.json'),{})
    transport=FakeChoiceTransport(origin='jev')
    ledger=GeometryJevRequestLedger(root/'requests',plan_digest=digest(plan),per_job_max_sends=19,shared_max_sends=76,allow_real_transport=True)
    try:
        with patch.object(exact_adapter,'assess_candidate',side_effect=AssertionError('ASSESS_FORBIDDEN')) as assess, \
             patch('semantic_pallet_planner.jev_select.execution.commit_physical',side_effect=AssertionError('COMMIT_FORBIDDEN')) as commit, \
             patch.object(balance_network,'linprog',side_effect=AssertionError('LP_FORBIDDEN')) as lp:
            with pytest.raises(JevSelectError):
                run_jev_job(plan,'G00',adapted[0],monitor_snapshot=monitor,admission=a,kernel_receipt=b,
                            root=root/('rejected_'+case),transport=transport,ledger=ledger)
            assert assess.call_count==commit.call_count==lp.call_count==0
            assert not transport.bodies and ledger.statistics()['send_reservations']==0
            assert not (root/('rejected_'+case)).exists()
    finally:
        if restore:restore[0].write_bytes(restore[1])
