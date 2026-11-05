"""Bounded JN1-A preregistration and one-decision execution via run_episode.

No full-order entry point: preparation stops at the first multi-candidate state;
execution stops immediately after that saved decision. CLI send is explicit.
"""
from __future__ import annotations
import argparse
import base64
import copy
import hashlib
from pathlib import Path
import shutil

from .contracts import digest, JevSelectError
from .ledger import read, write, exclusive
from .packaging_remote import (VERSION, VERSIONS, REGISTRY, load_remote_config,
                               RequestLedger, decision_record, preflight_remote)
from .packaging_protocol import selector_factory
from .packaging_runtime import load_runtime_dataset, physical_manifest
from .experiment import source_manifest
from .episode import run_episode
from .packaging_experiment import new_output, validate_saved_checkpoint

REPO=Path(__file__).resolve().parents[4]
PARENT=Path('semantic_pallet_planner/outputs/JEV_JN0_20261103_02')

class StopAtBoundary(BaseException):
    pass


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def parent_check():
    parent=REPO/PARENT
    manifest=read(parent/'delivery_manifest.json')
    changed=[n for n,h in manifest['files_sha256'].items() if not (parent/n).is_file() or sha(parent/n)!=h]
    if changed:raise JevSelectError('parent_artifact_changed',str(changed[:3]))
    r=read(parent/'full_order_readiness.json');h=read(parent/'handoff.json');review=read(parent/'monitor_scope_review.json')
    if not (r['JN1_admitted'] and h['JN1_admitted'] and review['JN1_admitted'] and r['actual_cumulative_starts']==9):
        raise JevSelectError('parent_not_admitted')
    plan=read(parent/'plan/plan.json')
    if plan['physical_manifest']!=physical_manifest():raise JevSelectError('parent_physical_changed')
    return {'parent':str(PARENT),'parent_receipt_digest':digest(h), 'parent_handoff_sha256':sha(parent/'handoff.json'),
            'manifest_sha256':sha(parent/'delivery_manifest.json'),'files_verified':len(manifest['files_sha256']),
            'readiness_sha256':sha(parent/'full_order_readiness.json'), 'monitor_scope_review_sha256':sha(parent/'monitor_scope_review.json'),
            'JN0_actual_starts':9,'JN0_reruns':0,'JN1_admitted':True,
            'scope':'unchanged conservative POSE_HEIGHT_MISMATCH stop boundary',
            'spec_difference':'repository main specification has 6.1-6.3; A01-A07 follow explicit goal objective'},plan


def prior_requests(output):
    rows=[]
    for path in sorted((REPO/'semantic_pallet_planner/outputs').glob('JEV_JN1_*/**/requests.json')):
        if path.is_relative_to(output):continue
        d=read(path)
        for r in d.get('requests',[]):
            if r.get('origin')=='jev' and r.get('send_started'):
                rows.append({'path':str(path.relative_to(REPO)),'decision_id':r['decision_id'],'state':r['state']})
    return rows


def prepare(output):
    root=new_output(output)
    baseline,plan=parent_check()
    previous=prior_requests(root)
    if previous:raise JevSelectError('JN1_A_cumulative_budget_already_used')
    # Fixed before any trajectory/monitor review: first task in admitted parent's frozen order.
    data=load_runtime_dataset(REPO/plan['dataset'])
    if data['data_identity']!=plan['data_identity']:raise JevSelectError('parent_data_changed')
    task=next(t for t in data['tasks'] if t['task_id']==plan['task_ids'][0])
    config=load_remote_config(data_identity=data['data_identity'],task_digest=digest(task),enabled=True)
    local=load_remote_config(data_identity=data['data_identity'],task_digest=digest(task),method='local_geometry_test_double',enabled=True)
    local_selector=selector_factory(local['selector'],execution_version=VERSION,config=local)
    ready=[];checkpoints=[]
    def cp(c):checkpoints.append(c)
    def hook(phase,event):
        if phase=='decision_ready' and event['route']=='CHOICE_REQUIRED':
            ready.append(copy.deepcopy(event));raise StopAtBoundary()
    try:
        run_episode(task,local_selector,local,job_id='A_SMOKE',method=local['selector'],
                    on_checkpoint=cp,hook=hook,event_limit=100)
    except StopAtBoundary:pass
    if not ready:raise JevSelectError('no_multi_candidate_state_within_fixed_prefix_bound')
    prefix=copy.deepcopy(checkpoints[-1])
    # Rebind the saved local prefix to the independently frozen new selector config.
    # For this protocol the expected earliest choice follows arrivals only; avoid
    # relabelling any local selected/committed decision as Jev.
    if any(e.get('selection') for e in prefix['events']):
        raise JevSelectError('local_selected_prefix_requires_separate_handoff')
    prefix.update(config_digest=digest(config),method='jev_no_memory',runtime_identity=config['runtime_identity'])
    from .stability.monitor import seal_checkpoint
    seal_checkpoint(prefix)
    from .episode import decision_inputs
    req,policy,bundle,ctx=decision_inputs(prefix['state'],task,config,'A_SMOKE','A_SMOKE_D0000')
    validate_saved_checkpoint(prefix,task,config,'A_SMOKE')
    write(root/'baseline_verification.json',baseline)
    write(root/'prior_request_audit.json',{'existing_stage_sends':previous,'remaining_send_slots':1})
    write(root/'task.snapshot.json',task);write(root/'config.snapshot.json',config)
    write(root/'prefix/local_config.json',local);write(root/'prefix/local_checkpoint.json',checkpoints[-1])
    write(root/'prefix/checkpoint.json',prefix)
    write(root/'frozen/observation.json',req);write(root/'frozen/candidates.json',bundle.data)
    write(root/'frozen/context.json',ctx.data);write(root/'frozen/request.json',ctx.data['request_body'])
    sources=source_manifest();write(root/'source_manifest.json',sources)
    for n in sources:
        target=root/'code_snapshot'/n;target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(Path(__file__).resolve().parent.parent/n,target)
    from .stability.runtime import environment
    write(root/'environment.json',environment())
    prereg={'version':VERSIONS['plan'],'stage':'JN1-A','job_id':'A_SMOKE','task_id':task['task_id'],
            'source_group':task['source_group_id'],'data_identity':data['data_identity'],
            'parent_receipt_digest':baseline['parent_receipt_digest'],
            'selection_rule':'first task in parent frozen task_ids; earliest CHOICE_REQUIRED; max 100 prefix events; no monitor preassessment',
            'prefix_origin':'LOCAL_ARRIVAL_PREFIX_NOT_JEV; zero selected prefix decisions',
            'max_real_sends':1,'retries':0,'complete_order_runs':0,
            'stop':'after one decision commit/legal stop or request failure/unknown; no second model decision',
            'model':config['model'],'method_registry':REGISTRY,'versions':VERSIONS,
            'source_manifest_digest':digest(sources),'config_digest':digest(config),
            'task_digest':digest(task),'state_digest':digest(prefix['state']),
            'candidate_pool_digest':digest(bundle.data),'mapping_digest':digest(ctx.data['display_mapping']),
            'context_digest':digest(ctx.data),'request_digest':digest(ctx.data['request_body']),
            'monitor_identity':config['runtime_identity']['monitor_identity'],
            'credential_reference':{'loader':'transport.credential','file':'typesafe_api_key.md','persist_auth':False},
            'source_manifest_data_sha256':sha(REPO/plan['dataset']/'source_manifest.json')}
    prereg['record_digest']=digest(prereg);write(root/'preregistration.json',prereg)
    return {'status':'PREPARED','output':str(root.relative_to(REPO)), 'candidate_count':len(ctx.data['criteria']), 'task_id':task['task_id']}


def execute(output, *, transport=None, api_key_file=None):
    root=Path(output).resolve();prereg=read(root/'preregistration.json');config=read(root/'config.snapshot.json');task=read(root/'task.snapshot.json')
    if prereg['record_digest']!=digest({k:v for k,v in prereg.items() if k!='record_digest'}):raise JevSelectError('preregistration_changed')
    if source_manifest()!=read(root/'source_manifest.json') or digest(source_manifest())!=prereg['source_manifest_digest']:
        raise JevSelectError('smoke_source_changed')
    if digest(config)!=prereg['config_digest'] or digest(task)!=prereg['task_digest']:raise JevSelectError('smoke_frozen_input_changed')
    if parent_check()[0]!=read(root/'baseline_verification.json'):raise JevSelectError('smoke_parent_changed')
    preflight_remote(config)
    # Serialize real stage sends across output roots, and inspect cumulative evidence.
    with exclusive(REPO/'semantic_pallet_planner/outputs'):
        if prior_requests(root):raise JevSelectError('JN1_A_cumulative_budget_already_used')
        ledger=RequestLedger(root/'request_ledger',max_sends=1)
        if transport is None:
            from .transport import JevTransport
            transport=JevTransport(config,api_key_file=api_key_file)
        selected=selector_factory('jev_no_memory',execution_version=VERSION,config=config,transport=transport,ledger=ledger,job_id=prereg['job_id'])
        cp=read(root/'checkpoint.json') if (root/'checkpoint.json').exists() else read(root/'prefix/checkpoint.json')
        def checkpoint(value):
            write(root/'checkpoint.json',value)
            if value['pending_event'] is not None:write(root/'stages'/f"{value['phase']}.json",value)
        def hook(phase,event):
            if phase=='decision_ready':
                if digest(event['context'])!=prereg['context_digest'] or digest(event['before'])!=prereg['state_digest'] or digest(event['bundle'])!=prereg['candidate_pool_digest']:
                    raise JevSelectError('smoke_decision_changed')
                write(root/'request.json',event['context']['request_body'])
            if phase=='after_checkpoint' and any(e.get('selection') is not None for e in event['events']):
                raise StopAtBoundary()
        # Completed invocation is read-only; no regenerated candidate or second decision.
        if not any(e.get('selection') is not None for e in cp['events']):
            try:run_episode(task,selected,config,job_id=prereg['job_id'],method='jev_no_memory',
                            resume=cp,on_checkpoint=checkpoint,hook=hook,event_limit=len(cp['events'])+1)
            except StopAtBoundary:pass
            cp=read(root/'checkpoint.json')
        validate_saved_checkpoint(cp,task,config,prereg['job_id'])
        event=next(e for e in cp['events'] if e.get('selection') is not None)
        write(root/'decision_record.json',decision_record(event));write(root/'event.json',event)
        write(root/'selection.json',event['selection']);write(root/'monitor.json',event['monitor'])
        write(root/'execution.json',{'action':event['action'],'proposed_action':event['proposed_action'],
              'event':event['event'],'reason':event['reason'],'before':event['before'],'after':event['after']})
        for r in ledger.data['requests']:
            if r['transport'] is not None:
                (root/'response.raw.json').write_bytes(base64.b64decode(r['transport']['raw_body_b64']))
                write(root/'transport.json',r['transport'])
        stats=ledger.statistics();write(root/'request_statistics.json',stats)
        from .packaging_runtime import summary
        write(root/'metrics.json',{'scope':'one decision only; not a full-order outcome',
              'loading':summary(task,config,'jev_no_memory',cp['state'],cp['events'],cp['reason'] or 'JN1_A_SINGLE_DECISION_BOUNDARY'),
              'request_statistics':stats})
        return {'status':'CLOSED','selection_status':event['selection']['status'],
                'monitor_status':event['monitor']['status'] if event['monitor'] else 'NOT_RUN',
                'execution':event['event'],'request_statistics':stats}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=('prepare','send','inspect'))
    parser.add_argument('--output',required=True);parser.add_argument('--api-key-file')
    args=parser.parse_args()
    if args.action=='prepare':answer=prepare(args.output)
    elif args.action=='send':answer=execute(args.output,api_key_file=args.api_key_file)
    else:answer=read(Path(args.output)/'request_statistics.json')
    import json
    print(json.dumps(answer,ensure_ascii=False))

if __name__=='__main__':main()
