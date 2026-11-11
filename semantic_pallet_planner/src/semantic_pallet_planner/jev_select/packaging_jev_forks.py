"""JM1-A1: receipt-bound independent starts and one forced public-engine step.

No sampling, continuation factory, model transport, or restart implementation.
References are repository-relative and pinned to archived bytes; a receipt is
identity evidence, never a grant of training/source/execution admission.
"""
from __future__ import annotations

import copy
import hashlib
from pathlib import Path

from .contracts import CandidateBundle, DecisionContext, JevSelectError, digest, validate_schema
from .ledger import read
from .packaging_versions import JM_FORK_VERSION, EXACT_VERSION

REPO = Path(__file__).resolve().parents[4]
SOURCE = 'FORCED_FROM_FROZEN_POOL'
STOP = 'JM_CONTINUATION_NOT_IMPLEMENTED'


def require(ok, code):
    if not ok:
        raise JevSelectError(code)


def seal(value):
    value['record_digest'] = digest({k: v for k, v in value.items() if k != 'record_digest'})
    return value


def check_seal(value):
    require(value['record_digest'] == digest({k: v for k, v in value.items() if k != 'record_digest'}),
            'jm_record_changed')


def _path(relative):
    p = (REPO / relative).resolve()
    require(not Path(relative).is_absolute() and p.is_relative_to(REPO), 'jm_evidence_path_escape')
    return p


def _load(ref):
    p = _path(ref['path'])
    require(hashlib.sha256(p.read_bytes()).hexdigest() == ref['sha256'], 'jm_saved_bytes_changed')
    value = read(p)
    pointer = ref['pointer']
    require(pointer == '' or pointer.startswith('/'), 'jm_invalid_pointer')
    for part in pointer.split('/')[1:]:
        key = part.replace('~1', '/').replace('~0', '~')
        value = value[int(key)] if isinstance(value, list) else value[key]
    return value


def _ref(path, pointer=''):
    p = _path(path)
    return {'path':path, 'sha256':hashlib.sha256(p.read_bytes()).hexdigest(), 'pointer':pointer}


def freeze_start(*, receipt_path, snapshot_path, snapshot_pointer, task_path,
                 evidence_scope='ARCHIVED_ONLY_NOT_EXECUTION_ADMISSION', task_receipt_path=None):
    """Consume already saved snapshot/task listed by a pinned files_sha256 receipt.

    For historical JN2 inputs snapshot_pointer is /value/snapshot. No historical
    candidates, placements, monitor results, or trajectories are reconstructed.
    """
    start = {'version':'jev_jm_fork_start_v1','evidence_scope':evidence_scope,
             'receipt':_ref(receipt_path),'task_receipt':_ref(task_receipt_path or receipt_path),'snapshot_ref':_ref(snapshot_path,snapshot_pointer),
             'task_ref':_ref(task_path),'snapshot':_load(_ref(snapshot_path,snapshot_pointer)),
             'task_digest':digest(_load(_ref(task_path)))}
    seal(start)
    validate_start(start)
    return copy.deepcopy(start)


def validate_start(start):
    validate_schema('jm_fork_start_v1', start); check_seal(start)
    # Each input must be enumerated in its own pinned parent manifest.
    for key, receipt_key in (('snapshot_ref','receipt'),('task_ref','task_receipt')):
        receipt = _load(start[receipt_key])
        parent = _path(start[receipt_key]['path']).parent
        ref = start[key]
        p = _path(ref['path'])
        require(p.is_relative_to(parent), 'jm_unlisted_evidence')
        require(receipt['files_sha256'].get(p.relative_to(parent).as_posix()) == ref['sha256'],
                'jm_unlisted_evidence')
    snapshot = _load(start['snapshot_ref']); task = _load(start['task_ref'])
    require(snapshot == start['snapshot'] and digest(task) == start['task_digest'] == snapshot['task_digest'],
            'jm_saved_start_changed')
    check_seal(snapshot)
    validate_schema('packaging_fork_snapshot_v1',snapshot)
    state = snapshot['state']; event = snapshot['event']; config = snapshot['parent_config']
    from semantic_pallet_planner.o4.buffer.buffer_state import invariant
    from semantic_pallet_planner.o4.extensions.e2.protocol import observation
    from .context import validate_context
    from .packaging_runtime import no_policy
    invariant(state)
    require(snapshot['source_group'] == task['source_group_id'] and
            event['context']['local_binding']['job_id'] == snapshot['parent_job_id'] and
            event['context']['local_binding']['decision_id'] == snapshot['decision_id'], 'jm_parent_identity_changed')
    require(task['partition'] == 'train' and config['version'] in ('jev_packaging_remote_v6', EXACT_VERSION),
            'jm_start_protocol_or_partition')
    require(config['selector'] in ('jev_no_memory',) and config.get('memory_mode','none') == 'none',
            'jm_start_requires_no_memory')
    require(config['stability_monitor']['enabled'] is True, 'jm_monitor_required')
    require(config['runtime_identity']['task_identity'] == digest(task), 'jm_task_identity')
    require(snapshot['cursor'] == state['arrival_count'] and
            state['arrived_ids'] == [x['item_id'] for x in task['items'][:snapshot['cursor']]] and
            snapshot['buffer'] == state['pending_items'] and snapshot['end_of_stream'] == state['end_of_stream'],
            'jm_arrival_or_buffer_changed')
    require(event['before'] == state and event['bundle'] == snapshot['pool'] and
            event['context']['display_mapping'] == snapshot['mapping'] and
            event['decision_id'] == snapshot['decision_id'], 'jm_frozen_decision_changed')
    req = observation(state,task['instruction_text'],task['regions'])
    require(req == event['observation'], 'jm_observation_changed')
    bundle = CandidateBundle.from_dict(snapshot['pool']); context = DecisionContext.from_dict(event['context'])
    no_policy(req); validate_context(context,req,bundle,config)
    require(context.data['model_state'].get('memories') == [], 'jm_memory_forbidden')
    pool = snapshot['pool']['selectable_candidates']; mapping = snapshot['mapping']
    require(len({c['candidate_id'] for c in pool}) == len(pool) == len(mapping), 'jm_pool_mapping_changed')
    for row in mapping.values():
        matches = [c for c in pool if c['candidate_id'] == row['candidate_id']]
        require(len(matches) == 1 and row['candidate_digest'] == digest(matches[0]), 'jm_mapping_candidate_changed')
    label = event['selection']['selected_display_id']
    require(label in mapping and mapping[label]['candidate_id'] == event['selection']['selected_candidate_id'],
            'jm_original_selection_changed')
    from semantic_pallet_planner.o4.extensions.e2.planning import action_for
    chosen = next(c for c in pool if c['candidate_id'] == mapping[label]['candidate_id'])
    require(event['proposed_action'] == action_for(req,snapshot['pool']['physical_candidates'],chosen),
            'jm_original_action_changed')
    return task, config


def _candidate(start, label):
    s = start['snapshot']
    require(label in s['mapping'], 'jm_action_not_in_frozen_pool')
    cid = s['mapping'][label]['candidate_id']
    return copy.deepcopy(next(c for c in s['pool']['selectable_candidates'] if c['candidate_id'] == cid))


def intervention(start, candidate):
    s = start['snapshot']; original = _candidate(start,s['event']['selection']['selected_display_id'])
    def exact(c):
        return {k:c[k] for k in ('pick_item_id','pose','oriented_size_mm')}
    if exact(candidate) == exact(original):
        return 'ORIGINAL_ACTION_REFERENCE'
    return 'SAME_BOX_DIFFERENT_POSE' if candidate['pick_item_id'] == original['pick_item_id'] else 'CROSS_BOX_SELECTION'


def bind_branch(start, *, branch_id, forced_display_id):
    _, config = validate_start(start)
    candidate = _candidate(start,forced_display_id)
    from semantic_pallet_planner.o4.extensions.e2.planning import action_for
    s = start['snapshot']
    value = seal({'version':JM_FORK_VERSION,'branch_id':branch_id,'start':copy.deepcopy(start),
        'start_digest':digest(start),'config_digest':digest(config),'policy_identity':copy.deepcopy(config['runtime_identity']),
        'forced_display_id':forced_display_id,'forced_candidate':candidate,
        'exact_action':action_for(s['event']['observation'],s['pool']['physical_candidates'],candidate),
        'intervention':intervention(start,candidate)})
    validate_schema('jm_fork_binding_v1',value)
    return value


def validate_binding(binding, task, config, job_id):
    validate_schema('jm_fork_binding_v1',binding); check_seal(binding)
    saved_task, saved_config = validate_start(binding['start'])
    require(task == saved_task and config == saved_config and job_id == binding['branch_id'], 'jm_execution_identity_changed')
    expected = bind_branch(binding['start'],branch_id=job_id,forced_display_id=binding['forced_display_id'])
    require(binding == expected, 'jm_binding_changed')


def bootstrap(binding, task, config, job_id):
    validate_binding(binding,task,config,job_id)
    require(binding['start']['evidence_scope'] == 'CONSTRUCTED_ONLY', 'jm_A1_constructed_only')
    from .selector import bind_decision, SelectionResult
    from .stability.monitor import seal_checkpoint
    s = binding['start']['snapshot']; e = copy.deepcopy(s['event'])
    did = f'{job_id}_D0000'
    context = bind_decision(DecisionContext.from_dict(e['context']),job_id,did,config=config)
    label = binding['forced_display_id']; candidate = binding['forced_candidate']
    selection = {'version':'jev_jm_forced_selection_v1','status':'singleton' if context.data['route']=='SINGLETON_BYPASS' else 'selected',
        'selected_display_id':label,'selected_candidate_id':candidate['candidate_id'],'source':SOURCE,
        'requested_model':None,'served_model':None,'probabilities':None,'confidence':None,'attempt_ids':[],
        'usage':None,'latency_s':None,'local_binding_digest':digest(context.data['local_binding']),
        'raw_response_digest':None,'error':None,'network_attempted':False,'error_stage':None,'error_code':None,
        'fork_binding_digest':digest(binding),'candidate_digest':digest(candidate),'config_digest':digest(config),
        'forced_action_count':1,'model_call_count':0}
    validate_schema('jm_forced_selection_v1',selection)
    e.update(event='STOP',decision_id=did,before=copy.deepcopy(s['state']),after=copy.deepcopy(s['state']),
        context=context.data,selection=SelectionResult.from_dict(selection).data,proposed_action=copy.deepcopy(binding['exact_action']),
        action=None,monitor=None,monitor_result_reuses=0,reason=None,error=None,reference_after=None,business_after=None,
        timings={'public_business_s':0.,'selection_s':0.,'physical_commit_s':0.,'independent_evaluation_s':0.,'checkpoint_io_s':0.})
    cp = {'version':'jev_checkpoint_'+config['version'].rsplit('_',1)[1], 'job_id':job_id,'method':config['selector'],
        'task_digest':digest(task),'config_digest':digest(config),'state':copy.deepcopy(s['state']),
        'cursor':s['cursor'],'decision':0,'events':[],'reason':None,'phase':'SELECTED','pending_event':e,
        'runtime_identity':copy.deepcopy(config['runtime_identity'])}
    seal_checkpoint(cp); validate_schema('checkpoint_'+config['version'].rsplit('_',1)[1],cp)
    return cp


def validate_forced_selection(selected, context, candidate, config):
    validate_schema('jm_forced_selection_v1',selected)
    require(config['stability_monitor']['enabled'] is True and selected['config_digest'] == digest(config) and
            selected['candidate_digest'] == digest(candidate) and selected['selected_candidate_id'] == candidate['candidate_id'] and
            selected['local_binding_digest'] == digest(context.data['local_binding']), 'jm_forced_selection_changed')


class UnimplementedContinuation:
    """A2 supplies a separately versioned no-memory selector/ledger contract."""
    def select(self, *args, **kwargs):
        raise JevSelectError(STOP)


def run_forced_first(binding, *, on_checkpoint):
    """One constructed first step; persistence callback required before monitoring.

    Full resume/repeated-slot support is intentionally rejected by the shared
    route until A3. This entry point does not claim cross-process exactly-once.
    """
    require(callable(on_checkpoint), 'jm_persistence_required')
    task, config = validate_start(binding['start'])
    from .episode import run_episode
    return run_episode(task,UnimplementedContinuation(),config,job_id=binding['branch_id'],
                       method=config['selector'],training_fork=binding,on_checkpoint=on_checkpoint)
