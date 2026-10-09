"""Selectors receive public request only; tie-break by display label, never real ID."""
from ..evaluation.policy_v2 import evaluate, optimal_set
from .instruction_parser_v2 import parse_instruction


def execute_policy(request, policy):
    evaluations = [evaluate(request, c, policy, request['container']) for c in request['candidates']]
    best = optimal_set(evaluations)
    if not best['equivalent_indices']:
        return None
    return min((request['candidates'][i] for i in best['equivalent_indices']),
               key=lambda c: (-c['geometry_score'], c['display_label']))['display_label']


def geometry(request):
    return min(request['candidates'], key=lambda c: (-c['geometry_score'], c['display_label']))['display_label'] if request['candidates'] else None


FIXED_POLICY = {
    'schema_version': 'pallet_policy_v2_pilot',
    'hard_constraints': [
        {'type': 'fragile_load_limit', 'selector': {'fragile': True}, 'threshold_kg': 1.},
        {'type': 'forbidden_contact', 'left': {'product_category': 'electronics'}, 'right': {'weight_class': 'heavy'}}],
    'soft_priorities': [{'priority': 1, 'metric': 'heavy_low'}, {'priority': 2, 'metric': 'heavy_center'}]}


def fixed_attribute(request):
    # If the fixed universal policy has no feasible choice, still propose its least
    # violating action. Its fixed policy is not the current task's hidden truth.
    result = execute_policy(request, FIXED_POLICY)
    if result is not None:
        return result
    ranked = [(evaluate(request, c, FIXED_POLICY, request['container']), c) for c in request['candidates']]
    if not ranked:
        return None
    return min(ranked, key=lambda pair: (pair[0]['post_business_violation_count'],
               *[-(q if q is not None else 0) for q in pair[0]['soft_quality']],
               -pair[1]['geometry_score'], pair[1]['display_label']))[1]['display_label']


def public_parser(request):
    return execute_policy(request, parse_instruction(request['instruction_text']))
