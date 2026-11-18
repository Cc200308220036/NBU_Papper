"""Bounded same-box native-ranking comparisons. No remote calls or memory writes."""
from copy import deepcopy
from itertools import product
from pathlib import Path
import math

from .contracts import JevSelectError, digest, canonical
from .ledger import read, write
from .diagnostics import violation_measure, outcome_dominates


def same_box_ranking(event):
    mapping = event['context']['display_mapping']
    selected = event['selection']['selected_display_id']
    probabilities = event['selection'].get('probabilities')
    if not probabilities or set(probabilities) != set(mapping):
        raise JevSelectError('native_probabilities_missing_or_unbound')
    if any(type(p) not in (float, int) or not math.isfinite(p) or not 0 <= p <= 1
           for p in probabilities.values()):
        raise JevSelectError('invalid_native_probability')
    pick = mapping[selected]['pick_item_id']
    pool = {c['candidate_id']:c for c in event['bundle']['physical_candidates']}
    labels = sorted((k for k,v in mapping.items() if v['pick_item_id']==pick),
                    key=lambda k:(-probabilities[k], k != selected, k))
    if labels[0] != selected:
        raise JevSelectError('actual_choice_not_first_same_box_rank')
    return [{'rank':i+1, 'display_id':k, 'probability':probabilities[k],
             'tied_probability':sum(probabilities[j]==probabilities[k] for j in labels)>1,
             'candidate':pool[mapping[k]['candidate_id']]} for i,k in enumerate(labels)]


def segregation_feedback(event):
    """Replace face contact with forbidden co-pallet pairs in a separate audit view."""
    kept = [deepcopy(i) for i in event['business_after']['instances'] if i['kind']!='forbidden_contact']
    state = event['after']
    categories = {b['item_id']:state['attributes'][b['item_id']]['cargo_category']
                  for b in state['placed_items']}
    foods = sorted(k for k,v in categories.items() if v=='food')
    cleaners = sorted(k for k,v in categories.items() if v=='household_cleaner')
    for a,b in product(foods, cleaners):
        ids = sorted([a,b])
        kept.append({'identity':canonical(['forbidden_co_pallet','food_cleaner_segregation',ids]),
                     'kind':'forbidden_co_pallet','rule_id':'food_cleaner_segregation',
                     'object_ids':ids,'severity':None})
    return {'instances':kept}


def branch_metrics(ep, *, segregation):
    steps = [e for e in ep['events'] if e['event']=='PLACE']
    if not steps:
        raise JevSelectError('candidate_branch_has_no_placement')
    feedbacks = [segregation_feedback(e) if segregation else e['business_after'] for e in steps]
    return {'placed_items':ep['summary']['placed_items'],
            'planned_items':ep['summary']['planned_items'],
            'termination_reason':ep['summary']['termination_reason'],
            'final_violations':violation_measure(feedbacks[-1]),
            'trajectory_violation_instance_steps':sum(len(f['instances']) for f in feedbacks),
            'ever_unique_violation_instances':len({i['identity'] for f in feedbacks for i in f['instances']}),
            'per_step_instances':[len(f['instances']) for f in feedbacks]}


def compare_same_box(experiment, output, *, job_id='J0000', decision_id='J0000_D0000', top_k=3):
    from .dataset_j4 import offline_dataset_guard, verify_seal
    from .experiment import _new_output, file_manifest
    from .config import config_for_memory
    from .memory_store import empty_snapshot
    from .selector import LocalSelector, result
    from .episode import run_episode, semantic_record
    if type(top_k) is not int or not 2 <= top_k <= 3:
        raise JevSelectError('same_box_branch_budget_must_be_2_or_3')
    root = Path(experiment).resolve()
    with offline_dataset_guard() as guards:
        seal = verify_seal(root)
        if seal['status'] != 'PASS':
            raise JevSelectError('experiment_seal_not_verified')
        source_before = file_manifest(root)
        account = root.parent/'JEV_J4_GENERATION_ACCOUNTING_V1'
        account_before = file_manifest(account)
        historical = read(root/'episodes'/f'{job_id}.json')
        if historical['summary']['partition'] != 'train':
            raise JevSelectError('case_analysis_training_only')
        events = [e for e in historical['events'] if e['event']=='PLACE']
        indices = [i for i,e in enumerate(events) if e['decision_id']==decision_id]
        if len(indices)!=1:
            raise JevSelectError('unknown_same_box_fork_decision')
        fork = indices[0]; event = events[fork]
        ranking = same_box_ranking(event)[:top_k]
        if len(ranking)<2:
            raise JevSelectError('not_enough_same_box_candidates')
        task = next(t for t in read(root/'plan/private/input_snapshot.json')['tasks']
                    if t['task_id']==historical['summary']['task_id'])
        out = _new_output(output); out.mkdir(parents=True)
        registration = {'version':'same_box_native_rank_branch_v1','source_experiment':root.name,
            'source_episode_digest':digest(historical),'task_digest':digest(task),
            'fork_decision':decision_id,'saved_prefix_length':fork,'rankings':ranking,
            'ranking_rule':'saved native probabilities restricted to the actual selected box; descending probability, selected action first on ties, then display ID; no conditional renormalization',
            'continuation_policy':'shared_geometry','branch_budget':len(ranking),
            'semantics':'new audit view replaces forbidden face contact with food-cleaner forbidden co-pallet pairs; all other saved rules remain; old engine feedback retained separately',
            'hard_constraint_note':'diagnostic rollouts measure violations; incompatible boxes are not filtered or routed to a second pallet; no deployment claim',
            'stop_rule':'natural full-order completion or physical pool exhaustion; never stop on favorable scores',
            'remote_calls':0,'memory_writes':0,'source_seal':seal}
        write(out/'registration.json',registration)
        memory=empty_snapshot()
        cfg=config_for_memory(read(root/'plan/config.snapshot.json'),'shared_geometry',memory)

        class ForcedPrefix:
            def __init__(self,ids): self.ids=ids;self.follow=LocalSelector('shared_geometry')
            def bind_public(self,*args):self.follow.bind_public(*args)
            def select(self,context,*,decision_id):
                index=int(decision_id.rsplit('_D',1)[1])
                if index>=len(self.ids):return self.follow.select(context,decision_id=decision_id)
                matches=[k for k,v in context.data['display_mapping'].items() if v['candidate_id']==self.ids[index]]
                if len(matches)!=1:raise JevSelectError('forced_same_box_candidate_unavailable')
                return result(context,status='selected',source='local_baseline',label=matches[0])

        rows=[]
        for rank in ranking:
            ids=[e['selection']['selected_candidate_id'] for e in events[:fork]]+[rank['candidate']['candidate_id']]
            ep=run_episode(deepcopy(task),ForcedPrefix(ids),cfg,job_id=f"SAME_BOX_R{rank['rank']}",
                           method='shared_geometry',memory_snapshot=memory)
            if not ep.get('summary') or ep['summary']['termination_reason'] not in ('ALL_ITEMS_PLACED','STOP_NO_PHYSICAL_CANDIDATE'):
                raise JevSelectError('same_box_branch_execution_failed')
            observed=[e for e in ep['events'] if e['event']=='PLACE']
            for old,new in zip(events[:fork+1],observed[:fork+1]):
                if digest(old['before'])!=digest(new['before']):
                    raise JevSelectError('same_box_prefix_state_mismatch')
            if observed[fork]['selection']['selected_candidate_id']!=ids[-1]:
                raise JevSelectError('same_box_fork_action_mismatch')
            row={'rank':rank['rank'],'display_id':rank['display_id'],'native_probability':rank['probability'],
                 'candidate':rank['candidate'],'legacy_face_contact':branch_metrics(ep,segregation=False),
                 **branch_metrics(ep,segregation=True)}
            row['dominates_rank1']=False if not rows else outcome_dominates(row,rows[0])
            rows.append(row)
            write(out/'branches'/f"rank_{rank['rank']}.json",semantic_record(ep))
            write(out/'audit_feedback'/f"rank_{rank['rank']}.json",[segregation_feedback(e) for e in observed])
        report={'version':'same_box_native_rank_comparison_v1','registration':registration,
                'rows':rows,'historical_reinterpreted':branch_metrics(historical,segregation=True),
                'model_api_calls':0,'local_rollouts':len(rows),'guards':dict(guards),
                'limitations':'Same-box ranking interventions under a fixed local geometry continuation, not alternative Jev continuations or verified model probabilities. Old future actions/probabilities are not replayed after the fork. Single source; no activation or global optimum.',
                'decision':'IMPROVEMENT_FOUND' if any(r['dominates_rank1'] for r in rows) else 'NO_DOMINATING_ALTERNATIVE_FOUND'}
        if file_manifest(root)!=source_before or file_manifest(account)!=account_before:
            raise JevSelectError('same_box_analysis_changed_history_or_account')
        write(out/'comparison.json',report)
        (out/'source_snapshot').mkdir()
        (out/'source_snapshot/candidate_branch.py').write_text(Path(__file__).read_text())
        write(out/'delivery_manifest.json',file_manifest(out))
        return report
