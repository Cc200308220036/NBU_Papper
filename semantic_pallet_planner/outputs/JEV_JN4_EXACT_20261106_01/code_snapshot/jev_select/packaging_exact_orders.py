"""Frozen exact-pose supplement: consume only the parent's NOT_RUN slots.

Reuses the common _run_plan and run_episode, including durable send/monitor/
commit transitions. Never resumes or rewrites a parent plan or run.
"""
from pathlib import Path
from .contracts import digest,validate_schema
from .ledger import read,write,exclusive
from .experiment import source_manifest,file_manifest
from .packaging_source_audit import require,sha
from .packaging_versions import EXACT_VERSION,EXACT_PLAN,EXACT_RUN
from .packaging_exact_protocol import load_exact_config
from .packaging_synthetic_orders import scope,native_transport,ConstructedTransport
from .packaging_synthetic_protocol import PURPOSE,request_accounting
from .packaging_evaluation_protocol import METHODS,REGISTRY
from .packaging_runtime import physical_manifest
from . import packaging_evaluation_orders as base

GATE={'version':'jev_exact_supplement_scope_v1',
 'scope':'all and only parent NOT_RUN jobs, in original order; explicit user authorization',
 'old_gate':'archived PASS is historical evidence, never relabelled as a v3 first-block gate',
 'stop':'technical error, unknown send, watchdog, cancellation, identity or unregistered monitor scope',
 'monitor':'exact-pose v3 independently validated before freeze; original registered range reasons retained'}

def capture_parent(plan_root,run_root):
    plan_root=Path(plan_root);run_root=Path(run_root);p=read(plan_root/'plan.json')
    validate_schema('synthetic_orders_plan_v1',p)
    require(read(plan_root/'delivery_manifest.json')==file_manifest(plan_root)
        and read(plan_root/'plan_receipt.json')=={'plan_digest':digest(p)},'exact_parent_plan_bytes')
    require(read(run_root/'delivery_manifest.json')==file_manifest(run_root),'exact_parent_run_bytes')
    require(read(run_root/'run_receipt.json')['plan_digest']==digest(p),'exact_parent_run_binding')
    require(read(run_root/'first_gate.json')['status']=='PASS','exact_parent_first_gate')
    require(p['snapshots']==base.snapshots(),'exact_parent_memory_snapshots')
    rows=base.saved_requests(run_root,p);stats=request_accounting(rows)
    require(stats['unknown_sends']==0,'exact_parent_unknown_send')
    statuses={j['job_id']:read(run_root/'jobs'/j['job_id']/'status.json') for j in p['jobs']}
    require(all(s['state'] in ('NOT_RUN','FINISHED') for s in statuses.values()),'exact_parent_active_job')
    ids=[j['job_id'] for j in p['jobs'] if statuses[j['job_id']]['state']=='NOT_RUN']
    require(bool(ids) and all(not any(r['job_id']==jid for r in rows) for jid in ids),'exact_only_never_run_slots')
    if not p['data']['fixture_only']:
        require(ids==[f'J{i:04d}' for i in range(7,36)] and stats['send_reservations']==64
            and p['request_budget']['global']==656,'exact_authorized29_only')
        require(read(run_root/'technical_failure.json')=={'reason':'UNREGISTERED_MONITOR_SCOPE'},'exact_parent_stop_changed')
    parent={'plan':base.location(plan_root),'run':base.location(run_root),'plan_sha256':sha(plan_root/'plan.json'),
        'run_manifest_sha256':sha(run_root/'delivery_manifest.json'),'first_gate_sha256':sha(run_root/'first_gate.json'),
        'summary_sha256':sha(run_root/'summary.json'),'not_run_job_ids':ids,
        'original_global_cap':p['request_budget']['global'],'consumed_reservations':stats['send_reservations'],
        'remaining_cap':p['request_budget']['global']-stats['send_reservations']}
    return p,parent

def jobs_for(old,parent):
    jobs=[];snaps=old['snapshots']
    for j in old['jobs']:
        if j['job_id'] not in parent['not_run_job_ids']:continue
        mode=REGISTRY[j['method_id']]['mode'];rm='E' if mode=='E_unrelated_control' else mode
        c=load_exact_config(data_identity=old['data']['data_identity'],task_digest=j['task_digest'],
            method=j['method_id'],relation=old['data']['relations'][j['task_id']],purpose=old['purpose'],
            snapshot=None if mode=='none' else snaps[rm],control=snaps['control'] if mode=='E_unrelated_control' else None,enabled=True)
        # All strategy inputs other than explicit protocol/monitor/source identities stay frozen.
        require({k:v for k,v in c.items() if k not in ('version','runtime_identity','stability_monitor')}==
                {k:v for k,v in j['config'].items() if k not in ('version','runtime_identity','stability_monitor')},'exact_parent_strategy_changed')
        jobs.append({**j,'config':c})
    return jobs

def derive(plan_root,parent_run,output):
    old,parent=capture_parent(plan_root,parent_run);scope(old['data'],old['purpose'])
    jobs=jobs_for(old,parent)
    limits={j['job_id']:old['request_budget']['per_job'][j['job_id']] for j in jobs}
    require(sum(limits.values())<=parent['remaining_cap'],'exact_budget_inheritance')
    return {**old,'version':EXACT_PLAN,'execution_version':EXACT_VERSION,'parent':parent,'jobs':jobs,
        'source_manifest':source_manifest(),'dependencies':base.dependencies(),'physical_manifest':physical_manifest(),
        'request_budget':{'per_job':limits,'global':parent['remaining_cap']},'gate_rule':GATE,
        'run_location':base.location(Path(output).resolve().parent/'run'),
        'model_availability':'UNKNOWN_NOT_PROBED'}

def prepare(parent_plan,parent_run,output):
    out=Path(output);require(not out.exists(),'exact_plan_exists')
    p=derive(parent_plan,parent_run,out);validate_schema('synthetic_supplement_plan_v2',p)
    write(out/'plan.json',p);write(out/'plan_receipt.json',{'plan_digest':digest(p)})
    write(out/'delivery_manifest.json',file_manifest(out));validate_plan(out)
    return p

def validate_plan(root):
    root=Path(root);p=read(root/'plan.json');validate_schema('synthetic_supplement_plan_v2',p)
    require(read(root/'plan_receipt.json')=={'plan_digest':digest(p)} and read(root/'delivery_manifest.json')==file_manifest(root),'exact_plan_bytes')
    require(p['source_manifest']==source_manifest() and p['dependencies']==base.dependencies()
            and p['physical_manifest']==physical_manifest(),'exact_runtime_identity')
    expected=derive(base.resolve(p['parent']['plan']),base.resolve(p['parent']['run']),root)
    require(p==expected,'exact_frozen_binding')
    return p

def run(plan_root,*,resume=False,constructed_factory=None):
    p=validate_plan(plan_root);fixture=p['data']['fixture_only']
    require(fixture==(constructed_factory is not None),'exact_transport_scope')
    root=base.resolve(p['run_location'])
    if not fixture:
        # A stopped supplemental matrix cannot be duplicated under a new run path.
        account=base.REPO/'semantic_pallet_planner/outputs/JEV_JN4_EXACT_SUPPLEMENT_ACCOUNTING_V1'
        account.mkdir(exist_ok=True)
        with exclusive(account):
            owner={'parent_run_manifest':p['parent']['run_manifest_sha256'],'plan_digest':digest(p),'run':p['run_location']}
            if (account/'owner.json').exists():require(read(account/'owner.json')==owner,'exact_supplement_already_registered')
            else:write(account/'owner.json',owner)
    return base._run_plan(p,plan_root,root,transport_factory=constructed_factory or native_transport,
        resume=resume,execution_mode='CONSTRUCTED_SUPPLEMENTAL_ONLY' if fixture else 'JEV_SUPPLEMENTAL_TRANSPORT')

def main():
    import argparse
    from .contracts import canonical
    parser=argparse.ArgumentParser();parser.add_argument('command',choices=['prepare','validate','run','resume','validate-run'])
    parser.add_argument('--parent-plan');parser.add_argument('--parent-run');parser.add_argument('--plan');parser.add_argument('--output')
    a=parser.parse_args()
    if a.command=='prepare':result=prepare(a.parent_plan,a.parent_run,a.output);result={'status':'FROZEN','jobs':len(result['jobs']),'budget':result['request_budget']}
    elif a.command=='validate':validate_plan(a.plan);result={'status':'PASS_STATIC_ONLY'}
    elif a.command=='validate-run':result=base.validate_run(a.output)
    else:result=run(a.plan,resume=a.command=='resume')
    print(canonical(result))
    if result.get('status')=='ERROR':raise SystemExit(1)

if __name__=='__main__':main()
