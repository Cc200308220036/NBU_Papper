"""Read-only final E5 audit, run only after offline/online-plan delivery exists."""
import hashlib
import json
from collections import Counter,defaultdict
from pathlib import Path
import xml.etree.ElementTree as ET
from semantic_pallet_planner.o4.common import read,write,digest
from semantic_pallet_planner.o4.extensions.e2.experiment import verify_seal,files
from semantic_pallet_planner.o4.extensions.e5.experiment import PACKAGE,offline_jobs,online_jobs
from semantic_pallet_planner.o4.extensions.e5.episode import stable
from semantic_pallet_planner.o4.buffer.buffer_state import physical,invariant
from semantic_pallet_planner.evaluation.geometry_oracle import check_candidate

WS=Path('/home/cyw/NBU_Papper');BASE=WS/'semantic_pallet_planner/outputs';OUT=WS/'report/analysis/O4_E5_DEVELOPMENT_20261026_01'
PLAN=BASE/'PLAN_O4_E5_090_OFFLINE_READY_20261026_06';EXP=BASE/'EXP_O4_E5_090_OFFLINE_20261026_06';ONLINE=BASE/'PLAN_O4_E5_090_ONLINE_READY_20261026_01'
report=read(EXP/'acceptance_report.json');assert report['offline_status']=='PASS' and all(report['gates'].values())
readonly=read(OUT/'readonly_verify.json');assert readonly['episode_records_recomputed']==240 and readonly['saved_repeats_verified']==readonly['saved_restores_verified']==120
seals={p.name:verify_seal(p) for p in (PLAN,EXP,ONLINE)}
plan=read(PLAN/'plan.json');data=read(EXP/'private/input_snapshot.json');jobs=read(EXP/'audit/jobs.json');tasks={t['task_id']:t for t in data['tasks']+data['constructs']}
assert files(PACKAGE)==plan['source_files'] and files(WS/'semantic_pallet_planner/src/semantic_pallet_planner')==plan['source_files'];assert len(jobs)==240 and all(j['status']=='PASS' for j in jobs)
assert [{**j,'status':'NOT_RUN'} for j in jobs]==offline_jobs(data)
assert len(data['sources'])==len({s['source_order_key'] for s in data['sources']})==12
v1=read(BASE/'PLAN_O4_E5_090_OFFLINE_READY_20261026_05/private/input_snapshot.json')
for key in ('sources','tasks','constructs','gold','regression_inputs'):assert data[key]==v1[key],key
startup=next(r for r in read(EXP/'audit/faults.json') if r['purpose']=='initialization_failure_records_denominator')
startup_report=read(Path(startup['report_path']))
assert startup_report['status']=='FAIL' and startup_report['not_run_jobs']==240 and startup_report['materialized_jobs']==startup_report['recorded_episodes']==0 and startup_report['new_api_attempts']==0
original=read(WS/'semantic_pallet_planner/outputs/EXP_O4_F_BUFFER_20261021_01/private/input_snapshot.json')
source_sha=hashlib.sha256((WS/'semantic_pallet_planner/outputs/EXP_O4_F_BUFFER_20261021_01/private/input_snapshot.json').read_bytes()).hexdigest()
for t in data['tasks']:
    sid=t['scenario_id'];scenario=original['scenarios'][sid];byid={i['item_id']:i for i in scenario['items']};arrival=scenario['arrival_order'][:12]
    assert t['items']==[byid[i] for i in arrival] and t['attributes']=={i:original['data']['attributes'][sid]['objects'][i] for i in arrival}
    assert t['container']==scenario['container'] and t['provenance']['source_sha256']==source_sha
for a,b in zip(data['tasks'][::2],data['tasks'][1::2]):assert a['reference_policy']['rules']==b['reference_policy']['rules'][:-1]
counts=defaultdict(Counter);events=Counter();commits=0;restores_nonterminal=0;topk_limited=0;truncated=0;component_states=0
job_checks=[]
for job in jobs:
    r=read(EXP/f"episodes/{job['job_id']}.json");s=r['summary'];task=tasks[job['task_id']];state=r['final_state'];invariant(state)
    assert s['planned_items']==len(task['items']) and s['placed_items']==len(state['placed_items'])
    assert s['completed']==(s['placed_items']==len(task['items']))
    assert set(s['pending_ids'])=={p['item']['item_id'] for p in state['pending_items']}
    assert set(s['unarrived_ids'])=={i['item_id'] for i in task['items']}-set(state['arrived_ids'])
    assert not s['final_business_violations'] and s['violating_steps']==0
    if s['source_kind']=='constructed':assert s['completed']==task['expected_by_planner'][s['planner']]
    key=s['source_kind']+'/'+s['backend']+'/'+s['planner'];counts[key]['episodes']+=1;counts[key]['completed']+=s['completed'];counts[key]['placed']+=s['placed_items'];counts[key]['planned_items']+=s['planned_items']
    for e in r['events']:
        events[e['event']]+=1
        if 'source_request' in e:
            q=e['source_request'];observed={o['object_id'] for k in ('placed_objects','available_objects') for o in q[k]}
            assert observed==set(e['before']['arrived_ids']) and not q['images']
            assert not set(q)&{'reference_policy','reference_action','future_items','desired_final_layout'}
            assert len(q['available_objects'])<=s['capacity']
        if e['event'] in ('PLACE','STOP'):
            component_states+=1
            assert e['compilation_metrics']['semantic_equal'] and e['compilation_metrics']['allowed_set_equal']
            assert not e['compilation_metrics']['false_allow_ids'] and not e['compilation_metrics']['false_reject_ids']
            assert len(e['candidates'])<=48 and all(len(g['candidates'])<=16 for g in e['groups'])
            tr=e['search_trace'];assert tr['evaluations']<=256 and tr.get('max_depth',0)<=3 and tr.get('max_beam',0)<=8
            if 'before_real_state' in tr:assert tr['before_real_state']==tr['after_real_state']==digest(e['before'])
            topk_limited+=e['diagnostics']['topk_coverage_limited'];truncated+=tr.get('search_truncated',False)
        if e.get('action'):
            commits+=1;c=next(c for c in e['candidates'] if c['candidate_id']==e['action']['candidate_id'])
            assert not check_candidate(physical(e['before'],c['pick_item_id']),{'container':task['container']},c)
    if s['backend']=='oracle_ast':
        repeat=read(EXP/f"repeats/{job['job_id']}.json");restored=read(EXP/f"restores/{job['job_id']}.json")
        assert stable(repeat)==stable(r)==stable(restored['result'])
        restores_nonterminal+=bool(restored['checkpoint']['state']['pending_items']) and not(restored['checkpoint']['events'] and restored['checkpoint']['events'][-1]['event'] in ('STOP','COMPILE_FAILURE','COMMIT_FAILURE'))
    job_checks.append({'job_id':job['job_id'],'passed':True})
for filename,n in [('regression',180),('invalid',48),('gold',12)]:
    records=read(EXP/f'metrics/{filename}.json');assert len(records)==n and all(r['passed'] for r in records)
assert sum(len(r['individual_rule_witnesses']) for r in read(EXP/'metrics/gold.json'))==2
assert len(read(EXP/'audit/repeats.json'))==len(read(EXP/'audit/restores.json'))==120
faults=read(EXP/'audit/faults.json');assert all(f['passed'] for f in faults)
extra_faults=[]
for filename in ('extra_fault_audit.json','extra_state_fault_audit.json','nonfinite_fault_audit.json','collision_fault_audit.json'):
    extra=read(OUT/filename);assert extra['status']=='PASS' and all(r['passed'] for r in extra['faults']);extra_faults.extend(extra['faults'])
assert len(extra_faults)==17
if not (OUT/'fault_requirement_mapping.json').exists():
    import runpy,contextlib,io
    with contextlib.redirect_stdout(io.StringIO()):runpy.run_path(str(OUT/'fault_coverage_mapping.py'),run_name='__main__')
fault_mapping=read(OUT/'fault_requirement_mapping.json');assert fault_mapping['status']=='PASS' and len(fault_mapping['rows'])==13 and all(r['status']=='PASS' for r in fault_mapping['rows'])
assert {'wrong_ast_drop','wrong_ast_direction','remote_image_commit','global_budget_repair_and_resume','http_saved_before_commit_resume','unknown_attempt_not_resent','explicit_unsupported_yaw_instruction','unsupported_allowed_yaw_ast'}<={f['purpose'] for f in faults}
protected=read(OUT/'protected.before.json');changed=[name for name,sha in protected.items() if not (WS/name).is_file() or hashlib.sha256((WS/name).read_bytes()).hexdigest()!=sha];assert not changed
online=read(ONLINE/'plan.json');assert online['jobs']==online_jobs(data) and len(online['jobs'])==240
assert online['maximum_api_attempts']==sum(j['attempt_limit'] for j in online['jobs'])==3100
assert online['prefix_maximum_api_attempts']==sum(j['attempt_limit'] for j in online['jobs'][:20])==260
assert {j['task_id'] for j in online['jobs'][:20]}=={'E5_SRC00_C0','E5_SRC01_C1'}
assert not (BASE/'EXP_O4_E5_090_REAL_20261026_01').exists(),'Developer must not run the user real experiment'
test_ids=set()
for name in ('tests_acceptance_v2_final.xml',):
    tree=ET.parse(OUT/name).getroot();suites=tree.findall('testsuite')
    assert all(int(x.get('failures',0))==int(x.get('errors',0))==0 for x in suites)
    for case in tree.iter('testcase'):test_ids.add((case.get('classname'),case.get('name')))
test_count=len(test_ids);assert test_count>=80
assert read(OUT/'tests_v2_source_binding.json')['status']=='PASS'
for rel,sha in read(OUT/'tests_v2_before.json').items():assert hashlib.sha256((WS/rel).read_bytes()).hexdigest()==sha
assert read(EXP/'audit/attempts.json')==[] and read(EXP/'audit/budget.json')['real_api_attempts']==0
assert len(read(EXP/'metrics/failure_attribution.json'))==240
summary=read(EXP/'metrics/summary.json')
assert sum(g['planned_episodes'] for g in summary['groups'])==sum(g['recorded_episodes'] for g in summary['groups'])==240
assert all(g['measurement_complete'] for g in summary['groups'])
assert sum(g['compilation']['decisions'] for g in summary['groups'])==len(read(EXP/'audit/compilations.json'))
assert all(g['compilation']['first_valid_rate']==g['compilation']['final_valid_rate']==1 for g in summary['groups'])
assert all(g['mean_placed_volume_ratio'] is not None for g in summary['groups'])
result={'status':'PASS','sealed_files':seals,'source_matches_frozen':True,'planned_source_tasks':24,'independent_development_sources':12,
        'primary_episodes':192,'construct_episodes':48,'job_checks':len(job_checks),'actual_commits_independently_checked':commits,
        'per_source_kind_backend_planner':dict(counts),'event_counts':dict(events),'compilation_states':component_states,
        'semantic_regression':180,'invalid_regression':48,'mixed_gold':12,'repeats':120,'restores':120,
        'restores_with_nonterminal_prefix':restores_nonterminal,'topk_limited_decision_states':topk_limited,'truncated_search_decisions':truncated,
        'faults':len(faults),'additional_independent_copy_fault_checks':len(extra_faults),'protected_files':len(protected),'protected_changed':changed,'distinct_tests':test_count,
        'online_planned_jobs':240,'online_prefix_jobs':20,'api_attempt_limit':3100,'prefix_api_attempt_limit':260,
        'new_api_attempts':0,'real_online_status':'NOT_RUN','e3_status':'DEFERRED','e4_status':'OUT_OF_SCOPE',
        'unseen_generalization':'NOT_MEASURED','visual_increment':'NOT_MEASURED'}
write(OUT/'evidence.json',result);write(OUT/'job_checks.json',job_checks)
requirements=[]
def item(key,claim,evidence):requirements.append({'requirement':key,'claim':claim,'status':'PASS','evidence':evidence})
for key,value in report['gates'].items():assert value;item(key,'E5 numbered acceptance gate',f'{EXP.relative_to(WS)}/acceptance_report.json:gates.{key}')
for key,claim,evidence in [
 ('1_SCOPE','0/90 current scope, E3 deferred and E4 out of scope','config.snapshot.json; faults; tests_acceptance_v2_final.xml'),
 ('2_SEMANTICS','five frozen rule families, bindings, reference isolation and 16/48/3/8/256 caps','regression.json; gold.json; episode traces; resource_maxima'),
 ('3_BACKENDS','actual compiled_request carried through image-bound proposal and commit; global budget and interruption recovery','tests_acceptance_v2_final.xml; audit/faults.json; faults/ HTTP artifacts'),
 ('4_DATA','twelve fixed old development sources, 24 exact C0/C1 tasks, independent new gold and manual paths','private/input_snapshot.json; provenance comparison in this audit'),
 ('5_CLOSURE','actual full-order transitions, full denominators, pending and unarrived preserved','job_checks.json; episodes/'),
 ('EX-E5-CONTRACT','closed capabilities, input/response/action binding, source/private separation','audit/faults.json; tests_acceptance_v2_final.xml'),
 ('EX-E5-REGRESSION','180 semantic and48 invalid regressions recomputed with frozen inputs','metrics/regression.json; metrics/invalid.json'),
 ('EX-E5-MIXED-GOLD','12 declared arithmetic combinations6 allow6 reject','metrics/gold.json'),
 ('EX-E5-CONSTRUCT','6 constructs×2 backends×4 planners, four positive and two proven negatives','episodes/; private/manual_witnesses.json'),
 ('EX-E5-MIXED','24source tasks×2backends×4planners; unsuccessful orders retained','metrics/summary.json; audit/jobs.json'),
 ('EX-E5-FAULT','actual injection with raw HTTP doubles, wrong AST effects, budget and saved-state recovery','audit/faults.json; tests_acceptance_v2_final.xml'),
 ('EX-E5-VISUAL','all actual compilation states plus gold, independent facts/geometry/card/pixel/hash checks','audit/visual.json; public/images/'),
 ('EX-E5-DELIVERY','240primary records readonly-recomputed and120 Oracle repeats/restores checked','readonly_verify.json; audit/repeats.json; audit/restores.json'),
 ('6_REAL_HANDOFF','240job frozen real plan; 20job prefix not duplicated; global attempts3100 and prefix260','PLAN_O4_E5_090_ONLINE_READY_20261026_01; runtime handbook'),
 ('7_METRICS','symbolic semantics distinct from nonempty rule applicability, N/A and stopped orders','metrics/summary.json; activity.py; failure diagnostics'),
 ('8_FAULT_TABLE','each required fault family mapped to explicit injection outcomes and code tests','audit/faults.json; extra_fault_audit.json; extra_state_fault_audit.json; tests_acceptance_v2_final.xml'),
 ('9_ORDER','scope/data frozen before formal matrix, no real API by developer','plan.json; protection baseline; real plan; new_api_attempts0'),
 ('11_INITIALIZATION_FAILURE','new output records operation/phase/error and all unexecuted jobs; existing outputs untouched','audit/faults.json:initialization_failure_records_denominator; faults/failed_initialization/; tests_acceptance_v2_final.xml'),
 ('11_DELIVERY','actual CLI/help, frozen sources, test and docs snapshots, no overwritten old artifacts','documentation/cli_help.txt; protected.before.json; source_and_tests.json'),
 ('12_EXCLUSIONS','no E3/robot/visual perception/unseen claims','acceptance_report.json; development and runtime docs')]:item(key,claim,evidence)
write(OUT/'requirements_audit.json',{'status':'PASS','scope':'E5 0/90 offline development and real API handoff','requirements':requirements,
      'delegated_to_user':[{'requirement':'E5-R','status':'NOT_RUN','reason':'Real API commands supplied for user execution'}]})
paths=[*sorted((WS/'semantic_pallet_planner/src/semantic_pallet_planner/o4/extensions/e5').glob('*.py')),
       WS/'semantic_pallet_planner/src/semantic_pallet_planner/runners/o4_e5.py',WS/'semantic_pallet_planner/configs/o4_e5_090_offline_v2.json',
       WS/'semantic_pallet_planner/tests/unit/test_o4_e5.py',WS/'semantic_pallet_planner/tests/integration/test_o4_e5_delivery.py']
write(OUT/'source_and_tests.json',{str(p.relative_to(WS)):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths})
print(json.dumps(result,ensure_ascii=False,indent=2))
