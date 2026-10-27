"""Checks for B0's new seam and identities; no extra T0 searches."""
import copy
import json
from pathlib import Path
import pytest
from semantic_pallet_planner.o4.common import O4Error
from semantic_pallet_planner.o4.extensions.e5.layout_v3.config import DEFAULT, validate, v2_config
from semantic_pallet_planner.o4.extensions.e5.layout_v3.planning import choose, pools, clear_cache
from semantic_pallet_planner.o4.extensions.e5.layout_v3.suite import configuration
from semantic_pallet_planner.o4.extensions.e5.layout_v2.planning import pools as old_pools
from semantic_pallet_planner.o4.extensions.e2.candidates import key
from semantic_pallet_planner.o4.extensions.e5.layout_v3.experiment import TARGET, OLD, read
from semantic_pallet_planner.o4.extensions.e5.episode import episode, stable
from semantic_pallet_planner.o4.extensions.e5.backends import LocalCompiler
from semantic_pallet_planner.o4.extensions.e5.data import construct_tasks


def cfg(): return configuration(read(OLD/'plan.json')['base_config'])


@pytest.mark.parametrize('q', [f'Q{i}' for i in range(1, 8)])
def test_b0_exact_B_pose_coverage_and_eligibility(q):
    c = read(TARGET/'inputs.json')[q]; config = cfg()
    a, ac = old_pools(c['state'], c['request'], c['ast'], v2_config(config))
    b, bc = pools(c['state'], c['request'], c['ast'], config)
    assert ac == bc <= 48
    for x, y in zip(a, b):
        for field in ('candidates', 'eligible'): assert [key(c) for c in x[field]] == [key(c) for c in y[field]]
        assert key(x['selected']) == key(y['selected']) if x['selected'] else y['selected'] is None
        for field in ('retention', 'coverage_lost', 'coverage_gained'): assert x['generation'][field] == y['generation'][field]
        assert all(c['candidate_id'].startswith('E5B0_') for c in y['candidates'])
        assert set(c['candidate_id'] for c in x['candidates']).isdisjoint(c['candidate_id'] for c in y['candidates'])


def test_closed_version_and_V2_not_relaxed():
    from semantic_pallet_planner.o4.extensions.e5.layout_v2.config import validate as v2_validate
    for field in DEFAULT:
        c = cfg(); c['o4_e5_capacity'][field] = 'unknown'
        with pytest.raises(O4Error): validate(c)
    c = cfg(); c['o4_e5_layout'] = v2_config(cfg())['o4_e5_layout']
    with pytest.raises(O4Error): validate(c)
    v = v2_config(cfg())['o4_e5_layout']; v['version'] = DEFAULT['version']
    with pytest.raises(O4Error): v2_validate(v)


def test_public_root_cache_copy_and_empty_choice():
    c = read(TARGET/'inputs.json')['Q5']; config = cfg(); before = copy.deepcopy(c['state'])
    expected = read(OLD/'plan.json')['group_configurations']['B']
    from semantic_pallet_planner.o4.extensions.e5.layout_v2.planning import choose as B_choose
    a = choose(c['state'], c['request'], c['ast'], config, 'single')
    old = B_choose(c['state'], c['request'], c['ast'], expected, 'single')
    assert key(a[0]) == key(old[0])
    a[0]['pose']['x_mm'] = 123456; a[1].clear()
    hidden = copy.deepcopy(c['state']); hidden['private_future'] = [{'length_mm': 999999}]
    b = choose(hidden, c['request'], c['ast'], config, 'single')
    assert key(b[0]) == key(old[0]) and b[1] and c['state'] == before


@pytest.mark.parametrize('case', ['gap', 'narrow', 'stack', 'no_top'])
def test_existing_rule_counterexamples_through_B0(monkeypatch, case):
    import test_o4_e5_layout_v2 as guard
    monkeypatch.setattr(guard, 'choose', choose); monkeypatch.setattr(guard, 'cfg', cfg)
    if case == 'gap': guard.test_c05_unique_gap_region_and_forbidden_contact_survive_retention()
    elif case == 'narrow': guard.test_c06_visible_small_box_can_use_narrow_gap()
    else: guard.test_c08_actual_stacking_vs_zero_load_business_counterexample(case == 'no_top')


@pytest.mark.parametrize('method', ['single', 'buffer_search'])
def test_small_construction_repeat_and_restore(method):
    task = construct_tasks()[1]; config = cfg()
    a = episode(task, 'public_parser', method, config, LocalCompiler('public_parser'), 'B0_repeat')
    clear_cache()
    b = episode(task, 'public_parser', method, config, LocalCompiler('public_parser'), 'B0_repeat')
    restored = episode(task, 'public_parser', method, config, LocalCompiler('public_parser'), 'B0_repeat', resume=a['checkpoints'][1])
    omit = lambda r: stable({k: v for k,v in r.items() if k != 'checkpoints'})
    assert omit(a) == omit(b) == omit(restored)
    assert not a['summary']['final_business_violations']
    assert all(e['search_trace']['evaluations'] <= 256 for e in a['events'] if 'search_trace' in e)
