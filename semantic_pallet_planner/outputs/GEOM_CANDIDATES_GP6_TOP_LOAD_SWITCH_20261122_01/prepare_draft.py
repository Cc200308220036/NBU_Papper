"""Prepare the two-job DRAFT only. No credentials, ledgers, monitor or dispatch."""
from pathlib import Path
import hashlib
import json
import sys
REPO=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(REPO/'semantic_pallet_planner/src'))
from semantic_pallet_planner.jev_select.packaging_geometry_protocol import adapt_task
from semantic_pallet_planner.jev_select.geometry_jev_protocol import prepare_jev_plan,GP6_ORDER
from semantic_pallet_planner.jev_select.contracts import digest
from semantic_pallet_planner.jev_select.candidate_backends import backend_config
from semantic_pallet_planner.jev_select.experiment import source_manifest

OUT=Path(__file__).parent
DATA=REPO/'semantic_pallet_planner/outputs/DATA_JEV_PACKAGING_LOAD_20261102_02'
def read(p):return json.loads(p.read_text())
def save(name,v):(OUT/name).write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n')
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
    manifest=read(DATA/'manifest.json');handoff=read(DATA/'handoff.json');sources=read(DATA/'source_manifest.json');split=read(DATA/'split_manifest.json');delivery=read(DATA/'delivery_manifest.json')
    assert manifest['data_identity']==handoff['manifest']['data_identity']
    assert sources['exposed_training_only'] and sources['independent_new_sources']==0
    assert any(g['source_group_id']=='SG_901bbb22f834c63f' and g['partition']=='train' for g in split['groups'])
    task_id='NEW_00100027_controlled_base';task_path=DATA/'tasks'/f'{task_id}.json'
    assert sha(task_path)==delivery[f'tasks/{task_id}.json']
    adapted=adapt_task(task_path.read_bytes(),origin='EXPOSED_TRAIN',expected_sha256=sha(task_path))
    ledgers='semantic_pallet_planner/outputs/GEOM_CANDIDATES_GP6_TOP_LOAD_DISABLED_LEDGERS_20261122_01'
    run_root='semantic_pallet_planner/outputs/GEOM_CANDIDATES_GP6_TOP_LOAD_DISABLED_RUN_20261122_01'
    kwargs=dict(data_identity=manifest['data_identity'],scope=GP6_ORDER,per_job_max_sends=19,shared_max_sends=38,request_ledger_path=ledgers+'/requests/requests.json',call_ledger_path=ledgers+'/calls/calls.json',switch_protocol=True)
    # New protocol's default remains enabled; old plans need no new field.
    enabled=prepare_jev_plan([adapted],**kwargs)
    assert enabled['packaging_top_load_limit_enabled'] is True
    plan=prepare_jev_plan([adapted],packaging_top_load_limit_enabled=False,**kwargs)
    assert plan['status']=='DRAFT' and len(plan['jobs'])==2
    save('gp6_top_load_disabled_plan_DRAFT.json',plan)
    save('source_identity.json',{'source_identity':digest(source_manifest()),'files':source_manifest()})
    save('run_layout_DRAFT.json',{
        'status':'DRAFT','authorized_for_api_calls':False,'real_calls_this_delivery':0,
        'plan_digest':digest(plan),'run_root':run_root,'request_ledger_path':plan['request_ledger_path'],
        'call_ledger_path':plan['call_ledger_path'],'ledger_initialization':'NOT_RUN',
        'monitor_snapshot_reference':'semantic_pallet_planner/outputs/GEOM_CANDIDATES_GP5_P2_FINAL_RUNTIME_20261120_01/monitor_snapshot.json',
        'monitor_enabled':True,'monitor_algorithm':'pct_exact_pose_network_v3',
        'buffer_capacity':3,'display_order_seed':20261102,'per_object_top_k':16,'joint_candidates_max':48,
        'arrival_order_digest':digest([o['item_id'] for o in adapted['runtime']['items']]),
        'jobs':[{**job,'packaging_top_load_limit_enabled':False,'generator_config':backend_config(job['backend']),
            'send_limit':19,'status':'NOT_RUN'} for job in plan['jobs']],
        'shared_send_limit':38,'primary_metrics':['placed_items','fixed_container_utilization','PREDICTED_STATIC_INSTABILITY'],
        'additional_metrics':['max_height_mm','envelope_utilization'],'packaging_top_load_compliance':'NOT_APPLICABLE',
        'data_checks':{n:sha(DATA/n) for n in ('manifest.json','handoff.json','source_manifest.json','split_manifest.json',f'tasks/{task_id}.json')},
        'limits':'Exposed train source; feasibility UNKNOWN. Draft ceilings are not dispatch permission; new admission and bridge required.'})
    print(json.dumps({'status':'DRAFT','jobs':2,'plan_digest':digest(plan),'real_calls':0}))
if __name__=='__main__':main()
