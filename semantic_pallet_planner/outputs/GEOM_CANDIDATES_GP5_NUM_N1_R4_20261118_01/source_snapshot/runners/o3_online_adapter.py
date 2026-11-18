"""Public O3 request and deterministic submit barrier for online episodes."""
from __future__ import annotations

import copy
import random

from ..evaluation.attribute_metrics_v2 import public_relations
from ..evaluation.policy_v2 import evaluate, optimal_set
from ..planner.scoring import geometry_score
from ..protocol import state_hash
from ..selectors.instruction_parser_o1b import resolved_public_policy
from ..vlm.pilot_protocol_v2 import digest, scan_public


def public_request(state, candidates, instruction, *, seed=20261015):
    """Only Cxx and reproducible public facts cross the selector boundary."""
    if len(state['available_items']) != 1:
        raise ValueError('O3 requires buffer_size=1')
    physical_hash = state_hash(state['container'], state)
    if len(candidates) > 16:
        raise ValueError('Top-K exceeds frozen K=16')
    ordered = list(candidates)
    random.Random(seed ^ int(physical_hash[:16], 16)).shuffle(ordered)
    visible, mapping = [], {}
    for index, candidate in enumerate(ordered, 1):
        label = f'C{index:02d}'
        fields = ('pick_item_id', 'pose', 'oriented_size_mm', 'support', 'load',
                  'resulting_geometry', 'geometry_score_components')
        public = {key: copy.deepcopy(candidate[key]) for key in fields}
        public.update(display_label=label, geometry_score=geometry_score(candidate),
                      public_relations=public_relations(state, candidate))
        visible.append(public)
        mapping[label] = candidate
    request = {
        'schema_version': 'pallet_request_v2_pilot',
        'request_id': state['request_id'],
        'state_hash': physical_hash,
        'policy_digest': digest({'grammar': 'o1b_instruction_1', 'instruction_text': instruction}),
        'instruction_text': instruction,
        'container': copy.deepcopy(state['container']),
        'placed_items': copy.deepcopy(state['placed_items']),
        'available_items': copy.deepcopy(state['available_items']),
        'candidates': visible,
        'buffer_size': 1,
    }
    private_ids = [c['candidate_id'] for c in ordered]
    scan = scan_public(request, private_ids)
    if scan['status'] != 'PASS':
        raise ValueError('O3 public request leakage: ' + str(scan['hits']))
    return request, mapping, scan


def candidate_diagnostics(request, truth_policy):
    public_policy = resolved_public_policy(request['instruction_text'], request)
    public = [evaluate(request, c, public_policy, request['container']) for c in request['candidates']]
    truth = [evaluate(request, c, truth_policy, request['container']) for c in request['candidates']]
    return public, truth, optimal_set(truth)


def screen(request, proposal, public_evaluations):
    labels = {c['display_label']: i for i, c in enumerate(request['candidates'])}
    if proposal is None:
        return None, False, 'selector_abstain'
    if proposal not in labels:
        return None, False, 'invalid_response'
    value = public_evaluations[labels[proposal]]
    # Existing violations stay separately visible; an unrelated action is not
    # blamed for them, but a worsened existing load is still blocked.
    blocked = bool(value['new_violation_instances'] or value['worsened_existing_violation_instances'])
    return (None, True, 'screen_abstain') if blocked else (proposal, False, None)
