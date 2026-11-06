"""JN3-B fixed-query E injection; shared episode/monitor/commit only, one decision."""
from __future__ import annotations
import argparse
from pathlib import Path
from .contracts import canonical,digest,DecisionContext,CandidateBundle
from .ledger import read,write,exclusive
from .experiment import source_manifest
from . import packaging_contrast as e
from . import packaging_contrast_generation as generation
from .packaging_contrast_protocol import load_contrast_config,ContrastRequestLedger,contrast_selector_factory,VERSIONS
from .packaging_experience import require,public_query

REPO=Path(__file__).resolve().parents[4]
A=REPO/'semantic_pallet_planner/outputs/JEV_JN3_20261104_01'


def other_E_requests(root):
    return [str(f.relative_to(REPO)) for f in (REPO/'semantic_pallet_planner/outputs').glob('JEV_JN3_*/E_request_ledger/requests.json') if f.resolve()!=(Path(root)/'E_request_ledger/requests.json').resolve() and read(f)['requests']]


def prepare(root):
    from .packaging_runtime import load_runtime_dataset,build_context
    from .episode import decision_inputs
    from .selector import bind_decision
    from semantic_pallet_planner.o4.buffer.buffer_state import initial,receive
    root=Path(root);generation.validate_saved(root)
    require(not (root/'E_preregistration.json').exists(),'contrast_decision_already_registered')
    s=read(root/'contrast_snapshot.json');e.validate_snapshot(s)
    # No card or no isolated hit is a saved NOT_READY, never a replacement query.
    pre=read(A/'query_preregistration.json')
    write(root/'E_query_preregistration.json',{'version':'JN3-B_query_preregistration_v1','T_query_rule':pre,
      'scope':'same fixed first parent task; new receive-only prefix, not replayed T/Jev history',
      'generation_plan_digest':read(root/'generation_plan.json')['plan_digest'],'max_E_Jev_sends':1,'historical_T_sends':1,
      'no_replacement_or_retry':True})
    if read(root/'generation_ledger.json')['unknown_sends']:
        write(root/'E_preparation_status.json',{'status':'NOT_READY','reason':'GENERATION_UNKNOWN_SEND_STOP','library_nonempty':bool(s['cards']),'retrieval_nonempty':False,'request_nonempty':False})
        return read(root/'E_preparation_status.json')
    if not s['cards']:
        write(root/'E_preparation_status.json',{'status':'NOT_READY','reason':'NO_APPROVED_REAL_CARD','library_nonempty':False,'retrieval_nonempty':False,'request_nonempty':False})
        return read(root/'E_preparation_status.json')
    require(not any(c['fixture_only'] for c in s['cards']) or read(root/'generation_plan.json')['fixture_only'],'contrast_fixture_cannot_be_real')
    require(not other_E_requests(root),'contrast_previous_E_attempt_exists')
    plan=read(REPO/'semantic_pallet_planner/outputs/JEV_JN1_20261103_03/plan/plan.json')
    dataset=load_runtime_dataset(REPO/plan['dataset']);task=next(t for t in dataset['tasks'] if t['task_id']==pre['task_id'])
    cfg=load_contrast_config(data_identity=dataset['data_identity'],task_digest=digest(task),snapshot_digest=s['snapshot_digest'],entry_digests=[c['public_digest'] for c in s['cards']],enabled=True)
    state=initial(task['container'],3)
    for o in task['items'][:3]:state=receive(state,o,task['attributes'][o['item_id']])
    req,pol,b,empty=decision_inputs(state,task,cfg,'JN3B','JN3B_D0000');require(empty.data['route']=='CHOICE_REQUIRED','contrast_fixed_query_not_choice')
    view,audit=e.retrieve(public_query(empty),s,excluded_source_groups=pre['excluded_source_groups'])
    context=bind_decision(build_context(cfg,req,b,pol,memory_view=view),'JN3B','JN3B_D0000')
    for n,v in [('E_task.snapshot.json',task),('E_config.snapshot.json',cfg),('E_state.json',state),('E_observation.json',req),
                ('E_bundle.json',b.data),('E_context.json',context.data),('E_request.json',context.data['request_body']),('E_memory_view.json',view.data),('E_retrieval.json',audit)]:write(root/n,v)
    frozen={'version':'JN3-B_E_preregistration_v1','versions':VERSIONS,'context_digest':digest(context.data),'config_digest':digest(cfg),
            'source_digest':digest(source_manifest()),'snapshot_digest':s['snapshot_digest'],'view_digest':view.data['view_digest'],
            'query_preregistration_digest':digest(read(root/'E_query_preregistration.json')),'request_digest':digest(context.data['request_body']),
            'retrieval_digest':digest(audit),'max_sends':1,'ready_to_send':bool(view.data['entries'])}
    write(root/'E_preregistration.json',frozen)
    status={'status':'READY' if frozen['ready_to_send'] else 'NOT_READY','reason':'FROZEN_NONEMPTY' if frozen['ready_to_send'] else 'FIXED_QUERY_NO_COMPLETE_ISOLATED_HIT',
            'library_nonempty':True,'retrieval_nonempty':bool(view.data['entries']),'request_nonempty':bool(view.data['entries'])}
    write(root/'E_preparation_status.json',status);return status


def validate_frozen(root):
    from .packaging_runtime import validate_runtime_context
    root=Path(root);generation.validate_saved(root);p=read(root/'E_preregistration.json');s=read(root/'contrast_snapshot.json');e.validate_snapshot(s,p['snapshot_digest'])
    cfg=read(root/'E_config.snapshot.json');ctx=DecisionContext.from_dict(read(root/'E_context.json'))
    require(digest(ctx.data)==p['context_digest'] and digest(cfg)==p['config_digest'] and digest(source_manifest())==p['source_digest'],'contrast_decision_identity_changed')
    require(digest(read(root/'E_task.snapshot.json'))==cfg['runtime_identity']['task_identity'],'contrast_decision_task_changed')
    require(digest(read(root/'E_query_preregistration.json'))==p['query_preregistration_digest'],'contrast_query_registration_changed')
    validate_runtime_context(ctx,read(root/'E_observation.json'),CandidateBundle.from_dict(read(root/'E_bundle.json')),cfg)
    pre=read(root/'E_query_preregistration.json')['T_query_rule'];view,audit=e.retrieve(public_query(ctx),s,excluded_source_groups=pre['excluded_source_groups'])
    require(view.data==read(root/'E_memory_view.json')==ctx.data['memory_view'] and audit==read(root/'E_retrieval.json') and digest(audit)==p['retrieval_digest'],'contrast_retrieval_changed')
    require(read(root/'E_request.json')==ctx.data['request_body'] and digest(ctx.data['request_body'])==p['request_digest'],'contrast_body_changed')
    return p


def run(root,*,api_key_file=None,transport=None):
    from .episode import run_episode
    from .transport import JevTransport
    root=Path(root)
    with exclusive(root):
        p=validate_frozen(root);require(p['ready_to_send'],'contrast_E_NOT_READY');require(not other_E_requests(root),'contrast_other_E_request_exists')
        plan=read(root/'generation_plan.json');require(plan['fixture_only']==(transport is not None),'contrast_E_transport_mode_changed')
        cfg=read(root/'E_config.snapshot.json');task=read(root/'E_task.snapshot.json');view=e.EMemoryView.from_dict(read(root/'E_memory_view.json'))
        ledger=ContrastRequestLedger(root/'E_request_ledger',max_sends=1)
        selector=contrast_selector_factory(e.METHOD,config=cfg,ledger=ledger,job_id='JN3B',transport=transport if transport is not None else JevTransport(cfg,api_key_file=api_key_file))
        def checkpoint(cp):
            write(root/'E_checkpoint.json',cp)
            if cp['phase'] in ('SELECTED','MONITORED','COMMITTED'):write(root/'E_stages'/f"{cp['phase']}.json",cp)
        resume=read(root/'E_checkpoint.json') if (root/'E_checkpoint.json').exists() else None
        ep=run_episode(task,selector,cfg,job_id='JN3B',method=e.METHOD,memory_view=view,resume=resume,on_checkpoint=checkpoint,event_limit=4)
        write(root/'E_episode.json',ep);write(root/'E_request_statistics.json',ledger.statistics())
        events=[x for x in ep['events'] if x.get('decision_id')];require(len(events)==1,'contrast_decision_scope_changed')
        event=events[0]
        for n,v in [('E_decision.json',event),('E_selection.json',event['selection']),('E_monitor.json',event['monitor']),
           ('E_execution.json',{'event':event['event'],'reason':event['reason'],'action':event['action'],'before_digest':digest(event['before']),'after_digest':digest(event['after'])}),
           ('E_scope_stop.json',{'reason':'REGISTERED_SINGLE_E_DECISION_CLOSED','continued':False,'natural_order_reason':ep['checkpoint']['reason']})]:write(root/n,v)
        return {'event':event['event'],'monitor':event['monitor']['status'] if event['monitor'] else None,'statistics':ledger.statistics()}


def validate_saved(root):
    from .packaging_experiment import validate_saved_checkpoint
    from .selector import parse_response
    root=Path(root);gen=generation.validate_saved(root)
    if not (root/'E_preregistration.json').exists():return {'status':'PASS','generation':gen,'E_status':read(root/'E_preparation_status.json')}
    p=validate_frozen(root);cfg=read(root/'E_config.snapshot.json');task=read(root/'E_task.snapshot.json')
    if not (root/'E_checkpoint.json').exists():return {'status':'PASS','generation':gen,'E_status':read(root/'E_preparation_status.json')}
    cp=read(root/'E_checkpoint.json');validate_saved_checkpoint(cp,task,cfg,'JN3B')
    for f in (root/'E_stages').glob('*.json'):validate_saved_checkpoint(read(f),task,cfg,'JN3B')
    ledger=ContrastRequestLedger.__new__(ContrastRequestLedger);ledger.root=root/'E_request_ledger';ledger.path=ledger.root/'requests.json';ledger.max_sends=1
    rows=ledger._load()['requests'];require(len(rows)==1 and rows[0]['send_started'],'contrast_saved_E_count_changed');row=rows[0]
    ctx=DecisionContext.from_dict(read(root/'E_context.json'))
    require(all(row[k]==v for k,v in ledger.identity(ctx,'JN3B','JN3B_D0000').items()),'contrast_E_request_identity_changed')
    require(parse_response(ctx,row,cfg).data==row['selection']==read(root/'E_selection.json'),'contrast_E_response_changed')
    ev=read(root/'E_decision.json');require(ev==next(x for x in cp['events'] if x.get('decision_id')) and ev['context']==ctx.data and ev['selection']==row['selection'] and ev['monitor']==read(root/'E_monitor.json'),'contrast_E_saved_event_changed')
    require(read(root/'E_request_statistics.json')==ledger.statistics(),'contrast_E_statistics_changed')
    return {'status':'PASS','generation':gen,'E_request_nonempty':bool(ctx.data['model_state']['memories']),
            'E_monitor':ev['monitor']['status'] if ev['monitor'] else None,'E_event':ev['event'],'E_model_calls':ledger.statistics()['model_calls']}


def main():
    p=argparse.ArgumentParser();p.add_argument('command',choices=['prepare','run','validate']);p.add_argument('--output',required=True);p.add_argument('--api-key-file');a=p.parse_args()
    r=prepare(a.output) if a.command=='prepare' else run(a.output,api_key_file=a.api_key_file) if a.command=='run' else validate_saved(a.output)
    print(canonical(r))
if __name__=='__main__':main()
