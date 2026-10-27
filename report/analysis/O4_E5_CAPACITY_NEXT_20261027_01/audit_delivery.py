"""Requirement-by-requirement final audit, including historical integrity."""
import hashlib
import json
import xml.etree.ElementTree as ET
from pathlib import Path

HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[2];OUT=ROOT/'semantic_pallet_planner/outputs'


def read(p):return json.loads(p.read_text())


def sha(p):
    h=hashlib.sha256()
    with p.open('rb') as f:
        for block in iter(lambda:f.read(1024*1024),b''):h.update(block)
    return h.hexdigest()


def write(p,d):
    with p.open('x') as f:json.dump(d,f,ensure_ascii=False,indent=2);f.write('\n')


T0=OUT/'EXP_O4_E5_CAPACITY_NEXT_T0_20261027_01';FP=OUT/'PLAN_O4_E5_CAPACITY_NEXT_F_20261027_01';SP=OUT/'PLAN_O4_E5_CAPACITY_NEXT_SMALL_20261027_01'
main=read(HERE/'main_audit.json');cost=read(HERE/'cost_audit.json');diag=read(T0/'local_diagnosis.json')
assert main['records']==96 and main['new_episodes']==84
test_root=ET.parse(HERE/'behavior_tests.xml').getroot()
tests=list(test_root.iter('testcase'));assert len(tests)==15 and not list(test_root.iter('failure')) and not list(test_root.iter('error'))
assert read(HERE/'three_dimensional_checks.json')['status']=='PASS'
assert read(HERE/'binding_checks.json')['status']=='PASS' and read(HERE/'mirror_checks.json')['status']=='PASS'
assert len(list((T0/'calls').glob('*.started.json')))==12
assert len(list((T0/'calls').glob('*.json')))==24
assert all(diag['tree_consistency'].values()) and all(read(HERE/'t0_interpretation.json')['checks'].values())
assert read(HERE/'t0_observational_equivalence.json')['status']=='PASS'
snapshots=[read(p/'manifest.json') for p in (SP,FP)]
assert snapshots[0]['snapshot_sha256']==snapshots[1]['snapshot_sha256']
for plan,m in zip((SP,FP),snapshots):
    assert all(sha(plan/'code_snapshot'/p)==h for p,h in m['snapshot_sha256'].items())
    assert all(sha(ROOT/p)==h for p,h in m['source_sha256'].items())
protected=read(OUT/'EXP_O4_E5_LAYOUT_V2_P0_20261027_01/protected.before.json')
for p,h in read(T0/'protected.before.json').items():
    assert p not in protected or protected[p]==h
    protected[p]=h
changed=[p for p,h in protected.items() if not (ROOT/p).is_file() or sha(ROOT/p)!=h]
old=read(OUT/'PLAN_O4_E5_LAYOUT_V2_20261027_01/manifest.json')
historical_source=[p for p,h in old['source_sha256'].items() if not p.endswith('/e5/planning.py') and sha(ROOT/p)!=h]
protection={'status':'PASS' if not changed and not historical_source else 'FAIL','historical_files_checked':len(protected),
            'changed':changed,'old_source_files_checked_except_authorized_dispatch':len(old['source_sha256'])-1,'old_source_changed':historical_source,
            'scope':'file hashes, not old planning replay or waived 240 verification','new_api_attempts':0}
write(HERE/'historical_protection.json',protection);assert protection['status']=='PASS'
decisions=read(HERE/'main_decisions.json');pending=sorted({d['pending_count'] for d in decisions if d['group']=='F' and d['method']=='buffer_search'})
assert pending==[1,2,3]
visual=read(HERE/'visual_smoke.json');assert visual['status']=='PASS'
assert read(HERE/'image_review.json')['status']=='PASS'
regressions=read(HERE/'regression_cases.json')
checks={
 'N01':{'status':'PASS','evidence':['15 targeted tests; seven B pose/coverage/eligible comparisons','identical small/F snapshots; frozen actual imports; main default AST proof']},
 'N02':{'status':'PASS','evidence':['Q5 B0 empty choice equals frozen B; unchanged legacy soft/geometry ranking']},
 'N03':{'status':'PASS','evidence':['Q6/Q7 retained B poses','gap/narrow/forbidden-contact tests','mirror_checks.json']},
 'N04':{'status':'PASS_CLOSED','evidence':['terminal_quality/P3/probe explicitly NOT_IMPLEMENTED; no new last-action quality ranking']},
 'N05':{'status':'PASS','evidence':['12 T0 calls; four tree-pair consistency checks; eight historical node-sequence comparisons','all root actions include zero/nonzero exposure; full rank and beam rejection logs']},
 'N06':{'status':'PASS','evidence':['all 96 records bounded16/48/3/8/256','F per-node spent deltas, reserve affordability and pending1/2/3 accounting','R not introduced; no new reserved-budget interpretation']},
 'N07':{'status':'PASS','evidence':['actual stacking/no-top tests','four indirect/multi-support boundary tests','all new actual commit/reference guards']},
 'N08':{'status':'PASS','evidence':['hidden future/deep-copy tests','binding_checks.json: stale cross-version action rejected, fresh clone commit, AST cache isolation']},
 'N09':{'status':'PASS','evidence':['single/search small construction independent root repeats and checkpoint restore in behavior_tests.xml']},
 'N10':{'status':'PASS','evidence':['review.html, all48 pairs, input/AST, actual vs hypothetical distinction','actual_layouts.png inspected; visual_smoke.json','no full browser claim']},
 'N11':{'status':'REPORTED','evidence':['main_pairs.json and main_audit.json; all severe regressions/HOLD explicit','three-process cold/hot cost_audit.json; timing sample scope explicit','S/R/E not tried, old D negative preserved']},
 'N12':{'status':'PASS','evidence':['historical_protection.json','original A default; local compiler only; API=0; old D-L3/D replay/old240 not run']}}
reasons=[]
if main['performance_status']!='CAPACITY_GATE_PASS':reasons.append('CAPACITY_GATE_FAILED')
if any(a['hold_tasks'] for a in main['aggregates']):reasons.append('SEVERE_TASK_REGRESSION')
if cost['status']!='PASS':reasons.append('COST_GATE_FAILED')
report={'engineering_status':'PASS','performance_status':main['performance_status'],
        'default_replacement_status':'NOT_ELIGIBLE_'+ '_AND_'.join(reasons) if reasons else 'ELIGIBLE_FOR_REVIEW_ORIGINAL_REMAINS_DEFAULT',
        'default_enabled':False,'F':'B0','checks':checks,'aggregates':main['aggregates'],'cost_status':cost['status'],
        'default_hold_reasons':reasons,'new_api_attempts':0,'T0_search_calls':12,'new_performance_episodes':84,
        'major_records':96,'tasks':24,'historical_development_sources':12,'planned_boxes_per_version_method':286,
        'unimplemented':['S','R','E','whole_terminal_quality','P3','probe','new_sampling_backend'],
        'not_proven':['unique full-order causal attribution from local T0','global infeasibility of STOP','independent generalization','tail latency guarantee outside frozen cost sample'],
        'old_D_L3':'NOT_RUN_NOT_RESUMED','old_240_extra_verification':'USER_WAIVER_PRESERVED','D_replay':'NOT_RUN',
        'historical_protection':protection,'cost_scope':cost['sample_scope']}
report['causal_review_required']=[c['pair']['task_id'] for c in regressions['cases']]
report['regression_followup_searches']=0
write(HERE/'delivery_audit.json',report)
print(json.dumps({k:v for k,v in report.items() if k not in ('checks','historical_protection')},ensure_ascii=False,indent=2))
