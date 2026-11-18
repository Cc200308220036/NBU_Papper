"""JN3-A frozen one-decision workflow. Prepare is offline; run is explicitly bounded."""
from __future__ import annotations
import argparse
import copy
from pathlib import Path
import shutil
from .contracts import digest,canonical,JevSelectError,DecisionContext,CandidateBundle
from .ledger import read,write,exclusive
from .experiment import source_manifest
from .packaging_experience import (build_snapshot,validate_snapshot,validate_evidence,retrieve,public_query,
    MemoryView,MemorySnapshotReceipt,VERSION,METHOD,RULE,LIMITATIONS,require,sha)
from .packaging_memory_protocol import load_memory_config,MemoryRequestLedger,memory_selector_factory,VERSIONS

REPO=Path(__file__).resolve().parents[4]
PARENT=REPO/'semantic_pallet_planner/outputs/JEV_JN2_20261104_03'


def prior_requests(output):
    rows=[]
    for f in (REPO/'semantic_pallet_planner/outputs').glob('JEV_JN3_*/request_ledger/requests.json'):
        d=read(f)
        for r in d['requests']:
            rows.append({'path':str(f.relative_to(REPO)),'attempt_id':r['attempt_id'],'send_started':r['send_started'],'state':r['state']})
    return rows


def prepare(output):
    from .packaging_runtime import load_runtime_dataset,build_context
    from .episode import decision_inputs
    from .selector import bind_decision
    from semantic_pallet_planner.o4.buffer.buffer_state import initial,receive
    root=Path(output);root.mkdir(parents=True,exist_ok=True)
    require(not (root/'preregistration.json').exists(),'trajectory_already_registered')
    prior=prior_requests(root);require(not prior,'trajectory_previous_attempt_exists')
    parent_plan=read(REPO/'semantic_pallet_planner/outputs/JEV_JN1_20261103_03/plan/plan.json')
    j=next(j for j in parent_plan['jobs'] if j['method_id']=='jev_no_memory')
    dataset=load_runtime_dataset(REPO/parent_plan['dataset']);task=next(t for t in dataset['tasks'] if t['task_id']==j['task_id'])
    require(digest(task)==j['task_digest'],'trajectory_parent_task_changed')
    pre={'version':'JN3-A_query_preregistration_v1','selection_rule':'first real-Jev job in parent JN1-B frozen order; earliest decision after initial buffer fill; no outcome-based search',
         'state_preparation':'new deterministic receive-only prefix; zero model/commit/PCT; not historical Jev prefix or whole-order replay',
         'task_id':j['task_id'],'source_group':j['source_group_id'],'excluded_source_groups':[j['source_group_id']],
         'isolation':'exclude entire source group including same fork, variants and equivalent copies; source never a score feature',
         'max_Jev_sends_A':1,'JN3_B_sends':0,'JN3_C_sends':0,'prior_requests':prior,
         'stop':'one decision closed loop or first failure/unknown; no retry or replacement query',
         'retrieval_rule':RULE,'parent_plan_digest':digest(parent_plan),'limitations':LIMITATIONS}
    write(root/'query_preregistration.json',pre)  # before inspecting the prepared query or its hits
    snapshot=build_snapshot(REPO,PARENT);s=snapshot.data
    require(not any(c['fixture_only'] for c in s['cases']),'trajectory_fixture_not_real')
    for c in s['cases']:
        for ref in c['evidence'].values():validate_evidence(REPO,ref)
    cfg=load_memory_config(data_identity=dataset['data_identity'],task_digest=digest(task),snapshot_digest=s['snapshot_digest'],
                           entry_digests=[c['public_digest'] for c in s['cases']],enabled=True)
    state=initial(task['container'],3)
    for o in task['items'][:3]:state=receive(state,o,task['attributes'][o['item_id']])
    req,pol,b,empty=decision_inputs(state,task,cfg,'JN3A','JN3A_D0000')
    require(empty.data['route']=='CHOICE_REQUIRED','trajectory_fixed_query_not_choice')
    view,audit=retrieve(public_query(empty),snapshot,excluded_source_groups=pre['excluded_source_groups'])
    context=bind_decision(build_context(cfg,req,b,pol,memory_view=view),'JN3A','JN3A_D0000')
    for name,data in [('trajectory_snapshot.json',s),('memory_view.json',view.data),('retrieval.json',audit),('task.snapshot.json',task),
                      ('config.snapshot.json',cfg),('state.json',state),('observation.json',req),('bundle.json',b.data),('context.json',context.data),
                      ('request.json',context.data['request_body']),('source_manifest.json',source_manifest())]:write(root/name,data)
    package=Path(__file__).resolve().parents[1]
    for n in source_manifest():
        target=root/'code_snapshot'/n;target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(package/n,target)
    freeze={'version':'JN3-A_preregistration_v1','query_preregistration_digest':digest(pre),'context_digest':digest(context.data),
            'snapshot_digest':s['snapshot_digest'],'view_digest':view.data['view_digest'],'source_digest':digest(source_manifest()),
            'config_digest':digest(cfg),'request_digest':digest(context.data['request_body']),'retrieval_digest':digest(audit),
            'versions':VERSIONS,'max_sends':1,'ready_to_send':bool(view.data['entries']),
            'scope':'interface injection only; research benefit NOT_ESTABLISHED'}
    write(root/'preregistration.json',freeze)
    return freeze


def validate_frozen(root,*,current_source=True):
    root=Path(root);p=read(root/'preregistration.json');pre=read(root/'query_preregistration.json')
    s=read(root/'trajectory_snapshot.json');validate_snapshot(s,p['snapshot_digest'])
    # Rebuild from verified parent evidence, rather than trusting resealed private/public content.
    require(build_snapshot(REPO,PARENT,frozen_at=s['frozen_at']).data==s,'trajectory_evidence_projection_changed')
    require(digest(pre)==p['query_preregistration_digest'],'trajectory_query_registration_changed')
    manifest=read(root/'source_manifest.json')
    require(digest(manifest)==p['source_digest'],'trajectory_source_manifest_changed')
    require(all(sha(root/'code_snapshot'/n)==h for n,h in manifest.items()),'trajectory_archive_changed')
    if current_source:require(source_manifest()==manifest,'trajectory_current_source_changed')
    cfg=read(root/'config.snapshot.json');ctx=DecisionContext.from_dict(read(root/'context.json'));a=read(root/'retrieval.json')
    require(digest(cfg)==p['config_digest'] and digest(ctx.data)==p['context_digest'] and digest(a)==p['retrieval_digest'],'trajectory_binding_changed')
    require(digest(read(root/'task.snapshot.json'))==cfg['runtime_identity']['task_identity'],'trajectory_task_changed')
    from .packaging_runtime import validate_runtime_context
    validate_runtime_context(ctx,read(root/'observation.json'),CandidateBundle.from_dict(read(root/'bundle.json')),cfg)
    v,expected=retrieve(public_query(ctx),MemorySnapshotReceipt.from_dict(s),excluded_source_groups=pre['excluded_source_groups'])
    require(v.data==read(root/'memory_view.json')==ctx.data['memory_view'] and expected==a,'trajectory_retrieval_changed')
    require(read(root/'request.json')==ctx.data['request_body'] and digest(ctx.data['request_body'])==p['request_digest'],'trajectory_request_changed')
    return p


def run(output,*,api_key_file=None,transport=None):
    from .episode import run_episode
    from .transport import JevTransport
    root=Path(output)
    with exclusive(root):
        p=validate_frozen(root);require(p['ready_to_send'],'trajectory_NOT_READY')
        elsewhere=[r for r in prior_requests(root) if r['path']!=str((root/'request_ledger/requests.json').resolve().relative_to(REPO))]
        require(not elsewhere,'trajectory_other_attempt_exists')
        cfg=read(root/'config.snapshot.json');task=read(root/'task.snapshot.json');view=MemoryView.from_dict(read(root/'memory_view.json'))
        ledger=MemoryRequestLedger(root/'request_ledger',max_sends=1)
        selector=memory_selector_factory(METHOD,config=cfg,ledger=ledger,job_id='JN3A',transport=transport or JevTransport(cfg,api_key_file=api_key_file))
        def checkpoint(cp):
            write(root/'checkpoint.json',cp)
            if cp['phase'] in ('SELECTED','MONITORED','COMMITTED'):write(root/'stages'/f"{cp['phase']}.json",cp)
        resume=read(root/'checkpoint.json') if (root/'checkpoint.json').exists() else None
        ep=run_episode(task,selector,cfg,job_id='JN3A',method=METHOD,memory_view=view,resume=resume,on_checkpoint=checkpoint,event_limit=4)
        write(root/'episode.json',ep);write(root/'request_statistics.json',ledger.statistics())
        decisions=[e for e in ep['events'] if e.get('decision_id')]
        require(len(decisions)==1,'trajectory_decision_scope_changed')
        e=decisions[0]
        for n,v in [('decision.json',e),('selection.json',e['selection']),('monitor.json',e['monitor']),
                    ('execution.json',{'event':e['event'],'reason':e['reason'],'action':e['action'],'before_digest':digest(e['before']),'after_digest':digest(e['after'])}),
                    ('scope_stop.json',{'reason':'REGISTERED_SINGLE_DECISION_COMPLETE','order_continued':False,'natural_order_termination':ep['checkpoint']['reason']})]:write(root/n,v)
        rows=read(root/'request_ledger/requests.json')['requests']
        if rows:
            write(root/'transport.json',rows[0]['transport'])
        return {'event':e['event'],'monitor':e['monitor']['status'] if e['monitor'] else None,'statistics':ledger.statistics()}


def validate_saved(root):
    from .packaging_experiment import validate_saved_checkpoint
    from .selector import parse_response
    root=Path(root);p=validate_frozen(root);cfg=read(root/'config.snapshot.json');task=read(root/'task.snapshot.json')
    cp=read(root/'checkpoint.json');validate_saved_checkpoint(cp,task,cfg,'JN3A')
    for path in (root/'stages').glob('*.json'):validate_saved_checkpoint(read(path),task,cfg,'JN3A')
    obj=MemoryRequestLedger.__new__(MemoryRequestLedger);obj.root=root/'request_ledger';obj.path=obj.root/'requests.json';obj.max_sends=1
    rows=obj._load()['requests'];require(len(rows)==1 and rows[0]['send_started'],'trajectory_request_count_changed')
    ctx=DecisionContext.from_dict(read(root/'context.json'));r=rows[0]
    require(all(r[k]==v for k,v in obj.identity(ctx,'JN3A','JN3A_D0000').items()),'trajectory_request_binding_changed')
    require(parse_response(ctx,r,cfg).data==r['selection']==read(root/'selection.json'),'trajectory_response_selection_changed')
    e=read(root/'decision.json');require(e==next(e for e in cp['events'] if e.get('decision_id')),'trajectory_decision_changed')
    require(e['context']==ctx.data and e['selection']==r['selection'] and e['monitor']==read(root/'monitor.json'),'trajectory_stage_changed')
    require(read(root/'request_statistics.json')==obj.statistics(),'trajectory_statistics_changed')
    return {'status':'PASS','dispatch':'saved facts only; no network, selection, generation, commit or PCT',
            'real_T_entries':len(read(root/'trajectory_snapshot.json')['cases']),
            'request_body_nonempty':bool(ctx.data['request_body']['state']['memories']),
            'monitor_status':e['monitor']['status'] if e['monitor'] else None,'event':e['event']}


def main():
    parser=argparse.ArgumentParser();parser.add_argument('command',choices=['prepare','run','validate']);parser.add_argument('--output',required=True);parser.add_argument('--api-key-file')
    args=parser.parse_args()
    if args.command=='prepare':r=prepare(args.output)
    elif args.command=='run':r=run(args.output,api_key_file=args.api_key_file)
    else:r=validate_saved(args.output)
    print(canonical(r))

if __name__=='__main__':main()
