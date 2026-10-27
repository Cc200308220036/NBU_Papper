"""Artifact and source audit. Does not rerun planning or semantic evaluation."""
import hashlib
import json
from pathlib import Path
import statistics
import xml.etree.ElementTree as ET

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
OUT = ROOT/'semantic_pallet_planner/outputs'
P0 = OUT/'EXP_O4_E5_LAYOUT_V2_P0_20261027_01'
PLAN = OUT/'PLAN_O4_E5_LAYOUT_V2_20261027_01'
EXP = OUT/'EXP_O4_E5_LAYOUT_V2_L2_20261027_01'


def read(path): return json.loads(path.read_text())
def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2)+'\n')
def sha(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for data in iter(lambda: stream.read(1024*1024), b''): h.update(data)
    return h.hexdigest()
def digest(obj): return hashlib.sha256(json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()
def percentile(values, p):
    values = sorted(values); x = (len(values)-1)*p; a = int(x); b = min(a+1,len(values)-1)
    return values[a]+(values[b]-values[a])*(x-a)


def main():
    plan = read(PLAN/'plan.json'); manifest = read(PLAN/'manifest.json')
    assert digest(plan) == manifest['plan_digest']
    for rel, expected in manifest['snapshot_sha256'].items(): assert sha(PLAN/'code_snapshot'/rel) == expected, rel
    for rel, expected in manifest['source_sha256'].items(): assert sha(ROOT/rel) == expected, rel
    original = read(OUT/'PLAN_O4_E5_090_OFFLINE_READY_20261026_06/private/input_snapshot.json')
    assert plan['tasks'] == original['tasks'] and plan['constructs'] == original['constructs']
    assert plan['group_configurations']['A'] == plan['base_config']
    assert read(ROOT/'semantic_pallet_planner/configs/o4_e5_layout_v2.json') == plan['group_configurations']['D']['o4_e5_layout']
    for g in 'BCD':
        cfg = dict(plan['group_configurations'][g]); extension = cfg.pop('o4_e5_layout')
        assert cfg == plan['base_config']
        assert (extension['candidate_retention'], extension['ranking']) == {'B':(True,False),'C':(False,True),'D':(True,True)}[g]
    junit = ET.parse(HERE/'behavior_tests_final.xml').getroot()
    tests = list(junit.iter('testcase'))
    assert len(tests) == 21 and all(not list(t) for t in tests)
    names = [t.attrib['name'] for t in tests]
    assert read(HERE/'supplementary_checks.json')['status'] == 'PASS'
    assert len(read(HERE/'supplementary_checks.json')['checks']) == 4
    jobs = read(EXP/'jobs.json'); rows = read(EXP/'metrics/rows.json')
    assert len(jobs) == len(rows) == 56 and all(j['status'] == 'PASS' for j in jobs)
    assert sum(j['stage'] == 'L2' for j in jobs) == 48
    assert sum(j['stage'] == 'compat' for j in jobs) == 8
    source_set = sorted({t['source_order_key'] for t in plan['tasks']})
    assert plan['l2_sources'] == [source_set[i] for i in (0,2,4)]
    max_joint = max_per = max_evaluations = max_depth = max_beam = actions = 0
    for row in rows:
        path = EXP/'episodes'/f'{row["job_id"]}.json'
        assert sha(path) == row['episode_sha256']
        result = read(path); summary = result['summary']
        assert summary['execution_status'] == 'PASS'
        assert not summary['final_business_violations'] and summary['violating_steps'] == 0
        assert len(result['final_state']['placed_items']) == summary['placed_items']
        assert summary['arrived_items']+len(summary['unarrived_ids']) == summary['planned_items']
        assert summary['arrived_items'] == summary['placed_items']+len(summary['pending_ids'])
        for event in result['events']:
            if not event.get('groups'): continue
            groups = event['groups']; trace = event['search_trace']
            max_joint = max(max_joint,sum(len(g['candidates']) for g in groups))
            max_per = max(max_per,max(len(g['candidates']) for g in groups))
            max_evaluations = max(max_evaluations,trace['evaluations'])
            max_depth = max(max_depth,trace.get('max_depth',0)); max_beam = max(max_beam,trace.get('max_beam',0))
            if 'before_real_state' in trace: assert trace['before_real_state'] == trace['after_real_state']
            if row['group'] in ('C','D') and row['method'] == 'buffer_search':
                assert trace['beam_and_final_rank_identical']
            if event['action']:
                selected = next(c for c in event['candidates'] if c['candidate_id'] == event['action']['candidate_id'])
                group = next(g for g in groups if selected in g['candidates'])
                assert selected['candidate_id'] in group['trace']['eligible_labels']
                assert selected['physical_valid'] and selected['pose']['yaw_deg'] in (0,90)
                assert len(event['after']['placed_items']) == len(event['before']['placed_items'])+1
                assert not event['reference_after']['violations']; actions += 1
    assert max_joint <= 48 and max_per <= 16 and max_evaluations <= 256 and max_depth <= 3 and max_beam <= 8
    timing = [read(HERE/f'timing_process_{i}.json') for i in (1,2,3)]
    assert len({t['pid'] for t in timing}) == 3
    assert all(t['recorded_cold_decisions'] == t['recorded_hot_decisions'] == 24 for t in timing)
    assert all(Path(t['module_path']).is_relative_to(PLAN/'code_snapshot') for t in timing)
    assert all(r['hot_root_hit'] for t in timing for r in t['rows'])
    latency = []
    for method in ('single','buffer_search'):
        numbers = {}
        for group in ('A','D'):
            values = [r['seconds'] for t in timing for r in t['rows'] if r['method'] == method and r['group'] == group]
            hot = [r['hot_seconds'] for t in timing for r in t['rows'] if r['method'] == method and r['group'] == group]
            cache_rows = [r['cold_cache_info'] for t in timing for r in t['rows'] if r['method'] == method and r['group'] == group]
            cache_rates = {}
            for role in ('legacy_root','new_root','legacy_candidates','new_candidates'):
                hits = sum(r[role]['hits'] for r in cache_rows); misses = sum(r[role]['misses'] for r in cache_rows)
                cache_rates[role] = {'hits':hits,'misses':misses,'hit_rate':hits/(hits+misses) if hits+misses else None}
            numbers[group] = {'cold_median_seconds': statistics.median(values), 'cold_p95_seconds':percentile(values,.95),
                              'hot_median_seconds':statistics.median(hot), 'samples':len(values), 'cold_run_cache_info':cache_rates,
                              'hot_root_hit_rate':1.0}
        ratios = {'median_ratio':numbers['D']['cold_median_seconds']/max(.001,numbers['A']['cold_median_seconds']),
                  'p95_ratio':numbers['D']['cold_p95_seconds']/max(.001,numbers['A']['cold_p95_seconds'])}
        latency.append({'method':method, 'groups':numbers, **ratios,
                        'local_cost_gate': ratios['median_ratio'] <= 2 and ratios['p95_ratio'] <= 3})
    write(HERE/'latency_independent_processes.json', {'processes':3,'cold_decisions':72,'hot_decisions':72,'methods':latency,
            'scope':'fixed same saved public states; main actual trajectories reported separately'})
    print('Checking protected historical files (hashes only)', flush=True)
    protected = read(P0/'protected.before.json')
    changed = [rel for rel, checksum in protected.items() if not (ROOT/rel).is_file() or sha(ROOT/rel) != checksum]
    protection = {'status':'PASS' if not changed else 'FAIL','checked':len(protected),'changed':changed,
                  'scope':'predevelopment historical artifacts and frozen E1/E2/planner/schema/data files; excludes __pycache__'}
    write(HERE/'historical_protection.json', protection)
    assert not changed
    baseline = read(P0/'manifest.json')['source_sha256']
    source_changed = [rel for rel, checksum in baseline.items()
                      if '/layout_v2/' not in rel and not rel.endswith('runners/o4_e5_layout_v2.py')
                      and not rel.endswith('extensions/e5/planning.py') and sha(ROOT/rel) != checksum]
    assert not source_changed
    dispatcher = ROOT/'semantic_pallet_planner/src/semantic_pallet_planner/o4/extensions/e5/planning.py'
    before = P0/'code_snapshot/semantic_pallet_planner/o4/extensions/e5/planning.py'
    insertion = "    if 'o4_e5_layout' in config:\n        from .layout_v2.planning import choose as layout_choose\n        return layout_choose(state,req,ast,config,method)\n"
    assert dispatcher.read_text().replace(insertion,'',1) == before.read_text()
    visual = read(HERE/'visual_validation.json'); assert visual['xml_valid'] and visual['axes_equal_scale'] and visual['hypotheses_labelled']
    explanation = read(HERE/'trajectory_explanations.json'); assert len(explanation) == 12
    local_rollback = read(HERE/'l0_rollback_fixed_states.json')
    assert local_rollback['fixed_states'] == len(local_rollback['records']) == 8
    assert {r['method'] for r in local_rollback['records']} == {'single','buffer_fifo','buffer_heuristic','buffer_search'}
    checks = {
        'C01': {'status':'PASS','evidence':['frozen/default source comparison','test_c01_default_dispatch_and_closed_version']},
        'C02': {'status':'PASS','evidence':['test_c02_contact_coordinates_and_height_separation','fixed_decisions.json']},
        'C03': {'status':'PASS','evidence':['test_c03_l0_original_alignment_is_retained_from_same_pool','per-episode retention and coverage_lost']},
        'C04': {'status':'PASS','evidence':['test_c04_l0_micro_probe_difference_cannot_defeat_contact','L0 A/B/C/D fixed-state choices']},
        'C05': {'status':'PASS','evidence':['test_c05_unique_gap_region_and_forbidden_contact_survive_retention','positive and contradictory orders']},
        'C06': {'status':'PASS','evidence':['test_c06_visible_small_box_can_use_narrow_gap']},
        'C07': {'status':'PASS','evidence':['test_c07_mirror_geometry_quality_and_empty_contact','all saved submitted candidates in original soft eligible set']},
        'C08': {'status':'PASS','evidence':['test_c08_actual_stacking_vs_zero_load_business_counterexample','supplementary cumulative load and third-layer boundary checks']},
        'C09': {'status':'PASS','evidence':['test_c06_c09_exact_union_and_fragmentation_are_soft_descriptors','tuple ranking, exact rectangle boundaries, positive dimensions']},
        'C10': {'status':'PASS','evidence':['test_c10_c11_hidden_data_cache_isolation_and_stale_action','unchanged bound commit and public state projection']},
        'C11': {'status':'PASS','evidence':['search construction checks','all saved budget and root-state checks','frozen cache supplementary check']},
        'C12': {'status':'PASS','evidence':['test_c12_independent_repeat_and_checkpoint_restore','supplementary second construct repeat/restore']},
        'C13': {'status':'PASS','evidence':['local_decisions.png visually inspected','layouts.html','visual_validation.json'],
                'limitation':'no automated browser session; generated SVG XML and source data validated'},
        'C14': {'status':'PASS','evidence':['historical_protection.json','unchanged legacy source comparison','frozen manifest and input equality']}}
    findings = read(HERE/'analysis.json')
    for check in checks.values():
        for evidence in check['evidence']:
            if evidence.startswith('test_'): assert any(n.startswith(evidence) for n in names), evidence
    deferred = [{'task_id':r['task_id'],'method':r['method'],'questions':r['unresolved_for_user_review']} for r in explanation if r['unresolved_for_user_review']]
    delivery = {'engineering_status':'PASS', 'engineering_scope':'C01-C14, local feature/guard checks and new 48+8 execution; no claim of packing benefit',
                'performance_status':'L2_FAILED_TO_QUALIFY_FOR_EXPANSION' if not findings['L3_recommended'] else 'L2_SCREEN_PASS_L3_REQUIRED',
                'default_replacement_status':'NOT_ELIGIBLE_ORIGINAL_REMAINS_DEFAULT',
                'L3_status':'NOT_RUN_L2_GATE_NOT_MET' if not findings['L3_recommended'] else 'REQUIRED_NOT_RUN',
                'new_api_attempts':0,'main_episodes':48,'compatibility_episodes':8,'actual_submissions':actions,
                'maxima':{'joint':max_joint,'per_object':max_per,'evaluations':max_evaluations,'depth':max_depth,'beam':max_beam},
                'checks':checks,'primary_behavior_tests':21,'frozen_supplementary_checks':4,
                'historical_protection':protection,'cost':latency,'pending_user_review':deferred,
                'pending_review_scope':'explanatory causal attribution only; no changes or retuning attempted',
                'business_support_quality':'NOT_IMPLEMENTED','probe_quality':'NOT_IMPLEMENTED',
                'independent_generalization':'NOT_MEASURED','old_240_extra_recheck':'NOT_RUN_USER_WAIVER_PRESERVED',
                'old_D_replay':'NOT_RUN','documentation':['docs/03_阶段产出分析/O4/O4E5规划质量V2开发与分级验收_20261027.md',
                'docs/04_运行与复核手册/O4E5规划质量V2本地运行与复核_20261027.md']}
    write(HERE/'delivery_audit.json',delivery)
    write(EXP/'delivery_acceptance_report.json',{**delivery,'evidence_report':str((HERE/'delivery_audit.json').relative_to(ROOT)),
          'initial_execution_report':'acceptance_report.json','note':'separate delivery audit; initial execution report and all episode records preserved'})
    artifacts = {str(p.relative_to(ROOT)):sha(p) for p in HERE.rglob('*') if p.is_file() and p.name != 'artifact_manifest.json'}
    write(HERE/'artifact_manifest.json',{'files':artifacts,'new_api_attempts':0})
    print(json.dumps({k:v for k,v in delivery.items() if k not in ('checks','cost','pending_user_review')},ensure_ascii=False,indent=2))


if __name__ == '__main__': main()
