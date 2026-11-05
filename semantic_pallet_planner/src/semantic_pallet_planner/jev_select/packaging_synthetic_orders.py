"""Synthetic plan adapter. Execution reuses the common v10 job/episode adapter."""
from pathlib import Path
from .contracts import digest, validate_schema
from .ledger import read,write
from .experiment import source_manifest,file_manifest
from .packaging_runtime import physical_manifest
from .packaging_source_audit import require
from . import packaging_evaluation_orders as base
from .packaging_synthetic_protocol import VERSION,VERSIONS,METHODS,REGISTRY,PURPOSE,load_synthetic_config
from .packaging_synthetic_data import load_dataset,MEMORY_SCOPE

GATE={**base.GATE,'version':'jev_synthetic_gate_v1','first_task':'SYN_COMBO_01',
 'outcomes':['PASS','DEFER_NO_EXPOSURE','STOP_TECHNICAL','CANCELLED'],
 'continue':'only PASS; E and unrelated E each require an actual real-origin nonempty send; no gain test',
 'defer':'stop; remaining30 NOT_RUN; explicit later override is a separate recorded authorization',
 'static_pressure':'do not skip excess demand or unfit items; original per-action physical constraints apply'}


def scope(data,purpose):
    if purpose==PURPOSE:
        require(not data['fixture_only'] and data['dataset_root'],'synthetic_formal_data_required')
        checked=load_dataset(base.REPO/data['dataset_root'],repo=base.REPO)
        require(checked==data,'synthetic_formal_data_changed')
        require(all(r['new_combination_status']=='PASS' for r in data['relations'].values()),'synthetic_overlapping_order')
    elif purpose=='SYNTHETIC_ENGINEERING':
        require(data['fixture_only'] is True and data['dataset_root'] is None and all(t['task_id'].startswith('CONSTRUCTED_') for t in data['tasks']),'synthetic_engineering_fixture_required')
    else:require(False,'synthetic_unknown_purpose')
    require(data['version']=='jev_synthetic_combo_dataset_v1','synthetic_data_version')
    for t in data['tasks']:
        r=data['relations'][t['task_id']]
        require(r['memory_scope_version']==MEMORY_SCOPE,'synthetic_relation_scope')


def jobs_for(data,snaps,purpose):
    jobs=[]
    for t in data['tasks']:
        for method in METHODS:
            mode=REGISTRY[method]['mode'];rm='E' if mode=='E_unrelated_control' else mode
            c=load_synthetic_config(data_identity=data['data_identity'],task_digest=digest(t),method=method,
               relation=data['relations'][t['task_id']],purpose=purpose,snapshot=None if mode=='none' else snaps[rm],
               control=snaps['control'] if mode=='E_unrelated_control' else None,enabled=True)
            jobs.append({'job_id':f'J{len(jobs):04d}','task_id':t['task_id'],'method_id':method,'task_digest':digest(t),'config':c})
    return jobs


def prepare(data,output,*,purpose=PURPOSE):
    scope(data,purpose);snaps=base.snapshots();jobs=jobs_for(data,snaps,purpose)
    limits={j['job_id']:len(next(t for t in data['tasks'] if t['task_id']==j['task_id'])['items']) if REGISTRY[j['method_id']]['remote'] else 0 for j in jobs}
    from .packaging_reanalysis import RULE
    p={'version':VERSIONS['plan'],'execution_version':VERSION,'purpose':purpose,'data':data,
     'task_ids':[t['task_id'] for t in data['tasks']],'method_ids':METHODS,'jobs':jobs,
     'source_manifest':source_manifest(),'dependencies':base.dependencies(),'physical_manifest':physical_manifest(),
     'snapshots':snaps,'request_budget':{'per_job':limits,'global':sum(limits.values())},
     'watchdog':{'max_events':10000,'max_active_wall_s':1800},'gate_rule':GATE,'evaluation_rule':RULE,
     'run_location':base.location(Path(output).resolve().parent/'run'),'model_availability':'UNKNOWN_NOT_PROBED'}
    validate_schema('synthetic_orders_plan_v1',p);out=Path(output);require(not out.exists(),'synthetic_plan_exists')
    write(out/'plan.json',p);write(out/'plan_receipt.json',{'plan_digest':digest(p)})
    write(out/'delivery_manifest.json',file_manifest(out));validate_plan(out);return p


def validate_plan(root):
    root=Path(root);p=read(root/'plan.json');validate_schema('synthetic_orders_plan_v1',p)
    require(read(root/'plan_receipt.json')=={'plan_digest':digest(p)} and read(root/'delivery_manifest.json')==file_manifest(root),'synthetic_plan_bytes')
    require(p['source_manifest']==source_manifest() and p['dependencies']==base.dependencies() and p['physical_manifest']==physical_manifest(),'synthetic_plan_runtime_identity')
    scope(p['data'],p['purpose']);snaps=base.snapshots()
    require(p['snapshots']==snaps and p['gate_rule']==GATE,'synthetic_snapshot_or_gate')
    require(p['jobs']==jobs_for(p['data'],snaps,p['purpose']),'synthetic_job_binding')
    b=base.budget_for_tasks(p['data']['tasks'])
    require(p['request_budget']=={'per_job':b['per_job'],'global':b['shared_batch_max_sends']},'synthetic_plan_budget')
    require(p['method_ids']==METHODS and p['task_ids']==[t['task_id'] for t in p['data']['tasks']],'synthetic_matrix')
    from .packaging_reanalysis import RULE
    require(p['evaluation_rule']==RULE and p['watchdog']=={'max_events':10000,'max_active_wall_s':1800},'synthetic_rules_changed')
    require(p['run_location']==base.location(root.resolve().parent/'run'),'synthetic_run_location')
    return p


def main():
    import argparse
    parser=argparse.ArgumentParser(description='Synthetic static build/plan/verify only. No model or formal run entry.')
    parser.add_argument('command',choices=['freeze','build','validate-data','plan','validate-plan','validate-run'])
    parser.add_argument('--repo',default=str(base.REPO));parser.add_argument('--dataset');parser.add_argument('--output')
    a=parser.parse_args()
    from . import packaging_synthetic_data as data
    if a.command=='freeze':data.freeze(a.repo,a.output)
    elif a.command=='build':data.build(a.repo,a.dataset)
    elif a.command=='validate-data':data.load_dataset(a.dataset,repo=a.repo)
    elif a.command=='plan':prepare(data.load_dataset(a.dataset,repo=a.repo),a.output)
    elif a.command=='validate-plan':validate_plan(a.output)
    else:base.validate_run(a.output)
    print('PASS_STATIC_ONLY_NO_FORMAL_DISPATCH')

if __name__=='__main__':main()
