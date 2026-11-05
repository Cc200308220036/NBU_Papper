import copy
import json
from pathlib import Path
import pytest
from semantic_pallet_planner.o4.common import O4Error, read, digest
from semantic_pallet_planner.o4.extensions.e5.layout_v2.quality import bounds, union_length, fragmentation, measure
from semantic_pallet_planner.o4.extensions.e5.layout_v2.config import DEFAULT, validate
from semantic_pallet_planner.o4.extensions.e5.layout_v2.planning import choose, select_layout, clear_cache, quality_key
from semantic_pallet_planner.o4.extensions.e5.layout_v2.candidates import generate, key
from semantic_pallet_planner.o4.extensions.e5.planning import choose as dispatch
from semantic_pallet_planner.o4.extensions.e2.planning import choose as original_choose, commit, action_for
from semantic_pallet_planner.o4.extensions.e2.protocol import observation
from semantic_pallet_planner.o4.extensions.e5.backends import LocalCompiler
from semantic_pallet_planner.o4.extensions.e5.data import construct_tasks
from semantic_pallet_planner.o4.extensions.e5.episode import episode, verify_episode, stable
from semantic_pallet_planner.config import WORKSPACE

P0 = WORKSPACE/'semantic_pallet_planner/outputs/EXP_O4_E5_LAYOUT_V2_P0_20261027_01'


def cfg(retention=True, ranking=True):
    config = read(P0/'config.snapshot.json'); config['o4_e5_layout'] = copy.deepcopy(DEFAULT)
    config['o4_e5_layout'].update(candidate_retention=retention, ranking=ranking)
    return config


def case(name): return read(P0/'cases'/f'{name}.json')


def shape(x, y, dx=100, dy=100, z=0, height=100, yaw=0, identifier='A'):
    return {'item_id': identifier, 'pose': {'x_mm': x, 'y_mm': y, 'z_base_mm': z, 'yaw_deg': yaw},
            'oriented_size_mm': [dx, dy, height], 'support': {'support_item_ids': []}}


def test_c01_default_dispatch_and_closed_version():
    c = case('original_second'); base = read(P0/'config.snapshot.json')
    a = dispatch(c['public_state'], c['request'], c['ast'], base, 'single')
    b = original_choose(c['public_state'], c['request'], c['ast'], base, 'single')
    assert stable(list(a[:2])) == stable(list(b[:2])) and a[3] == b[3]
    bad = cfg(); bad['o4_e5_layout']['version'] = 'unknown'
    with pytest.raises(O4Error, match='invalid_layout_config'): dispatch(c['public_state'], c['request'], c['ast'], bad, 'single')
    for k, value in [('ranking', 1), ('search_depth', True), ('per_object_top_k', 32), ('probe_quality', True)]:
        bad = copy.deepcopy(DEFAULT); bad[k] = value
        with pytest.raises(O4Error): validate(bad)


def test_c02_contact_coordinates_and_height_separation():
    assert bounds(shape(0, 0, 190, 600, yaw=90)) == (-95, 95, -300, 300, 0, 100)
    state = {'container': {'length_mm': 1000, 'width_mm': 1000}, 'placed_items': [shape(0, 0)]}
    q = measure(state, shape(100, 0))
    assert q['side_contact_length_mm'] == q['aligned_contact_length_mm'] == 100
    assert measure(state, shape(100, 0, z=100))['side_contact_length_mm'] == 0
    assert measure(state, shape(100, 100))['side_contact_length_mm'] == 0
    assert measure(state, shape(110, 0))['gaps'][0]['gap_mm'] == 10


def test_c03_l0_original_alignment_is_retained_from_same_pool():
    c = case('original_second'); old_pool = {key(r['candidate']) for r in c['groups'][0]['rows']}
    candidates, audit = generate(c['public_state'], 'item_02', c['request']['regions'], cfg())
    assert len(candidates) <= 16 and {key(x) for x in candidates} <= old_pool
    assert any(measure(c['public_state'], x)['aligned_contact_length_mm'] > 0 for x in candidates)
    assert any(key(x)[:4] in ((-105, -240, 0, 0), (105, -240, 0, 0)) for x in candidates)
    assert 'coverage_lost' in audit and len(audit['retention']) == len(candidates)


def test_c04_l0_micro_probe_difference_cannot_defeat_contact():
    c = case('withdrawn_v1_second'); candidates = c['saved_groups'][0]['candidate_snapshot']
    selected, trace, _ = select_layout(c['public_state'], c['request'], c['ast'], candidates, cfg(False))
    assert measure(c['public_state'], selected)['side_contact_length_mm'] > 0
    assert key(selected)[:4] != (0, 305, 0, 90)
    assert trace['remaining_capacity_prediction'] == 'NOT_IMPLEMENTED'


def test_c06_c09_exact_union_and_fragmentation_are_soft_descriptors():
    assert union_length([(0, 100), (50, 150), (160, 200)]) == 190
    container = {'length_mm': 1000, 'width_mm': 1000}
    center = fragmentation([(-100, 100, -500, 500)], container)
    edge = fragmentation([(-500, -300, -500, 500)], container)
    assert center['occupied_union_area_mm2'] == edge['occupied_union_area_mm2'] == 200000
    assert center['extra_free_runs'] > edge['extra_free_runs']
    duplicate = fragmentation([(-100, 100, -500, 500)]*2, container)
    assert duplicate == center
    assert fragmentation([], container)['extra_free_runs'] == 0
    state = {'container': container, 'placed_items': [shape(0, 0)]}
    # A positive descriptor does not become a feasibility veto: a 40mm box
    # geometrically fits a 50mm slit between two 100mm boxes.
    assert bounds(shape(125, 0, dx=40))[0] >= 100
    assert bounds(shape(125, 0, dx=40))[1] <= 150


def test_c07_mirror_geometry_quality_and_empty_contact():
    state = {'container': {'length_mm': 1000, 'width_mm': 1000}, 'placed_items': [shape(-100, 0)]}
    mirror = copy.deepcopy(state); mirror['placed_items'][0]['pose']['x_mm'] = 100
    a = measure(state, shape(0, 0)); b = measure(mirror, shape(0, 0))
    assert quality_key(a) == quality_key(b)
    assert measure({**state, 'placed_items': []}, shape(0, 0))['side_contact_ratio'] == 0


def test_c10_c11_hidden_data_cache_isolation_and_stale_action():
    c = case('original_second'); state = c['public_state']; before = digest(state)
    hidden = copy.deepcopy(state); hidden['future_boxes'] = ['should_never_be_read']; hidden['reference_policy'] = {'bad': True}
    a = choose(state, c['request'], c['ast'], cfg(), 'single')
    b = choose(hidden, c['request'], c['ast'], cfg(), 'single')
    assert stable(list(a)) == stable(list(b)) and digest(state) == before
    a[1][0]['candidates'].clear()
    assert choose(state, c['request'], c['ast'], cfg(), 'single')[1][0]['candidates']
    legacy = choose(state, c['request'], c['ast'], cfg(False, False), 'single')
    assert legacy[1][0]['generation']['version'].startswith('o4_e2_')
    assert b[1][0]['generation']['version'].startswith('o4_e5_layout_v2')
    candidates = [x for g in b[1] for x in g['candidates']]
    action = action_for(c['request'], candidates, b[0]); action['candidate_set_digest'] = 'stale'
    with pytest.raises(O4Error, match='invalid_binding'):
        commit(state, c['request']['regions'], c['request'], {'schema_version': 'o4_e2_response_v1',
               **{k: c['request'][k] for k in ('request_id','state_hash','observation_digest','instruction_digest')}, 'policy_ast': c['ast']}, candidates, action)


@pytest.mark.parametrize('method', ['single', 'buffer_fifo', 'buffer_heuristic', 'buffer_search'])
@pytest.mark.parametrize('index', [0, 4])
def test_c05_c08_c11_positive_and_contradictory_orders(method, index):
    task = construct_tasks()[index]; config = cfg()
    result = episode(task, 'public_parser', method, config, LocalCompiler('public_parser'), 'guard')
    assert result['summary']['clean_completed'] == (index == 0)
    assert not result['summary']['final_business_violations']
    assert all(e['search_trace']['evaluations'] <= 256 for e in result['events'] if 'search_trace' in e)
    for e in result['events']:
        if method == 'buffer_search' and 'search_trace' in e:
            assert e['search_trace']['beam_and_final_rank_identical']
    # Verification is limited to these small behavior constructions.
    assert verify_episode(result, task, config)['independent_physics']


@pytest.mark.parametrize('method', ['single', 'buffer_search'])
def test_c12_independent_repeat_and_checkpoint_restore(method):
    task = construct_tasks()[1]; config = cfg()
    a = episode(task, 'public_parser', method, config, LocalCompiler('public_parser'), 'repeat')
    clear_cache()
    b = episode(task, 'public_parser', method, config, LocalCompiler('public_parser'), 'repeat')
    c = episode(task, 'public_parser', method, config, LocalCompiler('public_parser'), 'repeat', resume=a['checkpoints'][1])
    omit = lambda r: stable({k: v for k, v in r.items() if k != 'checkpoints'})
    assert omit(a) == omit(b) == omit(c)


def test_c05_unique_gap_region_and_forbidden_contact_survive_retention():
    from semantic_pallet_planner.o4.extensions.e2.data import request, object_at, policy, relative
    from semantic_pallet_planner.o4.extensions.data import region, spatial
    from semantic_pallet_planner.o4.fixtures import rule, eq
    container = copy.deepcopy(read(P0/'config.snapshot.json')['container'])
    container.update(length_mm=400, width_mm=100, max_height_mm=100)
    ast = policy([relative(gap=50), rule('contact', 'forbidden_contact'), spatial('r', target=eq('cargo_category','food'), region_id='L')])
    req, state = request(ast, placed=[object_at('B', 'household_cleaner')],
                         regions=[region('L', -200, -100, -50, 50)], container=container)
    selected, groups, trace, reason = choose(state, req, ast, cfg(), 'single')
    assert selected is not None and reason is None
    assert selected['pose']['x_mm'] == -150 and selected['pose']['y_mm'] == 0
    assert all(g['evaluation']['allowed_ids'] for g in groups)


@pytest.mark.parametrize('no_top', [False, True])
def test_c08_actual_stacking_vs_zero_load_business_counterexample(no_top):
    from semantic_pallet_planner.o4.extensions.e2.data import request, object_at, policy
    from semantic_pallet_planner.o4.fixtures import rule, eq
    container = copy.deepcopy(read(P0/'config.snapshot.json')['container'])
    container.update(length_mm=100, width_mm=100, max_height_mm=300)
    ast = policy([rule('label', limit='label'), rule('zero', 'no_top_load', eq('labels.no_top_load', True), priority=10, overrides=['label'])])
    req, state = request(ast, placed=[object_at('B', label=2., no_top=no_top)],
                         available=[object_at('A', mass=1.)], container=container)
    selected, groups, _, reason = choose(state, req, ast, cfg(), 'single')
    if no_top:
        assert selected is None and reason == 'no_compiled_business_candidate'
        assert groups[0]['candidates'] and not groups[0]['evaluation']['allowed_ids']
    else:
        assert selected is not None and selected['pose']['z_base_mm'] == 100
        assert selected['support']['support_item_ids'] == ['B']


def test_c06_visible_small_box_can_use_narrow_gap():
    from semantic_pallet_planner.o4.extensions.e2.data import request, object_at, policy
    from semantic_pallet_planner.o4.extensions.data import region, spatial
    from semantic_pallet_planner.o4.fixtures import eq
    container = copy.deepcopy(read(P0/'config.snapshot.json')['container'])
    container.update(length_mm=400, width_mm=100, max_height_mm=100)
    ast = policy([spatial('r', target=eq('cargo_category','food'), region_id='slit')])
    req, state = request(ast, placed=[object_at('B', x=-100), object_at('C', x=50)],
                         available=[object_at('A', 'food', size=(40,100,100))],
                         regions=[region('slit', -50, 0, -50, 50)], container=container)
    selected, groups, _, reason = choose(state, req, ast, cfg(), 'single')
    assert selected is not None and reason is None
    assert bounds(selected)[0] >= -50 and bounds(selected)[1] <= 0
