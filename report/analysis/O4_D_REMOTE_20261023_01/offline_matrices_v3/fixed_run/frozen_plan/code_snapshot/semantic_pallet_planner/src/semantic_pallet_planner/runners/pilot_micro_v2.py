"""Hand-calculated microcases. Expected numbers are constants, not evaluator outputs."""
import copy

CONTAINER = {'length_mm': 1200, 'width_mm': 1000, 'max_height_mm': 850, 'max_payload_kg': 1000}


def item(i, mass=6., fragile=False, heavy=False, category='general', size=(200, 200, 100)):
    return {'item_id': i, 'geometry_id': 'micro', 'dimensions_mm': dict(zip(('length', 'width', 'height'), size)),
            'mass_kg': mass, 'weight_class': 'heavy' if heavy else 'medium', 'material': 'Cardboard',
            'fragile': fragile, 'stackable': True, 'top_load_limit_kg_synthetic': 100., 'product_category': category}


def placed(it, x=0., y=0., z=0.):
    p = copy.deepcopy(it)
    p.update(pose={'x_mm': x, 'y_mm': y, 'z_base_mm': z, 'yaw_deg': 0},
             oriented_size_mm=list(it['dimensions_mm'].values()), supported_load_kg=999., support_fractions=[])
    return p


def candidate(it, x=0., y=0., z=0.):
    return {'pick_item_id': it['item_id'], 'pose': {'x_mm': x, 'y_mm': y, 'z_base_mm': z, 'yaw_deg': 0},
            'oriented_size_mm': list(it['dimensions_mm'].values())}


def policy(limit=1., order=('heavy_low', 'heavy_center'), contact=False):
    hard = [] if limit is None else [{'type': 'fragile_load_limit', 'selector': {'fragile': True}, 'threshold_kg': limit}]
    if contact:
        hard.append({'type': 'forbidden_contact', 'left': {'product_category': 'electronics'}, 'right': {'weight_class': 'heavy'}})
    return {'schema_version': 'pallet_policy_v2_pilot', 'hard_constraints': hard,
            'soft_priorities': [{'priority': i+1, 'metric': m} for i, m in enumerate(order)]}


def microcases():
    a = placed(item('A', mass=4, fragile=True))
    b = item('B', heavy=True)
    out = []
    def add(name, ps, current, candidates, po, expected, note):
        out.append({'id': name, 'container': CONTAINER, 'case': {'placed_items': ps, 'available_items': [current]},
                    'candidates': candidates, 'policy': po, 'expected': expected, 'hand_calculation': note})
    add('M01_direct_fragile_load', [a], b, [candidate(b, z=100)], policy(),
        {'after_load_A': 6., 'added_load': 6., 'new_count': 1, 'post_count': 1}, 'B mass6 -> A6; physical capacity100, business limit1.')
    middle = placed(item('M', mass=4), z=100)
    add('M02_indirect_load', [a, middle], b, [candidate(b, z=200)], policy(),
        {'before_load_A': 4., 'after_load_A': 10., 'added_load': 6., 'new_count': 0, 'post_count': 1, 'worsened_count': 1}, 'A already carries M4; new B6 -> M6 -> A +6; same violated instance stays one.')
    counter = placed(item('counter', mass=40))
    heavy = item('B', mass=10, heavy=True)
    add('M03_heavy_vs_stack_com', [counter], heavy, [candidate(heavy, x=400)], policy(None),
        {'heavy_distance': 400., 'stack_com_x': 80.}, '(40*0+10*400)/50=80; target heavy distance400.')
    elec = placed(item('E', category='electronics'))
    left = placed(item('L', heavy=True), x=-200)
    right = placed(item('R', heavy=True), x=200)
    fresh = item('N')
    add('M04_two_forbidden_pairs', [elec, left, right], fresh, [candidate(fresh, y=400)], policy(None, contact=True),
        {'post_count': 2, 'new_count': 0}, 'E-L and E-R two unique unordered direct face pairs; both already present.')
    add('M05_equivalent_optima', [], b, [candidate(b, x=400), candidate(b, x=-400)], policy(None),
        {'equivalent_indices': [0, 1]}, 'Both z0, distance400; no geometry tie-break removes semantic equivalence.')
    add('M06_no_target', [], fresh, [candidate(fresh, x=400)], policy(),
        {'hard_applicable': False, 'soft_quality': [None, None]}, 'No fragile or heavy object: metrics N/A, never score1.')
    add('M07_old_violation_unrelated_step', [a, middle], fresh, [candidate(fresh, x=400)], policy(),
        {'before_load_A': 4., 'after_load_A': 4., 'added_load': 0., 'new_count': 0, 'post_count': 1, 'worsened_count': 0}, 'Prior overload4>1 persists; unrelated ground placement creates no new instance.')
    add('M08_candidate_set_no_business_solution', [a], b, [candidate(b, z=100)], policy(),
        {'feasible_indices': [], 'equivalent_indices': []}, 'Sole declared candidate places6kg on protected A; candidate-space infeasible, not proof of continuous infeasibility.')
    support = placed(item('S', mass=2, size=(200, 200, 200)))
    cs = [candidate(b, x=400), candidate(b, z=200)]
    add('M09_low_then_center', [support], b, cs, policy(None),
        {'equivalent_indices': [0]}, 'Low-first selects z0 at distance400 instead of z200 distance0.')
    add('M10_center_then_low', [support], b, cs, policy(None, order=('heavy_center', 'heavy_low')),
        {'equivalent_indices': [1]}, 'Center-first selects distance0 at z200; same physical set as M09.')
    support2 = placed(item('S2', mass=4), x=100)
    a2 = placed(item('A', mass=4, fragile=True), x=-100)
    wide = item('W', size=(400, 200, 100))
    add('M11_multi_support_split', [a2, support2], wide, [candidate(wide, z=100)], policy(),
        {'after_load_A': 3., 'added_load': 3., 'post_count': 1}, 'Equal contact areas:6kg/2=3kg each; A3>1.')
    add('M12_exact_business_threshold', [a], b, [candidate(b, z=100)], policy(6.),
        {'after_load_A': 6., 'post_count': 0, 'new_count': 0, 'feasible_indices': [0]}, 'Business limit6 exactly admits load6; physical limit100 remains separate.')
    diagonal = placed(item('H', heavy=True), x=200, y=200)
    add('M13_edge_contact_excluded', [elec, diagonal], fresh, [candidate(fresh, x=-400)], policy(None, contact=True),
        {'post_count': 0}, 'E and H only meet on a vertical edge; face overlap area=0, no prohibited pair.')
    return out


def verify_micro(m):
    from ..evaluation.attribute_metrics_v2 import transition, public_relations
    from ..evaluation.policy_v2 import evaluate, optimal_set
    es = [evaluate(m['case'], c, m['policy'], m['container']) for c in m['candidates']]
    e = es[0]
    before, after = transition(m['case'], m['candidates'][0])
    relations = public_relations(m['case'], m['candidates'][0])
    best = optimal_set(es)
    actual = {'new_count': e['new_business_violation_count'], 'post_count': e['post_business_violation_count'],
              'worsened_count': e['worsened_existing_violation_count'], 'hard_applicable': e['business_hard_applicable'], 'soft_quality': e['soft_quality'],
              'heavy_distance': relations['after']['heavy_center_distance_mm'],
              'added_load': relations['delta']['fragile_added_load_kg'], **best}
    for phase, state in [('before', before), ('after', after)]:
        for p in state:
            actual[f"{phase}_load_{p['item_id']}"] = p['supported_load_kg']
    actual['stack_com_x'] = sum(p['mass_kg']*p['pose']['x_mm'] for p in after)/sum(p['mass_kg'] for p in after)
    failures = []
    for field, expected in m['expected'].items():
        value = actual[field]
        equal = abs(value-expected)<1e-9 if isinstance(expected, (int, float)) and not isinstance(expected, bool) else value==expected
        if not equal:
            failures.append({'field': field, 'expected': expected, 'actual': value})
    return {'id': m['id'], 'status': 'PASS' if not failures else 'FAIL', 'expected': m['expected'], 'checked_actual': {k: actual[k] for k in m['expected']}, 'failures': failures}
