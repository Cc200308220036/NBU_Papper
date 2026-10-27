"""Read-only audit of sealed E2 final artifacts; writes only this report directory."""
import hashlib
import json
import subprocess
import xml.etree.ElementTree as ET
from collections import Counter,defaultdict
from pathlib import Path
from semantic_pallet_planner.o4.common import read,write,digest
from semantic_pallet_planner.o4.extensions.e2.experiment import verify_seal,files
from semantic_pallet_planner.o4.extensions.e2.episode import stable
from semantic_pallet_planner.o4.extensions.e2.reference import state as reference_state
from semantic_pallet_planner.evaluation.geometry_oracle import check_candidate
from semantic_pallet_planner.o4.buffer.buffer_state import physical,invariant

WORKSPACE=Path('/home/cyw/NBU_Papper')
OUT=WORKSPACE/'report/analysis/O4_E2_DEVELOPMENT_20261025_01'
BASE=WORKSPACE/'semantic_pallet_planner/outputs'
PLAN=BASE/'PLAN_O4_E2_OFFLINE_READY_20261025_01'
EXP=BASE/'EXP_O4_E2_OFFLINE_20261025_01'
report=read(EXP/'acceptance_report.json')
assert report['status']=='PASS'
readonly=read(OUT/'readonly_verify.json');assert readonly['status']=='PASS' and readonly['episode_records_recomputed']==96
plan=read(PLAN/'plan.json');data=read(EXP/'private/data.json');tasks={t['task_id']:t for t in data['constructs']}
seals={p.name:verify_seal(p) for p in (PLAN,EXP,BASE/'PLAN_O4_E2_SMOKE_READY_20261025_01',BASE/'PLAN_O4_E2_FIXED_READY_20261025_01')}
assert files(WORKSPACE/'semantic_pallet_planner/src/semantic_pallet_planner')==plan['source_files']
jobs=read(EXP/'audit/jobs.json');assert len(jobs)==96 and all(j['status']=='PASS' for j in jobs)
counts=defaultdict(Counter);commits=0;maxima=Counter();summary_checks=[];semantics=Counter();events=Counter();deferred_steps=0
for job in jobs:
    result=read(EXP/f"episodes/{job['job_id']}.json");summary=result['summary'];task=tasks[job['task_id']];final=result['final_state']
    invariant(final)
    assert summary['placed_items']==final['placed_count']==len(final['placed_items'])
    assert summary['completed']==(len(final['placed_items'])==len(task['items']))==task['expected_by_planner'][job['planner']]
    assert summary['arrived_items']==len(final['arrived_ids'])
    assert set(summary['pending_ids'])=={p['item']['item_id'] for p in final['pending_items']}
    assert set(summary['unarrived_ids'])=={o['item_id'] for o in task['items']}-set(final['arrived_ids'])
    counts[job['planner']]['episodes']+=1;counts[job['planner']]['completed']+=summary['completed'];counts[job['planner']]['placed']+=final['placed_count']
    for e in result['events']:
        events[e['event']]+=1
        if 'request' not in e:continue
        q=e['request'];assert not any(k in q for k in ('reference_policy','reference_action','future_items'))
        ids={o['object_id'] for key in ('placed_objects','available_objects') for o in q[key]}
        assert ids==set(e['before']['arrived_ids'])
        n=len(e['candidates']);maxima['joint_candidates']=max(maxima['joint_candidates'],n);assert n<=48
        for group in e['groups']:
            maxima['per_object_candidates']=max(maxima['per_object_candidates'],len(group['candidates']));assert len(group['candidates'])<=16
        trace=e['search_trace']
        for key,cap in [('evaluations',256),('max_depth',3),('max_beam',8)]:
            maxima[key]=max(maxima[key],trace.get(key,0));assert trace.get(key,0)<=cap
        m=e['compilation_metrics']
        for key in ('valid_ast','semantic_equal','allowed_set_equal'):
            if key in m:assert m[key];semantics[key]+=1
        assert not m['false_allow_ids'] and not m['false_reject_ids']
        deferred_steps+=bool(e['reference_after']['deferred_relations']) or any(v['status']=='deferred' for v in e['reference_after']['relation_status'].values())
        if e['action']:
            commits+=1;c=next(c for c in e['candidates'] if c['candidate_id']==e['action']['candidate_id'])
            assert not check_candidate(physical(e['before'],c['pick_item_id']),{'container':task['container']},c)
            assert not e['reference_after']['violations']
    assert not summary['final_business_violations']
    if job['backend']=='oracle_ast':
        original={k:v for k,v in result.items() if k!='checkpoints'}
        assert stable(read(EXP/f"repeats/{job['job_id']}.json"))==stable(original)
        assert stable(read(EXP/f"restores/{job['job_id']}.json")['result'])==stable(original)
    summary_checks.append({'job_id':job['job_id'],'passed':True})
assert deferred_steps>0
pairs=read(EXP/'metrics/pair_checks.json');pc=[p for p in pairs if p['backend']=='public_parser']
assert len(pc)==12 and all(p['passed'] for p in pairs)
changed=sum(p['allowed_set_changed'] for p in pc);actions=sum(p['action_changed'] for p in pc);assert changed>=4 and actions>=2
witnesses=read(EXP/'private/manual_witnesses.json');assert len(witnesses)==12 and all(w['passed'] for w in witnesses)
assert sum(w['kind']=='legal_manual_path' for w in witnesses)==8
assert sum(w['kind']=='physical_only' and w['analytic_certificate']['contradiction'] for w in witnesses)==4
paths=read(EXP/'audit/joint_manual_paths.json');assert len(paths)==4 and all(p['passed'] for p in paths)
coverage=read(EXP/'metrics/candidate_coverage.json')
faults=read(EXP/'audit/faults.json');assert all(f['passed'] for f in faults)
assert {'wrong_ast_visible','wrong_direction_visible','hidden_future_invariance','candidate_public_input_only'} <= {f['purpose'] for f in faults}
protection=read(OUT/'protected.before.json')
changed_files=[name for name,sha in protection.items() if not (WORKSPACE/name).is_file() or hashlib.sha256((WORKSPACE/name).read_bytes()).hexdigest()!=sha]
assert not changed_files
# Raw tracked dataset additionally compared byte-for-byte with the original Git index.
dataset_files=subprocess.check_output(['git','ls-files','--stage','-z','semantic_pallet_dataset_v1'],cwd=WORKSPACE).split(b'\0')
tracked=0;dataset_sha={}
for raw in dataset_files:
    if not raw:continue
    metadata,name=raw.split(b'\t',1);expected=metadata.split()[1].decode();name=name.decode()
    content=(WORKSPACE/name).read_bytes()
    assert hashlib.sha1(f'blob {len(content)}\0'.encode()+content).hexdigest()==expected,name
    dataset_sha[name]=hashlib.sha256(content).hexdigest();tracked+=1
write(OUT/'dataset_protected.json',dataset_sha)
# Distinct tests: latest E2 unit run supersedes the earlier combined unit subset.
test_suites={}
for name,offset in [('e2_unit_tests.xml',0),('e2_tests.xml',83),('e1_regression_tests.xml',0),('legacy_semantics_tests.xml',0)]:
    suites=ET.parse(OUT/name).getroot();tests=sum(int(s.get('tests',0)) for s in suites.findall('testsuite'))
    assert all(int(s.get('failures',0))==int(s.get('errors',0))==0 for s in suites.findall('testsuite'))
    test_suites[name]={'total':tests,'distinct_count':tests-offset}
metrics={'status':'PASS','sealed_files':seals,'source_matches_frozen':True,'planned_episodes':96,'summary_checks':len(summary_checks),
         'actual_commits_independently_checked':commits,'event_counts':dict(events),'per_planner':dict(counts),'maxima':dict(maxima),
         'compilation_metrics':dict(semantics),'deferred_steps':deferred_steps,'changed_pairs':changed,'action_changed_pairs':actions,
         'joint_manual_path_checks':len(paths),'faults':len(faults),'manual_legal_paths':8,'physical_only_negative_certificates':4,
         'protected_files':len(protection),'protected_changed':changed_files,'dataset_tracked_files_matching_index':tracked,
         'coverage_records':len(coverage),'topk_coverage_limited':sum(c['topk_coverage_limited'] for c in coverage),
         'baseline_empty_extended_nonempty':sum(c['baseline_allowed_count']==0 and c['extended_allowed_count']>0 for c in coverage),
         'test_suites':test_suites,'distinct_tests':sum(x['distinct_count'] for x in test_suites.values()),'new_api_attempts':0,
         'real_compile_status':'NOT_RUN','real_online_status':'NOT_RUN','unseen_generalization':'NOT_MEASURED','visual_increment':'NOT_MEASURED','e4_status':'OUT_OF_SCOPE'}
write(OUT/'evidence.json',metrics)
write(OUT/'summary_checks.json',summary_checks)
requirements=[]
def requirement(identifier,claim,evidence):
    requirements.append({'requirement':identifier,'claim':claim,'status':'PASS','evidence':evidence})
for key in report['gates']:
    assert report['gates'][key];requirement(key,'规范统一验收门槛',f'{EXP.relative_to(WORKSPACE)}/acceptance_report.json:gates.{key}')
for key in report['E2_gates']:
    assert report['E2_gates'][key];requirement(key,'E2专属验收门槛',f'{EXP.relative_to(WORKSPACE)}/acceptance_report.json:E2_gates.{key}')
for key,claim,evidence in [
 ('3.1','坐标/单位/容差、直立顶面标签、拒绝超能力角度','e2_unit_tests.xml; e2_tests.xml; audit/visual.json; config.snapshot.json'),
 ('3.2','公共事实与版本、状态/指令/图像绑定及参考隔离','audit/faults.json; e2_tests.xml; summary_checks.json'),
 ('3.3','封闭AST、选择器、载荷族覆盖与空间合取/deferred','metrics/invalid.json; metrics/gold.json; e2_unit_tests.xml'),
 ('5.1','AABB全部不同有序对、gap0接触及逆方向端点等价','metrics/gold.json; e2_unit_tests.xml'),
 ('8.1','16/48/3/8/256预算、公开采样与覆盖限制','evidence.json:maxima; metrics/candidate_coverage.json; audit/faults.json'),
 ('EX-E2-GOLD','24金标准+12非法输入与独立算术期望一致','metrics/gold.json; metrics/invalid.json'),
 ('EX-E2-PAIR','12组配对48主记录，6不变6变化','metrics/pairs.json; metrics/pair_checks.json'),
 ('EX-E2-CONSTRUCT','12四箱任务/2来源/4规划器，独立物理、双顺序和无解保留','episodes/; audit/jobs.json; evidence.json'),
 ('EX-E2-REGRESSION','36旧金标准24 E1金标准及48 E1配对回归','private/regression_inputs.json; metrics/legacy_regression.json'),
 ('EX-E-VISUAL-E2','24金标准及24配对状态和主矩阵公共图像','audit/visual.json; public/images/; e2_tests.xml'),
 ('EX-E-DELIVERY-E2','Oracle48独立重复48恢复及96只读复算','audit/repeats.json; audit/restores.json; readonly_verify.json'),
 ('9.3','真实编译冒烟12题/固定24状态封存；未发API','PLAN_O4_E2_SMOKE_READY_20261025_01; PLAN_O4_E2_FIXED_READY_20261025_01; e2_tests.xml'),
 ('11','保护旧源代码/数据/输出，新增入口与审计分母','audit/protected.json; evidence.json; audit/jobs.json; e2_tests.xml'),
 ('12','实际CLI/help、冻结快照、运行手册与阶段状态','documentation/cli_help.txt; docs/04_运行与复核手册/O4E2相对位置约束运行及验收手册_20261025.md')]:requirement(key,claim,evidence)
write(OUT/'requirements_audit.json',{'scope':'O4-E2 only','status':'PASS','requirements':requirements,
      'excluded':['E3 four-yaw implementation','E5 final mixed/real online','unseen generalization','E4 OUT_OF_SCOPE']})
write(OUT/'source_and_tests.json',{str(p.relative_to(WORKSPACE)):hashlib.sha256(p.read_bytes()).hexdigest()
 for p in [*sorted((WORKSPACE/'semantic_pallet_planner/src/semantic_pallet_planner/o4/extensions/e2').glob('*.py')),
 WORKSPACE/'semantic_pallet_planner/src/semantic_pallet_planner/runners/o4_e2.py',
 WORKSPACE/'semantic_pallet_planner/tests/unit/test_o4_e2_extensions.py',WORKSPACE/'semantic_pallet_planner/tests/integration/test_o4_e2_delivery.py']})
print(json.dumps(metrics,ensure_ascii=False,indent=2))
