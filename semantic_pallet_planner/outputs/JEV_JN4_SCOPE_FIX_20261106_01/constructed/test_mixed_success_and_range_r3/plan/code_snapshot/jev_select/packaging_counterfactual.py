"""JN2-A saved training forks over the common monitored v5 episode.

No transport, credentials, historical suffix replay or second order engine.
A fork is a new v1 orchestration identity, not a re-signed parent checkpoint.
"""
from __future__ import annotations
import copy
import hashlib
import math
import shutil
import time
from pathlib import Path

from .contracts import CandidateBundle, DecisionContext, JevSelectError, digest, validate_schema
from .ledger import read, write, exclusive
from .experiment import source_manifest, file_manifest
from . import packaging_experiment as common
from .packaging_runtime import (LocalPackagingDouble, build_context, no_policy,
                                physical_manifest, validate_runtime_context)
from .stability.monitor import load_monitor_config, seal_checkpoint, preflight
from .selector import bind_decision, result
from .packaging_protocol import termination_category, METRICS_CONTRACT
from .packaging_metrics import job_metrics

VERSION = 'jev_training_fork_v1'
METHOD = 'local_geometry_test_double'
RULE = {
    'decision': 'parent real Jev job order then ascending decision; earliest committed multi-choice with complete verified input',
    'alternative': 'one same-box different-pose then one cross-box; absent class leaves gap, no fill',
    'probability': 'complete finite native map: descending value then normalized exact-action SHA256; otherwise digest only',
    'dedup': 'SHA256 of pick_item_id, pose and oriented_size_mm; exclude original and duplicate exact actions',
    'provider_explicit_rank': 'UNAVAILABLE', 'provider_tie_rule': 'UNKNOWN',
    'stop': 'natural stop; technical error stops remaining branches; no reselection or replacement',
}


def require(ok, code):
    if not ok:
        raise JevSelectError(code)


def seal(value):
    value['record_digest'] = digest({k:v for k,v in value.items() if k != 'record_digest'})
    return value


def check_seal(value):
    require(value['record_digest'] == digest({k:v for k,v in value.items() if k != 'record_digest'}), 'fork_record_changed')


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def audit_parent(parent):
    """Validate frozen bytes against historical manifests, not current source equality."""
    parent = Path(parent).resolve()
    manifest = read(parent/'delivery_manifest.json')
    require(all(sha(parent/n) == h for n,h in manifest['files_sha256'].items()), 'fork_parent_files_changed')
    p = read(parent/'plan/plan.json')
    receipt = read(parent/'jn2_input_receipt.json')
    require(receipt['JN2_admitted'] and receipt['data_identity'] == p['data_identity'] and
            receipt['plan_digest'] == digest(p) and receipt['source_manifest_digest'] == digest(p['source_manifest']), 'fork_parent_not_admitted')
    require(read(parent/'source_manifest.json') == p['source_manifest'], 'fork_parent_source_manifest_changed')
    require(all(sha(parent/'plan/code_snapshot'/n) == h for n,h in p['source_manifest'].items()), 'fork_parent_source_snapshot_changed')
    require(read(parent/'jn2_decision_index.json')['all_decisions'] == read(parent/'run/decision_index.json'), 'fork_parent_index_changed')
    require(p['physical_manifest'] == physical_manifest(), 'fork_physics_changed')
    # The archived source stays frozen; current additions and viewer files do not invalidate it.
    return {'version':VERSION, 'parent':common.relative(parent), 'manifest_sha256':sha(parent/'delivery_manifest.json'),
            'plan_digest':digest(p), 'source_manifest_digest':digest(p['source_manifest']),
            'data_identity':p['data_identity'], 'files_verified':len(manifest['files_sha256']),
            'verification':'archived bytes + physical identity; no execution or current-source re-signing'}


def restore_training_fork(parent, decision_id):
    parent = Path(parent).resolve()
    identity = audit_parent(parent)
    p = read(parent/'plan/plan.json')
    rows = read(parent/'jn2_decision_index.json')['all_decisions']
    matches = [r for r in rows if r['decision_id'] == decision_id]
    require(len(matches) == 1 and matches[0]['eligible_training_decision'], 'fork_ineligible_decision')
    row = matches[0]; job = parent/'run/jobs'/row['job_id']
    entry = next(j for j in p['jobs'] if j['job_id'] == row['job_id'])
    task = read(job/'task.snapshot.json'); cfg = read(job/'config.snapshot.json')
    d = read(parent/'run'/row['record']); check_seal(d)
    require(digest(d) == row['record_digest'] and cfg == entry['config'] and digest(task) == entry['task_digest']
            and read(parent/'plan/tasks'/f"{task['task_id']}.json") == task, 'fork_task_or_config_changed')
    require(task['partition'] == 'train' and entry['method_id'] == 'jev_no_memory' and
            d['source_group'] == task['source_group_id'] == entry['source_group_id'] and
            d['task_id'] == task['task_id'] and d['data_identity'] == p['data_identity'] and
            d['config_digest'] == digest(cfg) and d['source_manifest_digest'] == digest(p['source_manifest']), 'fork_source_or_identity_changed')
    cp = read(job/'checkpoint.json')
    common.validate_saved_checkpoint(cp, task, cfg, row['job_id'])
    indices = [i for i,e in enumerate(cp['events']) if e.get('decision_id') == decision_id]
    require(len(indices) == 1, 'fork_event_missing')
    index = indices[0]; e = cp['events'][index]
    require(e == read(job/'actions'/f'{decision_id}.json') and e['event'] == 'PLACE' and
            e['selection']['source'] == 'jev' and e['route'] == 'CHOICE_REQUIRED', 'fork_original_not_committed_real_choice')
    from .packaging_orders import record
    requests=read(parent/'run/request_ledger/requests.json')['requests']
    saved_requests=[r for r in requests if r['decision_id']==decision_id]
    require(d['request_receipts']==saved_requests and any(r['origin']=='jev' and r['send_started'] for r in saved_requests), 'fork_request_receipt_mismatch')
    require(d == record(e, task, cfg, p, saved_requests), 'fork_decision_event_mismatch')
    stage = read(job/'stages'/decision_id/'SELECTED.json')
    common.validate_saved_checkpoint(stage, task, cfg, row['job_id'])
    state = d['before']; cursor = d['arrival_cursor']
    from semantic_pallet_planner.o4.buffer.buffer_state import invariant
    invariant(state)
    # receive increments arrival_count only for a real item, not EOS; prefix
    # WAIT_RECEIVE count and arrived sequence independently bind the next index.
    require(cursor == state['arrival_count'] == stage['cursor'] == sum(x['event']=='WAIT_RECEIVE' for x in cp['events'][:index])
            and state['arrived_ids'] == [x['item_id'] for x in task['items'][:cursor]]
            and state == stage['state'] and d['buffer'] == state['pending_items'], 'fork_arrival_progress_mismatch')
    require(stage['pending_event']['bundle'] == d['candidate_pool'] and stage['pending_event']['before'] == state and
            e['context']['display_mapping'] == d['display_mapping'] and len(d['display_mapping']) >= 2, 'fork_pool_mismatch')
    require(any(c['candidate_id'] != d['selected_candidate_id'] for c in d['candidate_pool']['selectable_candidates']), 'fork_no_alternative')
    snapshot = {'version':VERSION, 'parent_identity':identity, 'decision_id':decision_id, 'parent_job_id':row['job_id'],
                'record':row['record'], 'parent_record_digest':d['record_digest'], 'source_group':task['source_group_id'],
                'task_digest':digest(task), 'parent_config':cfg, 'state':state, 'cursor':cursor,
                'end_of_stream':state['end_of_stream'], 'buffer':d['buffer'], 'pool':d['candidate_pool'],
                'mapping':d['display_mapping'], 'event':e,
                'field_evidence':{'state':'DecisionRecord.before == SELECTED.state',
                    'cursor':'arrival_count == SELECTED.cursor == preceding WAIT_RECEIVE count; arrived_ids == task.items[:cursor]',
                    'pool':'DecisionRecord.candidate_pool == SELECTED.pending_event.bundle',
                    'task':common.relative(job/'task.snapshot.json'), 'prefix_events':index}}
    seal(snapshot);validate_schema("packaging_fork_snapshot_v1",snapshot)
    return snapshot


def exact_key(candidate):
    return digest({k:candidate[k] for k in ('pick_item_id','pose','oriented_size_mm')})


def interventions(snapshot):
    e = snapshot['event']; original = e['selection']['selected_candidate_id']
    pool = {c['candidate_id']:c for c in snapshot['pool']['selectable_candidates']}
    chosen = pool[original]; mapping = snapshot['mapping']; probabilities = e['selection'].get('probabilities')
    complete = (isinstance(probabilities,dict) and set(probabilities)==set(mapping) and
                all(type(p) in (int,float) and math.isfinite(p) and 0<=p<=1 for p in probabilities.values()))
    labels = {v['candidate_id']:k for k,v in mapping.items()}
    candidates = sorted(pool.values(),key=lambda c: (-(probabilities[labels[c['candidate_id']]]) if complete else 0, exact_key(c)))
    used = {exact_key(chosen)}; dedup = []
    for c in candidates:
        if exact_key(c) not in used:
            dedup.append(c); used.add(exact_key(c))
    def entry(c,kind):
        label = labels[c['candidate_id']]
        return {'candidate':c, 'exact_digest':exact_key(c), 'parent_display_id':label,
                'native_probability':probabilities.get(label) if isinstance(probabilities,dict) else None,
                'intervention':kind, 'original_box':chosen['pick_item_id'], 'box':c['pick_item_id'],
                'original_pose':chosen['pose'], 'pose':c['pose']}
    branches = [entry(chosen,'ORIGINAL_ACTION_REFERENCE')]; gaps=[]
    for kind,same in [('SAME_BOX_DIFFERENT_POSE',True),('CROSS_BOX_SELECTION',False)]:
        match = next((c for c in dedup if (c['pick_item_id']==chosen['pick_item_id']) == same),None)
        if match is None:gaps.append(kind)
        else:branches.append(entry(match,kind))
    return {'branches':branches,'coverage_gaps':gaps,'native_probability_complete':complete,
            'native_probabilities':probabilities, 'rules':RULE,
            'interpretation':'program-derived sampling; not explicit service rank or physical confidence'}


def continuation_factory():
    """Public current context only; no task/fork/monitor outcome supplied."""
    return LocalPackagingDouble(METHOD)


def validate_fork(binding, task, config):
    validate_schema("packaging_fork_binding_v1",binding)
    validate_schema("packaging_fork_snapshot_v1",binding["snapshot"])
    check_seal(binding)
    require(binding['version']==VERSION and config['version']=='jev_packaging_monitored_v5' and
            config['selector']==METHOD and digest(config)==binding['config_digest'] and
            digest(task)==binding['snapshot']['task_digest'] and task['partition']=='train', 'fork_execution_binding_changed')
    s = restore_training_fork(common.REPO/binding['snapshot']['parent_identity']['parent'], binding['snapshot']['decision_id'])
    require(s == binding['snapshot'], 'fork_snapshot_changed')
    require(binding['first'] in interventions(s)['branches'], 'fork_unregistered_first_action')
    require(s['parent_config']['stability_monitor'] == config['stability_monitor'], 'fork_monitor_changed')
    preflight(config)


def bootstrap(binding, task, config, job_id):
    validate_fork(binding, task, config)
    require(binding['job_id'] == job_id, 'fork_job_changed')
    s = binding['snapshot']; e = copy.deepcopy(s['event'])
    # Explicit v6->v5 envelope adapter. Candidate objects and original label map
    # remain byte-equivalent; only new config/job/selection credentials change.
    b = copy.deepcopy(s['pool']); b['version']='jev_candidate_bundle_v5'
    bundle = CandidateBundle.from_dict(b)
    ctx = bind_decision(build_context(config,e['observation'],bundle,no_policy(e['observation'])),job_id,f'{job_id}_D0000')
    require(ctx.data['display_mapping']==s['mapping'], 'fork_mapping_changed')
    candidate = binding['first']['candidate']
    label = next(k for k,v in ctx.data['display_mapping'].items() if v['candidate_id']==candidate['candidate_id'])
    require(next(c for c in b['selectable_candidates'] if c['candidate_id']==candidate['candidate_id']) == candidate, 'fork_exact_candidate_changed')
    selection = result(ctx,status='selected',source='test_double',label=label)
    from semantic_pallet_planner.o4.extensions.e2.planning import action_for
    e.update(event='STOP',decision_id=f'{job_id}_D0000',before=copy.deepcopy(s['state']),after=copy.deepcopy(s['state']),
             bundle=b,context=ctx.data,selection=selection.data,
             proposed_action=action_for(e['observation'],b['physical_candidates'],candidate),action=None,
             monitor=None,monitor_result_reuses=0,reason=None,error=None,reference_after=None,business_after=None,
             timings={'public_business_s':0.,'selection_s':0.,'physical_commit_s':0.,'independent_evaluation_s':0.,'checkpoint_io_s':0.})
    cp = {'version':'jev_checkpoint_v5','job_id':job_id,'method':METHOD,'task_digest':digest(task),'config_digest':digest(config),
          'state':copy.deepcopy(s['state']),'cursor':s['cursor'],'decision':0,'events':[],'reason':None,
          'phase':'SELECTED','pending_event':e,'runtime_identity':config['runtime_identity']}
    seal_checkpoint(cp);validate_schema('checkpoint_v5',cp)
    return cp


def validate_branch_checkpoint(cp, task, config, job_id, binding):
    # bootstrap validates parent identity. No prefix commit, selector or LP calls.
    require(binding['job_id']==job_id,'fork_job_changed')
    common.validate_saved_checkpoint(cp,task,config,job_id,fork_origin=binding['snapshot'])
    decisions=[e for e in cp['events'] if e.get('decision_id')]
    if cp['pending_event']:decisions.append(cp['pending_event'])
    require(bool(decisions),'fork_missing_first')
    first=decisions[0]; saved=binding['snapshot']; expected=binding['first']['candidate']
    require(first['before']==saved['state'] and first['bundle']['physical_candidates']==saved['pool']['physical_candidates'] and
            first['context']['display_mapping']==saved['mapping'] and first['selection']['selected_candidate_id']==expected['candidate_id'], 'fork_first_changed')
    require(sum(e['decision_id']==f'{job_id}_D0000' for e in decisions)==1,'fork_first_repeated')
    return cp


def prepare(parent, output):
    parent=Path(parent).resolve();audit=audit_parent(parent)
    # A new window cannot obtain a fresh A budget for the same parent.
    for receipt in (common.REPO/'semantic_pallet_planner/outputs').glob('JEV_JN2_*/branch_plan.json'):
        require(read(receipt)['parent_identity']['manifest_sha256'] != audit['manifest_sha256'], 'fork_existing_A_registration_use_resume')
    p=read(parent/'plan/plan.json'); rows=read(parent/'jn2_decision_index.json')['all_decisions']; scanned=[];snapshot=None
    for j in p['jobs']:
        if j['method_id']!='jev_no_memory':continue
        for r in sorted((r for r in rows if r['job_id']==j['job_id']),key=lambda r:r['decision_id']):
            if not r['eligible_training_decision']:continue
            candidate=restore_training_fork(parent,r['decision_id'])
            scanned.append({'decision_id':r['decision_id'],'status':'VERIFIED_ELIGIBLE'})
            snapshot=candidate;break
        if snapshot is not None:break
    require(snapshot is not None,'fork_no_eligible_input')
    task=read(common.REPO/snapshot['field_evidence']['task'])
    cfg=load_monitor_config(data_identity=audit['data_identity'],task_digest=digest(task),method=METHOD,enabled=True)
    require(cfg['stability_monitor']==snapshot['parent_config']['stability_monitor'],'fork_parent_monitor_drift')
    selected=interventions(snapshot)
    plan={'version':VERSION,'parent_identity':audit,'fork_digest':digest(snapshot),'source_group':snapshot['source_group'],
          'decision_id':snapshot['decision_id'],'task_digest':digest(task),'config':cfg,'selection':selected,'scanned':scanned,
          'continuation':{'method':METHOD,'display_seed':cfg['display_order_seed'],'randomness':'deterministic; no additional RNG',
                          'identity':cfg['runtime_identity']['strategy_identity']},
          'source_manifest':source_manifest(),'physical_manifest':physical_manifest(),
          'metrics_contract':dict(METRICS_CONTRACT,version='jev_training_branch_metrics_v1',branch_and_memory='prefix/final/increment; no memory'),
          'watchdog':{'max_events':10000,'max_active_wall_s':600},'watchdog_boundary':'durable persistence only; no preemption inside candidate generation or LP',
          'budget':{'A_max_suffixes':3,'registered':len(selected['branches']),'new_model_calls':0,'B_total_max_including_A':12},
          'branch_order':[f'B{i:02d}' for i in range(len(selected['branches']))], 'rules':RULE,
          'stop_rule':'technical/error/cancel/watchdog stops remainder with NOT_RUN; natural stops continue; no retry or decision change'}
    root=common.new_output(output)
    write(root/'fork_snapshot.json',snapshot);write(root/'task.private.json',task)
    seal(plan);validate_schema('packaging_fork_plan_v1',plan)
    write(root/'branch_plan.json',plan);write(root/'parent_verification.json',audit)
    write(root/'registration_receipt.json',{'plan_digest':digest(plan),'fork_digest':digest(snapshot)})
    for n in plan['source_manifest']:
        dest=root/'code_snapshot'/n;dest.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(Path(__file__).resolve().parents[1]/n,dest)
    for i,first in enumerate(selected['branches']):
        jid=f'B{i:02d}';binding=seal({'version':VERSION,'job_id':jid,'snapshot':snapshot,'first':first,'config_digest':digest(cfg),'plan_digest':digest(plan)})
        write(root/'branches'/jid/'binding.json',binding)
        write(root/'branches'/jid/'status.json',{'state':'NOT_RUN','category':'NOT_RUN','active_wall_s':0.,'error':None})
    return plan


def validate_plan(root):
    root=Path(root);p=read(root/'branch_plan.json');validate_schema('packaging_fork_plan_v1',p);check_seal(p)
    require(p['version']==VERSION and p['source_manifest']==source_manifest() and p['physical_manifest']==physical_manifest(), 'fork_source_changed')
    require(read(root/'registration_receipt.json')=={'plan_digest':digest(p),'fork_digest':p['fork_digest']}, 'fork_plan_changed')
    s=read(root/'fork_snapshot.json');t=read(root/'task.private.json')
    require(digest(s)==p['fork_digest'] and digest(t)==p['task_digest'] and interventions(s)==p['selection'], 'fork_plan_input_changed')
    require(p['rules']==RULE and p['selection']['rules']==RULE and p['continuation']=={
        'method':METHOD,'display_seed':p['config']['display_order_seed'],'randomness':'deterministic; no additional RNG',
        'identity':p['config']['runtime_identity']['strategy_identity']},'fork_policy_changed')
    require(p['budget']=={'A_max_suffixes':3,'registered':len(p['branch_order']),'new_model_calls':0,'B_total_max_including_A':12}
            and p['branch_order']==[f'B{i:02d}' for i in range(len(p['selection']['branches']))] and 1<=len(p['branch_order'])<=3, 'fork_budget_changed')
    require(all(sha(root/'code_snapshot'/n)==h for n,h in p['source_manifest'].items()),'fork_code_snapshot_changed')
    for jid,first in zip(p['branch_order'],p['selection']['branches']):
        binding=read(root/'branches'/jid/'binding.json')
        require(binding==seal({'version':VERSION,'job_id':jid,'snapshot':s,'first':first,'config_digest':digest(p['config']),'plan_digest':digest(p)}), 'fork_branch_binding_changed')
        validate_fork(binding,t,p['config'])
    return p,t


def branch_metrics(task,cfg,cp,status,snapshot):
    m=job_metrics(task,cfg,cp,status)
    m['version']='jev_training_branch_metrics_v1'
    from math import prod
    def quantities(state):
        return {'items':len(state['placed_items']),'volume_mm3':sum(prod(x['oriented_size_mm']) for x in state['placed_items']),
                'mass_kg':sum(x['mass_kg'] for x in state['placed_items'])}
    prefix=quantities(snapshot['state']);final=quantities(cp['state'])
    m['branch_metrics']={'prefix':prefix,'final':final,'suffix_increment':{k:final[k]-prefix[k] for k in prefix},
                         'monitor_scope':'suffix only; saved parent prefix monitor evidence retained separately',
                         'prefix_stable_commits':snapshot['state']['placed_count']}
    m['stable_complete']=bool(m['completed'] and cfg['stability_monitor']['enabled'] and
        m['monitor_statuses']['STABLE']+snapshot['state']['placed_count']==len(task['items']))
    return m


def branch_receipt(root,jid,p,task):
    job=Path(root)/'branches'/jid;status=read(job/'status.json');binding=read(job/'binding.json')
    cp=read(job/'checkpoint.json') if (job/'checkpoint.json').exists() else None
    receipt = seal({'version':'jev_branch_receipt_v1','job_id':jid,'plan_digest':digest(p),'binding_digest':digest(binding),
                 'fork_digest':p['fork_digest'],'first':binding['first'],'continuation':p['continuation'],
                 'status':status,'checkpoint_digest':digest(cp) if cp else None,
                 'metrics':branch_metrics(task,p['config'],cp,status,binding['snapshot']) if cp else 'NOT_RUN',
                 'model_calls':0,'comparison_labels':'DEFERRED_TO_JN2_B'})
    validate_schema('packaging_branch_receipt_v1',receipt)
    return receipt


def run(root, *, resume=False, hook=None):
    from .episode import run_episode
    root=Path(root);p,task=validate_plan(root)
    with exclusive(root):
        if (root/'execution_receipt.json').exists():
            require(resume,'fork_already_started_use_resume')
            if (root/'mechanism_results.json').exists():
                validate_output(root);return read(root/'mechanism_results.json')
        else:
            write(root/'execution_receipt.json',{'version':VERSION,'plan_digest':digest(p),'budget_reserved':len(p['branch_order'])})
        stopped=False
        for jid in p['branch_order']:
            job=root/'branches'/jid;status=read(job/'status.json')
            if status['state']=='FINISHED':
                stopped=stopped or status['category'] in common.STOP_CATEGORIES
                continue
            if stopped:continue
            binding=read(job/'binding.json');cfg=p['config'];old=status['active_wall_s'];started=time.perf_counter()
            cp=read(job/'checkpoint.json') if (job/'checkpoint.json').exists() else None
            # A RUNNING entry without its durable first selection is ambiguous:
            # do not reset it and launch another suffix.
            require(status['state']!='RUNNING' or cp is not None,'fork_unknown_start_no_retry')
            def persist(value):
                nonlocal cp
                cp=value;write(job/'checkpoint.json',value)
                if value['pending_event']:
                    write(job/'stages'/value['pending_event']['decision_id']/(value['phase']+'.json'),value)
                status['active_wall_s']=old+time.perf_counter()-started;write(job/'status.json',status)
                if value['reason'] is None and (len(value['events'])>=p['watchdog']['max_events'] or status['active_wall_s']>=p['watchdog']['max_active_wall_s']):
                    raise common._BoundaryStop()
            try:
                if cp is None:
                    cp=bootstrap(binding,task,cfg,jid);persist(cp)
                status['state']='RUNNING';write(job/'status.json',status)
                ep=run_episode(task,continuation_factory(),cfg,job_id=jid,method=METHOD,resume=cp,
                               on_checkpoint=persist,hook=hook,training_fork=binding)
                cp=ep['checkpoint'];write(job/'episode.json',ep)
                status.update(state='FINISHED',category=termination_category(cp['reason'],cp['events']))
            except common._BoundaryStop:status.update(state='FINISHED',category='TECHNICAL_LIMIT')
            except KeyboardInterrupt:status.update(state='FINISHED',category='CANCELED',error={'type':'KeyboardInterrupt'})
            except Exception as exc:
                status.update(state='FINISHED',category='ERROR',error={'type':type(exc).__name__,'code':getattr(exc,'code','UNEXPECTED_ERROR'),'detail':str(exc)[:240]})
            status['active_wall_s']=old+time.perf_counter()-started;write(job/'status.json',status)
            if cp:
                write(job/'checkpoint.json',cp);write(job/'final_layout.json',cp['state']['placed_items'])
                for e in cp['events']+([cp['pending_event']] if cp['pending_event'] else []):
                    if e.get('decision_id'):write(job/'actions'/f"{e['decision_id']}.json",e)
            write(job/'branch_receipt.json',branch_receipt(root,jid,p,task))
            stopped=status['category'] in common.STOP_CATEGORIES
        receipts=[]
        for jid in p['branch_order']:
            job=root/'branches'/jid
            r=branch_receipt(root,jid,p,task);write(job/'branch_receipt.json',r);receipts.append(r)
        summary={'version':VERSION,'planned_suffixes':len(receipts),'started_suffixes':sum(r['status']['state']!='NOT_RUN' for r in receipts),
                 'branches':[{'job_id':r['job_id'],'intervention':r['first']['intervention'],'category':r['status']['category'],
                              'metrics':r['metrics']} for r in receipts], 'model_calls':0,'coverage_gaps':p['selection']['coverage_gaps'],
                 'JN2_B_total_budget':12,'consumed_A_slots':len(receipts),'research_benefit':'NOT_ESTABLISHED'}
        write(root/'mechanism_results.json',summary)
        validate_output(root)
        return summary


def validate_output(root):
    root=Path(root);p,task=validate_plan(root)
    actual_rows=[]
    for jid in p['branch_order']:
        job=root/'branches'/jid;binding=read(job/'binding.json');status=read(job/'status.json')
        receipt=branch_receipt(root,jid,p,task)
        require(read(job/'branch_receipt.json')==receipt,'fork_receipt_changed')
        actual_rows.append({'job_id':jid,'intervention':receipt['first']['intervention'],'category':status['category'],'metrics':receipt['metrics']})
        if not (job/'checkpoint.json').exists():
            require(status['category'] in ('NOT_RUN','ERROR','CANCELED'),'fork_missing_checkpoint');continue
        cp=read(job/'checkpoint.json');validate_branch_checkpoint(cp,task,p['config'],jid,binding)
        for path in sorted((job/'stages').glob('*/*.json')):
            stage=read(path);validate_branch_checkpoint(stage,task,p['config'],jid,binding)
            require(stage['events']==cp['events'][:len(stage['events'])],'fork_stage_prefix_changed')
            pending=stage['pending_event'];final=next((e for e in cp['events'] if e.get('decision_id')==pending['decision_id']),cp['pending_event'])
            require(final is not None and all(pending[k]==final[k] for k in ('before','bundle','context','selection','proposed_action')),'fork_stage_binding_changed')
            if pending['monitor']:require(pending['monitor']==final['monitor'],'fork_monitor_overwritten')
        if status['category'] not in common.STOP_CATEGORIES:
            require(status['category']==termination_category(cp['reason'],cp['events']),'fork_termination_changed')
        require(read(job/'final_layout.json')==cp['state']['placed_items'],'fork_layout_changed')
        for e in cp['events']+([cp['pending_event']] if cp['pending_event'] else []):
            if e.get('decision_id'):require(read(job/'actions'/f"{e['decision_id']}.json")==e,'fork_action_changed')
    summary=read(root/'mechanism_results.json')
    require(summary['branches']==actual_rows and summary['planned_suffixes']==len(p['branch_order']) and
            summary['started_suffixes']==sum(read(root/'branches'/jid/'status.json')['state']!='NOT_RUN' for jid in p['branch_order']) and
            summary['model_calls']==0 and summary['consumed_A_slots']==len(p['branch_order']),'fork_summary_changed')
    return {'status':'PASS','verification':'saved records only; no selector, generation, commit or PCT dispatch'}


def main():
    import argparse
    parser=argparse.ArgumentParser(description=__doc__);sub=parser.add_subparsers(dest='command',required=True)
    p=sub.add_parser('prepare');p.add_argument('--parent',required=True);p.add_argument('--output',required=True)
    p=sub.add_parser('run');p.add_argument('--output',required=True);p.add_argument('--resume',action='store_true')
    p=sub.add_parser('validate');p.add_argument('--output',required=True)
    a=parser.parse_args()
    if a.command=='prepare':value=prepare(a.parent,a.output)
    elif a.command=='run':value=run(a.output,resume=a.resume)
    else:value=validate_output(a.output)
    print({'status':'OK','command':a.command,'version':value.get('version',VERSION)})


if __name__=='__main__':main()
