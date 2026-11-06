"""Frozen exact-pose supplement: consume only the parent's NOT_RUN slots.

Reuses the common _run_plan and run_episode, including durable send/monitor/
commit transitions. Never resumes or rewrites a parent plan or run.
"""
from pathlib import Path
from .contracts import digest,validate_schema
from .ledger import read,write,exclusive
from .experiment import source_manifest,file_manifest
from .packaging_source_audit import require,sha
from .packaging_versions import EXACT_VERSION,EXACT_PLAN,EXACT_RUN,REMAINDER_PLAN
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
    root=Path(root);p=read(root/'plan.json')
    if p['version']==REMAINDER_PLAN:return validate_remaining(root)
    validate_schema('synthetic_supplement_plan_v2',p)
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
        if p.get('version')==REMAINDER_PLAN:
            register_remaining(p,account)
        else:
            register_supplement(p,account)
    return base._run_plan(p,plan_root,root,transport_factory=constructed_factory or native_transport,
        resume=resume,execution_mode='CONSTRUCTED_SUPPLEMENTAL_ONLY' if fixture else 'JEV_SUPPLEMENTAL_TRANSPORT')

def register_supplement(p,account):
    with exclusive(account):
        owner={'parent_run_manifest':p['parent']['run_manifest_sha256'],'plan_digest':digest(p),'run':p['run_location']}
        if (account/'owner.json').exists():require(read(account/'owner.json')==owner,'exact_supplement_already_registered')
        else:write(account/'owner.json',owner)

def account_root():
    return base.REPO/'semantic_pallet_planner/outputs/JEV_JN4_EXACT_SUPPLEMENT_ACCOUNTING_V1'


def archived_plan(root,schema):
    """Read historical identity without demanding today's source identity."""
    root=Path(root);p=read(root/'plan.json');validate_schema(schema,p)
    require(read(root/'delivery_manifest.json')==file_manifest(root)
            and read(root/'plan_receipt.json')=={'plan_digest':digest(p)},'remaining_parent_plan_bytes')
    return p


def archived_run(root,p):
    # Check only the binding/status/accounting records, never replay trajectories
    # or re-audit every historical candidate/request artifact.
    root=Path(root);manifest=read(root/'delivery_manifest.json')
    names=['run_receipt.json','summary.json','request_ledger/requests.json']
    names += [f"jobs/{j['job_id']}/status.json" for j in p['jobs']]
    for name in names:
        require(manifest.get(name)==sha(root/name),'remaining_parent_record_bytes')
    require(read(root/'run_receipt.json')['plan_digest']==digest(p),'remaining_parent_run_binding')
    summary=read(root/'summary.json')
    require(summary==base.collect(root,p),'remaining_parent_summary')
    require(all(j['state'] in ('FINISHED','NOT_RUN') for j in summary['job_ledger']),
            'remaining_parent_active_job')
    return summary,base.saved_requests(root,p),manifest


def capture_stopped(plan_root,run_root):
    """One continuation level only: stopped v3 supplement -> never-started jobs."""
    plan_root=Path(plan_root);run_root=Path(run_root)
    require((run_root/'.writer.lock').exists(),'remaining_parent_not_closed')
    with exclusive(run_root):
        old=archived_plan(plan_root,'synthetic_supplement_plan_v2')
        require(base.resolve(old['run_location']).resolve()==run_root.resolve(),'remaining_parent_location')
        summary,rows,manifest=archived_run(run_root,old)
        require(summary['status']=='ERROR' and any(j['category'] in base.STOP for j in summary['job_ledger']),
                'remaining_parent_not_technical_stop')
        ids=[j['job_id'] for j in summary['job_ledger'] if j['state']=='NOT_RUN']
        require(bool(ids),'remaining_empty_scope')
        for jid in ids:
            directory=run_root/'jobs'/jid
            require(not any(r['job_id']==jid for r in rows)
                    and {f.relative_to(directory).as_posix() for f in directory.rglob('*') if f.is_file()}
                    =={'status.json','task.snapshot.json','config.snapshot.json'},'remaining_job_already_started')
            j=next(j for j in old['jobs'] if j['job_id']==jid)
            for name in ('task.snapshot.json','config.snapshot.json'):
                require(manifest.get(f'jobs/{jid}/{name}')==sha(directory/name),'remaining_snapshot_bytes')
            require(read(directory/'config.snapshot.json')==j['config']
                    and digest(read(directory/'task.snapshot.json'))==j['task_digest'],'remaining_snapshot_changed')
        unknown=[r for r in rows if r['state']=='UNKNOWN_SEND']
        require(bool(unknown) and all(r['state'] not in ('INTENT','SENDING') for r in rows),
                'remaining_parent_unsettled_send')
        for r in unknown:
            st=next(j for j in summary['job_ledger'] if j['job_id']==r['job_id'])
            cp_path=run_root/'jobs'/r['job_id']/'checkpoint.json';cp=read(cp_path)
            require(st['state']=='FINISHED' and st['category'] in base.STOP
                    and manifest.get(f"jobs/{r['job_id']}/checkpoint.json")==sha(cp_path)
                    and cp['phase']=='TERMINATED' and cp['pending_event'] is None
                    and cp['job_id']==r['job_id'] and cp['reason']=='UNKNOWN_IN_FLIGHT'
                    and cp['events'][-1]['event']=='STOP'
                    and cp['events'][-1]['decision_id']==r['decision_id']
                    and cp['events'][-1]['before']==cp['events'][-1]['after'], 'remaining_unknown_not_closed')
        root_ref=old['parent'];root_plan=base.resolve(root_ref['plan']);root_run=base.resolve(root_ref['run'])
        original=archived_plan(root_plan,'synthetic_orders_plan_v1')
        root_summary,root_rows,_=archived_run(root_run,original)
        require(sha(root_plan/'plan.json')==root_ref['plan_sha256']
                and sha(root_run/'delivery_manifest.json')==root_ref['run_manifest_sha256']
                and sha(root_run/'summary.json')==root_ref['summary_sha256']
                and sha(root_run/'first_gate.json')==root_ref['first_gate_sha256']
                and read(root_run/'first_gate.json')['status']=='PASS','remaining_root_binding')
        require(original['data']==old['data'] and original['snapshots']==old['snapshots']==base.snapshots()
                and old['evaluation_rule']==original['evaluation_rule']
                and old['watchdog']==original['watchdog'],'remaining_frozen_inputs')
        original_jobs={j['job_id']:j for j in original['jobs']}
        require([j['job_id'] for j in old['jobs']]==root_ref['not_run_job_ids'], 'remaining_parent_scope')
        for j in old['jobs']:
            prior=original_jobs[j['job_id']]
            require(all(j[k]==prior[k] for k in ('job_id','task_id','method_id','task_digest'))
                    and old['request_budget']['per_job'][j['job_id']]==original['request_budget']['per_job'][j['job_id']],
                    'remaining_job_inheritance')
        root_stats=root_summary['request_statistics'];stats=summary['request_statistics']
        cap=original['request_budget']['global'];used=root_stats['send_reservations']+stats['send_reservations']
        require(root_ref['original_global_cap']==cap and root_ref['consumed_reservations']==root_stats['send_reservations']
                and root_ref['remaining_cap']==cap-root_stats['send_reservations']==old['request_budget']['global'],
                'remaining_budget_lineage')
        known=root_stats['known_real_model_calls']+stats['known_real_model_calls']
        uncertain=root_stats['unknown_real_send_count']+stats['unknown_real_send_count']
        owner_path=account_root()/'owner.json'
        expected_owner={'parent_run_manifest':root_ref['run_manifest_sha256'],'plan_digest':digest(old),
                        'run':old['run_location']}
        if not old['data']['fixture_only']:
            require(read(owner_path)==expected_owner,'remaining_original_owner')
            require(ids==[f'J{i:04d}' for i in range(12,36)] and cap==656
                    and root_stats['send_reservations']==64 and stats['send_reservations']==57
                    and known==120 and uncertain==1 and len(unknown)==1
                    and (unknown[0]['attempt_id'],unknown[0]['decision_id'])==('A000057','J0011_D0006'),
                    'remaining_authorized24_only')
            # Consume the frozen runtime dataset, not raw data/prototype regeneration.
            data_root=base.resolve(old['data']['dataset_root']);dataset=read(data_root/'dataset.json')
            from .packaging_runtime import runtime_task
            require(dataset['data_identity']==digest({k:v for k,v in dataset.items() if k!='data_identity'})
                    and all(dataset[k]==old['data'][k] for k in ('version','data_identity','fixture_only','relations'))
                    and [runtime_task(t) for t in dataset['tasks']]==old['data']['tasks'],
                    'remaining_dataset_changed')
        return old,{'plan':base.location(plan_root),'run':base.location(run_root),
            'plan_sha256':sha(plan_root/'plan.json'),'run_manifest_sha256':sha(run_root/'delivery_manifest.json'),
            'summary_sha256':sha(run_root/'summary.json'),'not_run_job_ids':ids,
            'owner_sha256':None if old['data']['fixture_only'] else sha(owner_path),
            'owner':expected_owner,'unknown_requests':[{'attempt_id':r['attempt_id'],'job_id':r['job_id'],
                'decision_id':r['decision_id'],'request_digest':digest(r)} for r in unknown],
            'accounting':{'original_global_cap':cap,'root_reservations':root_stats['send_reservations'],
                'supplement_reservations':stats['send_reservations'],'consumed_reservations':used,
                'remaining_cap':cap-used,'known_real_model_calls':known,'unknown_real_send_count':uncertain,
                'actual_model_api_calls':'UNKNOWN','real_model_call_interval':{'minimum':known,'maximum':known+uncertain}}}


def derive_remaining(parent_plan,parent_run,output):
    old,remainder=capture_stopped(parent_plan,parent_run)
    jobs=jobs_for(old,remainder)
    for j in jobs:
        prior=next(x for x in old['jobs'] if x['job_id']==j['job_id'])
        require(j['config']['stability_monitor']==prior['config']['stability_monitor']
                and {k:v for k,v in j['config']['runtime_identity'].items() if k!='strategy_identity'}
                =={k:v for k,v in prior['config']['runtime_identity'].items() if k!='strategy_identity'},
                'remaining_monitor_or_physical_changed')
    limits={j['job_id']:old['request_budget']['per_job'][j['job_id']] for j in jobs}
    require(sum(limits.values())<=remainder['accounting']['remaining_cap'],'remaining_budget')
    if not old['data']['fixture_only']:
        require(len(jobs)==24 and sum(REGISTRY[j['method_id']]['remote'] for j in jobs)==16
                and sum(limits.values())==512,'remaining_limits')
    return {**old,'version':REMAINDER_PLAN,'remainder':remainder,'jobs':jobs,
        'source_manifest':source_manifest(),'dependencies':base.dependencies(),'physical_manifest':physical_manifest(),
        'request_budget':{'per_job':limits,'global':remainder['accounting']['remaining_cap']},
        'run_location':base.location(Path(output).resolve().parent/'run'),'model_availability':'UNKNOWN_NOT_PROBED'}


def prepare_remaining(parent_plan,parent_run,output):
    out=Path(output);require(not out.exists() and not (out.parent/'run').exists(),'remaining_output_exists')
    p=derive_remaining(parent_plan,parent_run,out);validate_schema('synthetic_remainder_plan_v3',p)
    write(out/'plan.json',p);write(out/'plan_receipt.json',{'plan_digest':digest(p)})
    write(out/'delivery_manifest.json',file_manifest(out));validate_remaining(out)
    return p


def validate_remaining(root):
    root=Path(root);p=read(root/'plan.json');validate_schema('synthetic_remainder_plan_v3',p)
    require(read(root/'plan_receipt.json')=={'plan_digest':digest(p)}
            and read(root/'delivery_manifest.json')==file_manifest(root),'remaining_plan_bytes')
    ref=p['remainder']
    require(p==derive_remaining(base.resolve(ref['plan']),base.resolve(ref['run']),root),'remaining_frozen_binding')
    return p


def register_remaining(p,account):
    """Append under the original account lock; never overwrite original owner."""
    with exclusive(account):
        ref=p['remainder'];require(sha(account/'owner.json')==ref['owner_sha256']
                and read(account/'owner.json')==ref['owner'],'remaining_original_owner')
        owner={'original_owner_sha256':ref['owner_sha256'],'parent_run_manifest':ref['run_manifest_sha256'],
            'job_ids':ref['not_run_job_ids'],'plan_digest':digest(p),'run':p['run_location']}
        path=account/'remaining24_owner.json'
        if path.exists():require(read(path)==owner,'remaining_already_registered')
        else:write(path,owner)


def main():
    import argparse
    from .contracts import canonical
    parser=argparse.ArgumentParser();parser.add_argument('command',choices=['prepare','prepare-remaining','validate','run','resume','validate-run'])
    parser.add_argument('--parent-plan');parser.add_argument('--parent-run');parser.add_argument('--plan');parser.add_argument('--output')
    a=parser.parse_args()
    if a.command=='prepare':result=prepare(a.parent_plan,a.parent_run,a.output);result={'status':'FROZEN','jobs':len(result['jobs']),'budget':result['request_budget']}
    elif a.command=='prepare-remaining':
        p=prepare_remaining(a.parent_plan,a.parent_run,a.output);result={'status':'FROZEN','jobs':len(p['jobs']),'budget':p['request_budget']}
    elif a.command=='validate':validate_plan(a.plan);result={'status':'PASS_STATIC_ONLY'}
    elif a.command=='validate-run':result=base.validate_run(a.output)
    else:result=run(a.plan,resume=a.command=='resume')
    print(canonical(result))
    if result.get('status')=='ERROR':raise SystemExit(1)

if __name__=='__main__':main()
