"""Saved-fact validation only: no dispatch, candidate generation, selector or LP.

Original geometry checks/descriptive facts and pure state transitions operate on
independent copies. They do not replay the order or call commit_physical.
"""
import copy
from dataclasses import asdict
import json
from pathlib import Path
from jsonschema import Draft202012Validator
from functools import lru_cache
from .contracts import digest,schema
from .persistence import require,RecoveryError,read_records

TERMINATIONS={'UNSTABLE':'PREDICTED_STATIC_INSTABILITY','UNASSESSABLE':'STABILITY_UNASSESSABLE','ERROR':'STABILITY_MONITOR_ERROR'}


@lru_cache(maxsize=16)
def _validator(name):
    document=schema(name)
    Draft202012Validator.check_schema(document)
    return Draft202012Validator(document)


def validate(name,value):
    from .protocol import validate_value
    _validator(name).validate(value);validate_value(name,value)


@lru_cache(maxsize=1)
def _result_validator():
    from importlib.resources import files
    resource=files('semantic_pallet_planner.jev_select.stability').joinpath('schemas/stability_result_v3.schema.json')
    document=json.loads(resource.read_text());Draft202012Validator.check_schema(document)
    return Draft202012Validator(document)


def validate_checkpoint(cp,task,config,job_id,method):
    from semantic_pallet_planner.o4.buffer.buffer_state import initial,receive,physical,can_wait
    from semantic_pallet_planner.o4.extensions.e2.protocol import observation
    from semantic_pallet_planner.o4.extensions.e2.planning import action_for
    from semantic_pallet_planner.evaluation.geometry_oracle import check_candidate
    from semantic_pallet_planner.evaluation.state import apply_candidate
    from semantic_pallet_planner.jev_select.contracts import CandidateBundle,DecisionContext
    from semantic_pallet_planner.jev_select.packaging_runtime import public_facts,no_policy,validate_runtime_context,evaluate_state
    from semantic_pallet_planner.jev_select.stability.geometry import state_from_runtime,box_from_runtime
    validate('checkpoint_b1_v1',cp)
    require(cp['record_digest']==digest({k:v for k,v in cp.items() if k!='record_digest'}),'CHECKPOINT_DIGEST_CHANGED')
    require(cp['task_digest']==digest(task) and cp['config_digest']==digest(config) and cp['runtime_identity']==config['runtime_identity'] and cp['job_id']==job_id and cp['method']==method,'CHECKPOINT_IDENTITY_CHANGED')
    state=initial(task['container'],1);cursor=decision=0;stopped=None

    def event_after(ev,before,committed,pending_phase=None):
        require(ev['before']==before,'SAVED_BEFORE_CHANGED')
        req=observation(copy.deepcopy(before),task['instruction_text'],task['regions'])
        require(ev['observation']==req and ev['decision_id']==f'{job_id}_D{decision:04d}','SAVED_DECISION_BINDING_CHANGED')
        bundle=CandidateBundle.from_dict(ev['bundle']);ctx=DecisionContext.from_dict(ev['context'])
        validate_runtime_context(ctx,observation=req,config=config)
        # Only deterministic public facts on a private copy, never candidate
        # generation, ContextBuilder.build or an order-engine replay.
        _,facts,criteria,mapping,_=public_facts(config,req,bundle,no_policy(req))
        require(ctx.data['model_state']==facts and ctx.data['criteria']==criteria and ctx.data['display_mapping']==mapping,'SAVED_PUBLIC_FACTS_OR_MAPPING_CHANGED')
        binding=ctx.data['local_binding']
        require(binding['job_id']==job_id and binding['decision_id']==ev['decision_id'] and binding['physical_digest']==bundle.data['physical_digest'] and binding['selectable_digest']==bundle.data['selectable_digest'],'SAVED_POOL_BINDING_CHANGED')
        for candidate in bundle.data['physical_candidates']:
            require(not check_candidate(physical(before,candidate['pick_item_id']),{'container':before['container']},candidate),'SAVED_PHYSICAL_CANDIDATE_CHANGED')
        n=len(bundle.data['selectable_candidates'])
        expected_route='STOP_NO_PHYSICAL_CANDIDATE' if not n else 'SINGLETON_BYPASS' if n==1 else 'CHOICE_REQUIRED'
        require(ev['route']==ctx.data['route']==expected_route,'SAVED_ROUTE_CHANGED')
        selected=ev['selection'];row=ev['monitor'];chosen=None
        if selected is not None:
            validate('selection_result_b1_v1',selected)
            require(selected['local_binding_digest']==digest(binding) and selected['network_attempted'] is False and selected['attempt_ids']==[],'SAVED_SELECTION_BINDING_CHANGED')
            if selected['status'] in ('selected','singleton'):
                label=selected['selected_display_id'];require(label in mapping,'SAVED_SELECTION_LABEL')
                require(selected['selected_candidate_id']==mapping[label]['candidate_id'] and (selected['status']=='singleton')==(n==1),'SAVED_SELECTION_CANDIDATE_CHANGED')
                chosen=next(c for c in bundle.data['selectable_candidates'] if c['candidate_id']==selected['selected_candidate_id'])
                require(ev['proposed_action']==action_for(req,bundle.data['physical_candidates'],chosen),'SAVED_ACTION_CHANGED')
        if pending_phase=='DECISION_READY':
            require(selected is None and row is None and ev['proposed_action'] is None and ev['action'] is None,'DECISION_READY_FIELDS')
        if pending_phase in ('SELECTED','MONITORED','COMMITTED'):require(chosen is not None,'SAVED_PHASE_SELECTION_MISSING')
        if pending_phase=='SELECTED':require(row is None,'SELECTED_HAS_MONITOR')
        if row is not None:
            require(chosen is not None,'MONITOR_WITHOUT_SELECTION')
            require(set(row)=={'version','binding','status','result','attempted','committed','result_digest','credential_digest'} and row['version']=='selected_action_monitor_v1','SAVED_MONITOR_FIELDS')
            expected={'state_digest':digest(before),'candidate_digest':digest(chosen),'action_digest':digest(ev['proposed_action']),
                'selection_digest':digest(selected),'context_digest':digest(ev['context']),'bundle_digest':digest(ev['bundle']),
                'decision_id':ev['decision_id'],'config_digest':digest(config),'runtime_identity':config['runtime_identity']}
            require(row['binding']==expected and row['attempted'] is True and row['committed'] is False,'SAVED_MONITOR_BINDING_CHANGED')
            require(row['result_digest']==digest(row['result']) and row['credential_digest']==digest({k:v for k,v in row.items() if k!='credential_digest'}),'SAVED_MONITOR_DIGEST_CHANGED')
            result=row['result'];frozen=config['stability_monitor']
            _result_validator().validate(result)
            require(row['status'] in ('STABLE','UNSTABLE','UNASSESSABLE','ERROR') and result['status']==row['status'],'SAVED_MONITOR_STATUS_CHANGED')
            obj=next(p['item'] for p in before['pending_items'] if p['item']['item_id']==chosen['pick_item_id'])
            box={**copy.deepcopy(obj),'pose':chosen['pose'],'oriented_size_mm':chosen['oriented_size_mm']}
            require(result['algorithm_identity']==frozen['algorithm_identity'] and result['config_digest']==digest(frozen['kernel_config']) and result['state_digest']==digest(asdict(state_from_runtime(before))) and result['candidate_digest']==digest(asdict(box_from_runtime(box))),'SAVED_KERNEL_BINDING_CHANGED')
        if pending_phase in ('MONITORED','COMMITTED'):require(row is not None,'SAVED_MONITOR_MISSING')
        if committed:
            require(row is not None and row['status']=='STABLE' and ev['action']==ev['proposed_action'] and ev['event']=='PLACE','SAVED_COMMIT_NOT_AUTHORIZED')
            after=copy.deepcopy(before)
            after['placed_items']=apply_candidate(physical(before),chosen)
            after['pending_items']=[p for p in after['pending_items'] if p['item']['item_id']!=chosen['pick_item_id']]
            after['placed_count']+=1;after['event_index']+=1
        else:
            after=copy.deepcopy(before)
            require(ev['action'] is None,'UNCOMMITTED_ACTION_PRESENT')
        require(ev['after']==after,'SAVED_AFTER_CHANGED')
        if pending_phase is None:
            require(ev['business_after']==evaluate_state(after),'SAVED_COMMIT_LEDGER_CHANGED')
            if row is not None and row['status'] in TERMINATIONS:require(ev['reason']==TERMINATIONS[row['status']],'SAVED_TERMINATION_CHANGED')
            if not committed:require(ev['reason'] is not None,'UNCOMMITTED_WITHOUT_STOP')
        return after

    for ev in cp['events']:
        require(stopped is None and ev['before']==state,'DISCONTINUOUS_OR_AFTER_STOP')
        if ev['event']=='WAIT_RECEIVE':
            require(cursor<len(task['items']) and can_wait(state),'INVALID_SAVED_RECEIVE')
            item=task['items'][cursor];after=receive(state,item,task['attributes'][item['item_id']]);cursor+=1
        elif ev['event']=='EOS':
            require(cursor==len(task['items']) and can_wait(state),'EARLY_SAVED_EOS')
            after=receive(state,eos=True)
        else:
            after=event_after(ev,state,ev['event']=='PLACE');decision+=1
            stopped=ev['reason']
        require(ev['after']==after,'SAVED_TRANSITION_CHANGED');state=after
    pending=cp['pending_event'];phase=cp['phase']
    if pending is not None:
        require(stopped is None and phase in ('DECISION_READY','SELECTED','MONITORED','COMMITTED') and cp['reason'] is None,'INVALID_SAVED_PENDING_PHASE')
        state=event_after(pending,state,phase=='COMMITTED',phase)
    else:require(phase in ('READY','TERMINATED'),'MISSING_SAVED_PENDING')
    require(cp['state']==state and cp['cursor']==cursor and cp['decision']==decision,'SAVED_PROGRESS_CHANGED')
    if cp['reason']=='ALL_ITEMS_PLACED':require(state['end_of_stream'] and not state['pending_items'] and len(state['placed_items'])==len(task['items']),'EARLY_COMPLETE')
    else:require(cp['reason']==stopped,'SAVED_STOP_CHANGED')
    require((phase=='TERMINATED')==(cp['reason'] is not None),'SAVED_TERMINAL_PHASE_CHANGED')
    return cp


def validate_job(root,*,check_current=False):
    header,rows=read_records(root)
    from .recovery import check_header
    check_header(header,check_current=check_current)
    previous=None
    allowed={'READY':{'READY','DECISION_READY','TERMINATED'},'DECISION_READY':{'SELECTED','TERMINATED'},
        'SELECTED':{'MONITORED'},'MONITORED':{'COMMITTED','TERMINATED'},'COMMITTED':{'READY','TERMINATED'},'TERMINATED':set()}
    for record in rows:
        cp=record['checkpoint'];validate_checkpoint(cp,header['task'],header['config'],header['admission']['job_id'],'geometry_b1')
        if previous:
            require(cp['phase'] in allowed[previous['phase']],'ILLEGAL_JOURNAL_PHASE_TRANSITION')
            require(cp['events'][:len(previous['events'])]==previous['events'],'SAVED_HISTORY_REWRITTEN')
            require(len(cp['events'])-len(previous['events']) in (0,1),'JOURNAL_EVENT_GAP')
            old=previous['pending_event']
            if old:
                new=cp['pending_event'] or (cp['events'][-1] if len(cp['events'])>len(previous['events']) else None)
                require(new is not None and new['decision_id']==old['decision_id'],'SAVED_PENDING_REPLACED')
                for key in ('before','observation','bundle','context','selection','proposed_action','monitor'):
                    if old[key] is not None:require(new[key]==old[key],'SAVED_STAGE_FACT_OVERWRITTEN:'+key)
        previous=cp
    intent=Path(root)/'commit_intent.json'
    if intent.exists():
        value=json.loads(intent.read_text())
        require(set(value)=={'version','decision_id','before_digest','selection_digest'} and value['version']=='pct_b1_commit_intent_v1','INVALID_COMMIT_INTENT')
        require(previous is not None and previous['phase']=='COMMITTED' and previous['pending_event']['decision_id']==value['decision_id'],'COMMIT_OUTCOME_UNKNOWN')
        require(value['before_digest']==digest(previous['pending_event']['before']) and value['selection_digest']==digest(previous['pending_event']['selection']),'COMMIT_INTENT_BINDING_CHANGED')
    episode_path=Path(root)/'episode.json'
    if episode_path.exists():
        value=json.loads(episode_path.read_text())
        require(previous is not None and previous['phase']=='TERMINATED' and set(value)=={'job_id','events','final_state','summary','checkpoint'},'INVALID_SAVED_EPISODE')
        require(value['checkpoint']==previous and value['events']==previous['events'] and value['final_state']==previous['state'] and value['job_id']==header['admission']['job_id'],'SAVED_EPISODE_CHANGED')
        from .execution import summarize_episode
        expected=summarize_episode(header['task'],header['config'],'geometry_b1',previous['state'],previous['events'],previous['reason'])
        require(value['summary']==expected,'SAVED_SUMMARY_LEDGER_CHANGED')
    return {'status':'PASS_SAVED_FACTS_ONLY','records':len(rows),'last_phase':previous['phase'] if previous else 'NOT_STARTED',
        'checkpoint':previous,'header':header,'rows':rows,'business_dispatch':'NONE'}
