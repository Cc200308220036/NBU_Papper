"""Public-state diagnostics from P0 snapshots; no branch or order execution."""
from collections import Counter
from pathlib import Path
from semantic_pallet_planner.o4.common import read, write
from semantic_pallet_planner.o4.extensions.e2.runtime import evaluate_state
from semantic_pallet_planner.o4.extensions.e5.layout_v2.quality import bounds
from semantic_pallet_planner.planner.constraints import rectangle_union_area

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
P0 = ROOT/'semantic_pallet_planner/outputs/EXP_O4_E5_LAYOUT_V2_P0_20261027_01'
rows = []
for path in sorted((P0/'cases').glob('rollback_*.json')):
    case = read(path); state = case['public_state']; req = case['request']; ast = case['ast']
    evaluated = evaluate_state(req['placed_objects'], ast, req['regions'], pending_objects=req['available_objects'],
                               end_of_stream=req['buffer_context']['end_of_stream'])
    boxes = state['placed_items']; container = state['container']
    floor_area = rectangle_union_area([bounds(o)[:4] for o in boxes if bounds(o)[4] == 0])
    capacity = []
    for obj in boxes:
        identifier = obj['item_id']; business = evaluated['limits_kg'].get(identifier)
        # This is a per-object upper bound; it is not an additive guarantee for
        # arbitrary multi-support arrangements or a future capacity prediction.
        capacity.append({'object_id': identifier, 'top_z_mm': bounds(obj)[5],
                         'business_top_limit_kg': business, 'current_top_load_kg': evaluated['loads_kg'][identifier],
                         'business_residual_kg': None if business is None else max(0., business-evaluated['loads_kg'][identifier]),
                         'scope': 'per_object_load_bound_not_business_usable_support_area'})
    rows.append({'job_id': case['job_id'], 'event_index': case['event_index'], 'event': case['event'],
                 'floor_occupied_union_mm2': floor_area, 'floor_free_area_mm2': container['length_mm']*container['width_mm']-floor_area,
                 'top_load_bounds': capacity, 'visible_pending': [{'id': o['object_id'], 'mass_kg': o['mass_kg'], 'dimensions_mm': o['dimensions_mm']} for o in req['available_objects']],
                 'sampled_pools': [{'pick_item_id': g['pick_item_id'], 'counts': g['counts'],
                     'floor_physical': sum(r['candidate']['pose']['z_base_mm'] == 0 for r in g['rows']),
                     'upper_physical': sum(r['candidate']['pose']['z_base_mm'] > 0 for r in g['rows']),
                     'floor_business_allowed': sum(r['business_allowed'] and r['candidate']['pose']['z_base_mm'] == 0 for r in g['rows']),
                     'upper_business_allowed': sum(r['business_allowed'] and r['candidate']['pose']['z_base_mm'] > 0 for r in g['rows']),
                     'rejection_instances': dict(Counter(v.split(':')[0] for r in g['rows'] for v in r['business_rejection_codes']))} for g in case['groups']],
                 'global_infeasibility': 'NOT_PROVEN', 'early_layout_causal_effect': 'NOT_PROVEN_WITHOUT_BRANCH_CONTINUATION'})
write(HERE/'p0_support_and_floor_diagnostics.json', rows)
for row in rows:
    if row['event'] == 'STOP': print(row['job_id'], row['floor_free_area_mm2'], row['sampled_pools'])
