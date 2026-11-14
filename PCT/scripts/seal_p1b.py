"""Seal completed P1-B facts, without numerical/business dispatch or install."""
import ast
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'PCT/src'))
from pct_baseline.contracts import read,sha,write_new,digest

OUT=ROOT/'PCT/outputs/PCT_P1_B_20261114_01'
REL=str(OUT.relative_to(ROOT))
PUBLIC='semantic_pallet_planner/src/semantic_pallet_planner/jev_select/'
ALLOWED=[PUBLIC+name for name in ['packaging_versions.py','selector.py','episode.py','stability/monitor.py']]


def put(name,value):write_new(OUT/(name+'.json'),value)


def main():
    changed=subprocess.run(['git','diff','--name-only'],cwd=ROOT,text=True,capture_output=True,check=True).stdout.splitlines()
    assert {p for p in changed if not p.startswith('PCT/')}==set(ALLOWED)
    subprocess.run(['git','diff','--check'],cwd=ROOT,check=True)
    initial=read(OUT/'initial_source_hashes.json')
    # The pre-existing integration-test change belongs to P1-A, not this stage.
    protected='PCT/tests/test_b1_integration.py'
    assert sha(ROOT/protected)==initial[protected]
    final=OUT/'final_verification'
    new=json.loads(read(final/'p1b_tests.json')['stdout']);old=json.loads(read(final/'p1a_regression.json')['stdout'])
    assert new=={'tests':11,'failures':0,'errors':0,'skips':0}
    assert old=={'tests':20,'failures':0,'errors':0,'skips':0}
    numeric=(OUT/'numeric_recheck.log').read_text();assert 'Ran 1 test' in numeric and '\nOK\n' in numeric
    episodes=[]
    for path in sorted((final/'cases').rglob('episode.json')):
        ep=read(path);rows=[e for e in ep['events'] if e.get('monitor')]
        kind=('CONTROL_STATUS_STUB' if 'control_stub' in str(path) else
            'EXCEPTION_INJECTION' if 'runtime_exception' in str(path) else
            'INVALID_SELECTION_NEGATIVE' if 'invalid_selection' in str(path) else 'REAL_EXACT_V3')
        episodes.append({'path':str(path.relative_to(ROOT)),'evidence_kind':kind,'reason':ep['checkpoint']['reason'],
            'planned_items':ep['summary']['loading']['planned_items'],'placed_items':ep['final_state']['placed_count'],
            'statuses':[e['monitor']['status'] for e in rows],
            'kernel_calls':sum(e['monitor']['result']['kernel_calls'] for e in rows),
            'selector_sources':[e['selection']['source'] for e in ep['events'] if e.get('selection')],
            'pending_ids':[p['item']['item_id'] for p in ep['final_state']['pending_items']]})
    assert len(episodes)==16
    put('case_index',{'version':'pct_p1b_case_index_v1','final_archive_episodes':16,'all_max_items':3,
        'rows':episodes,'direct_numeric_supplement':'numeric_recheck/test_real_kernel_boundaries_and_residuals/real_kernel.json',
        'interpretation':'constructions, not independent orders or research samples; stub and injected errors never called natural kernel outcomes'})
    put('baseline',{'branch':subprocess.run(['git','branch','--show-current'],cwd=ROOT,text=True,capture_output=True,check=True).stdout.strip(),
        'head':subprocess.run(['git','rev-parse','HEAD'],cwd=ROOT,text=True,capture_output=True,check=True).stdout.strip(),
        'initial_staged':'EMPTY','initial_modified':['PCT/README.md','PCT/docs/README.md','PCT/tests/test_b1_integration.py'],
        'initial_untracked':['PCT/docs/PCT_P1A_NBU环境补验_20261114_02.md','PCT/docs/PCT_P1A独立质检与P1B准入_20261114_01.md',
            'PCT/outputs/PCT_P1_A_NBU_20261114_02/','PCT/outputs/PCT_P1_A_QA_20261114_01/','PCT/scripts/verify_p1a_nbu.py'],
        'preservation':'pre-existing changes kept, test integration SHA unchanged; no pull/commit/push/stash/reset/checkout',
        'third_party_head':subprocess.run(['git','-C','Online-3D-BPP-PCT','rev-parse','HEAD'],cwd=ROOT,text=True,capture_output=True,check=True).stdout.strip(),
        'third_party_worktree':subprocess.run(['git','-C','Online-3D-BPP-PCT','status','--short'],cwd=ROOT,text=True,capture_output=True,check=True).stdout})
    put('authorization',{'version':'pct_p1b_authorization_v1','user_confirmation':[
        {'scope':'selector.py, episode.py, stability/monitor.py; B13-B15 small constructions; NBU necessary environment preparation','answer':'授权上述范围及环境准备'},
        {'scope':'packaging_versions.py exact selection/checkpoint version and Schema registration; source freeze impact disclosed','answer':'授权追加精确注册修改'}],
        'real_model_calls':0,'training':False,'subagents':False,'official_matrix':False,'P1_C':False})
    ext=[]
    for path in ALLOWED:
        before=initial[path];actual=sha(ROOT/path)
        ext.append({'path':path,'before_sha256':before,'after_sha256':actual,'status':'APPLIED_AUTHORIZED_P1_B',
            'freeze_impact':'new bytes require new runtime source identity; historical restored runs need original frozen implementation; no old signatures rewritten'})
    put('external_changes',{'version':'pct_p1b_external_changes_v1','public_files':ext,'other_public_changes':[],
        'preserved':['contracts.py','config.py','packaging_runtime.py','candidates.py','context.py','execution.py','numeric kernel/tolerances','old Schema/config bytes','third party','all historical output packages'],
        'registration_necessity':'Original commit_physical validates selection through public contracts; exact selection/checkpoint registration is necessary and separately authorized',
        'old_schema_protection':'172 resources byte equal to HEAD; final_verification/legacy_resources.json',
        'pre_existing_PCT_test_unchanged':{'path':protected,'sha256':initial[protected]}})
    patch=subprocess.run(['git','diff','--',*ALLOWED],cwd=ROOT,capture_output=True,check=True).stdout
    with (OUT/'public_changes.patch').open('xb') as stream:stream.write(patch)
    put('acceptance',{'version':'pct_p1b_acceptance_v1','status':'PASS','kind':'DEVELOPMENT_ACCEPTANCE_PENDING_INDEPENDENT_QA',
        'tests':{'P1B':new,'P1A_necessary_regression':old,'additional_same_numeric_test_recheck':{'tests':1,'passed':1},'unique_test_methods':31},
        'matrix':[
            {'id':'B13','status':'PASS','report_claim':'shared candidate/selection/monitor pipeline connected for capacity1',
             'implementation':'PCT execution admission and selector plus four public integration files; no second engine',
             'local_recheck':['empty pool','singleton original automatic result still real-monitored','multiple positions actually call GeometrySelector','0/90 exact actions','stackable and top-load hard boundaries','all four monitor states in explicit control stubs'],
             'archive':['final_verification/p1b_tests.json','case_index.json','final_verification/cases/'],
             'boundary':'geometry execution only; PCT network/Jev requests NOT_RUN'},
            {'id':'B14','status':'PASS','report_claim':'STABLE commits once; failure preserves box and installed prefix amounts',
             'implementation':'unchanged original commit_physical; public episode phase persistence and independent monitor copies',
             'local_recheck':['saved SELECTED precedes monitor; MONITORED precedes commit','actual commit count equals placed count','UNSTABLE/UNASSESSABLE/ERROR failures keep same before/after and no action','mass/volume/item totals unchanged at failed attempt','actual exact-v3 ancestor instability through public execution','runtime exception is saved ERROR; no second choice','mutating monitor copies does not mutate real state','damaged selection stops before monitor'],
             'archive':['final_verification/p1b_tests.json','case_index.json','final_verification/cases/'],
             'boundary':'uninterrupted constructions only; no cross-restart exactly-once guarantee'},
            {'id':'B15','status':'PASS','report_claim':'fixed exact-v3 algorithm/config/tolerances and actual numerical dependencies',
             'implementation':'exact_freeze/kernel_interface/validate_monitor reused; PCT preflight exact comparison; old numeric source untouched',
             'local_recheck':['SciPy1.15.3 _highspy._core imports, HiGHS1.8.0, original highs-ds configuration','real stable and unstable end-to-end','actual floating geometry returns UNASSESSABLE','independent per-box mass/moment checks from returned forces pass','disabled/tolerance/algorithm/dependency/physical/source drift rejected, including resealed monitor identity'],
             'archive':['pip_install_report.json','kernel_import.json.log','final_verification/exact_freeze.json','final_verification/environment.json','numeric_recheck/','numeric_recheck.log','final_verification/p1b_tests.json'],
             'boundary':'stub statuses and injected exception are explicitly labeled; not a proof for all numeric cases or true collapse'}],
        'P1_C':'NOT_RUN_NOT_ADMITTED','formal_22_task_execution':'NOT_RUN_NOT_ADMITTED','research_results':'NOT_RUN'})
    put('limitations',{'version':'pct_p1b_limitations_v1','status':'B13_B15_PASS_ONLY','independent_quality_review':'PENDING',
        'admitted':'1-3 item explicit CONSTRUCTED_P1B_ONLY geometry jobs with matching execution binding and persistence sink',
        'not_implemented_or_admitted':['official dataset/matrix route','remote or PCT inference','journal/recovery/locks/concurrent exactly-once guarantees','resume or saved-event replay'],
        'not_run':['22-task official matrix','P3 actual-order diagnosis','P1C interruption/resume/locks/drift matrix','model request','training','weights download','third-party update'],
        'numerical_evidence':'Real exact-v3 stable/unstable/unassessable bounded cases and independent reaction checks; four-status control stubs + runtime exception injection separate',
        'candidate_coverage':'One real ancestor-instability example prescribes oracle-admissible public pools; does not establish original TopK reachability of that exact action',
        'vendor_warning':'NumPy2.3.5 emits original 2D np.cross deprecation warning; source/tolerances unchanged; warning preserved in raw log',
        'data':'historical data frozen/exposed; synthetic packaging capacity, feasibility UNKNOWN, admitted independent holdout=0 unchanged',
        'failures_preserved':[{'path':'tests_initial.log','meaning':'one test error: expected ValueError omitted actual jsonschema.ValidationError; invalid tolerance was correctly rejected; assertion fixed'},
                              {'path':'verification_failure.json','meaning':'verification parent import path error after 31 tests and pip checks passed; only unfinished metadata checks completed, original receipts untouched'}],
        'QA_carryforward':{'P0-Q01':'training actual segment/detach contract retained; numerical training validation NOT_RUN',
            'P0-Q02':'upstream dot-product pointer/glimpse clarification retained; network NOT_RUN','P0-Q03':'actual interpreter/SciPy/HiGHS/import/binary/AST evidence supplied',
            'P1A-Q01':'installation evidence separate from metadata/check script; no hardcoded claim of new installation on recheck',
            'P1A-Q02':'network/credential monkeypatch guard covers test process; reviewed subprocess code separately, no whole-process formal proof'}})
    commands=read(final/'commands_and_results.json')
    commands['additional_actual_commands']=[
        {'command':'"$NBU_PY" -m pip install --disable-pip-version-check --only-binary=:all: --report '+REL+'/pip_install_report.json scipy==1.15.3','exit_code':0,'stdout_log':'pip_install.log','installation':'actual installation, user-authorized'},
        {'command':'python3 PCT/scripts/build_schemas_p1b.py','exit_code':0,'scope':'exclusive new Schema resources, old resources unchanged'},
        {'command':'PYTHONPATH=PCT/src:semantic_pallet_planner/src "$NBU_PY" -m unittest discover -s PCT/tests -p test_p1b_execution.py -v','exit_code':1,'evidence':'tests_initial.log','state':'fixed test exception expectation; no production tolerance change'},
        {'command':'PYTHONPATH=PCT/src:semantic_pallet_planner/src "$NBU_PY" -m unittest discover -s PCT/tests -p test_p1b_execution.py -v','exit_code':0,'evidence':'tests_second.log','tests':8},
        {'command':'"$NBU_PY" PCT/scripts/verify_p1b.py --output '+REL+'/final_verification','exit_code':1,'evidence':'verification_failure.json','tests':'31 passed before metadata-stage import error'},
        {'command':'"$NBU_PY" PCT/scripts/verify_p1b.py --output '+REL+'/final_verification --complete-checks','exit_code':0,'scope':'only metadata/AST/old-resource/old-output checks; no test rerun'},
        {'command':'PCT_P1B_EVIDENCE_DIR='+REL+'/numeric_recheck PYTHONPATH=PCT/tests:PCT/src:semantic_pallet_planner/src "$NBU_PY" -m unittest test_p1b_execution.ExecutionTests.test_real_kernel_boundaries_and_residuals -v','exit_code':0,'evidence':'numeric_recheck.log','scope':'one targeted same numeric test after adding independent force/moment arithmetic'},
        {'command':'"$NBU_PY" PCT/scripts/seal_p1b.py','exit_code':0,'scope':'read completed receipts; AST/hash/link checks and new delivery metadata only'}]
    put('commands_and_results',commands)
    put('official_sources',{'access_date':'2026-11-14','sources':[
        {'url':'https://github.com/scipy/scipy/blob/v1.15.3/pyproject.toml','consumed_fact':'SciPy1.15.3 supports Python>=3.10 and NumPy>=1.23.5,<2.5'},
        {'url':'https://docs.scipy.org/doc/scipy-1.15.3/reference/optimize.linprog-highs-ds.html','consumed_fact':'HiGHS dual simplex method; actual runtime backend/import additionally checked locally'}],
        'distinction':'official metadata/API documentation is not local import/solver evidence'})
    paths=list((ROOT/'PCT/src').rglob('*.py'))+list((ROOT/'PCT/src').rglob('*.schema.json'))+list((ROOT/'PCT/configs').glob('*.json'))+list((ROOT/'PCT/tests').glob('*.py'))+list((ROOT/'PCT/scripts').glob('*.py'))+[ROOT/'PCT/pyproject.toml']+[ROOT/path for path in ALLOWED]
    # Freeze exact kernel and physical source identities as observed, not re-signed historical sources.
    frozen=read(final/'exact_freeze.json')
    kernel_root=ROOT/'semantic_pallet_planner/src/semantic_pallet_planner/jev_select/stability'
    for relative,expected in frozen['algorithm_identity']['files_sha256'].items():assert sha(kernel_root/relative)==expected
    for path in paths:
        if path.suffix=='.py':ast.parse(path.read_text(),filename=str(path.relative_to(ROOT)))
    for path in sorted(set(paths)):
        target=OUT/'code_snapshot'/path.relative_to(ROOT);target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(path,target)
    put('identity',{'version':'pct_p1b_identity_v1','baseline':'baseline.json','source_configuration_schema_sha256':{str(p.relative_to(ROOT)):sha(p) for p in sorted(set(paths))},
        'environment':read(final/'environment.json'),'algorithm_identity':frozen['algorithm_identity'],'kernel_config':frozen['kernel_config'],
        'kernel_config_digest':digest(frozen['kernel_config']),
        'data_scope':'16 archived constructed jobs (1-3 items each); not the original22 task matrix; original parent/derived data remain unchanged',
        'historical_derived_data_identity':'81c754a234f2083a5fb0bcbd55dd7ed905b292bab74ddf92f708d05d9219b29e',
        'construction_task_config_identity_by_job':[{ 'path':str(p.parent.relative_to(ROOT)), 'task_sha256':sha(p.parent/'task.json'),'task_digest':digest(read(p.parent/'task.json')),
            'config_sha256':sha(p.parent/'config.json'),'config_digest':digest(read(p.parent/'config.json'))} for p in sorted((final/'cases').rglob('episode.json'))],
        'history':'final_verification/historical_outputs.json','old_resources':'final_verification/legacy_resources.json','model_weights':'NOT_IMPLEMENTED_NOT_RUN',
        'P1_C_runtime_identity':'NOT_ADMITTED; snapshots not a validated journal/resume contract'})
    put('handoff',{'version':'pct_p1b_handoff_v1','unit':'P1-B B13-B15','status':'DEVELOPMENT_PASS_PENDING_INDEPENDENT_QA','stopped':True,
        'recipient':'independent quality review window','report':'PCT/docs/PCT_P1B公共选择监测提交与验收_20261114_01.md',
        'acceptance':REL+'/acceptance.json','manifest':REL+'/delivery_manifest.json','entry':['pct_baseline.execution.build_config','pct_baseline.execution.run_constructed','pct_baseline.execution.GeometrySelector'],
        'result':'capacity1 selection/save/independent exact-v3 monitor/save/original commit or terminate connected; 11 P1B+20 P1A tests pass; targeted independent numeric check pass',
        'scope':'small synthetic constructions only; real kernel vs stub records labeled in case_index',
        'missing_next_unit':'P1-C journal, locks and full interruption/resume audit NOT_IMPLEMENTED/NOT_RUN; no next-stage authorization inferred',
        'P1_C':'NOT_STARTED','P3':'NOT_STARTED','official_matrix':'NOT_RUN','model_requests':0,'training':0,'subagents':0})
    # Final document links are verified before the self-excluded manifest is written.
    report=ROOT/'PCT/docs/PCT_P1B公共选择监测提交与验收_20261114_01.md'
    for name in [ROOT/'PCT/README.md',ROOT/'PCT/docs/README.md',report]:
        for link in re.findall(r'\]\(([^)]+)\)',name.read_text()):
            if not link.startswith(('http:','https:','#')):
                target=name.parent/link.split('#')[0]
                assert target.exists() or target.resolve()==(OUT/'delivery_manifest.json').resolve(),link
    put('final_checks',{'status':'PASS','AST':'all PCT Python + four changed public files','links':'PASS',
        'external_modified_files':ALLOWED,'preexisting_test_bytes':'UNCHANGED','old_kernel_files':'UNCHANGED',
        'independent_numerical_supplement':'PASS','git_diff_check':'PASS','staged':'EMPTY','manifest_self_excluded':True})
    files=[p for p in OUT.rglob('*') if p.is_file() and p.name!='delivery_manifest.json']+paths+[ROOT/'PCT/README.md',ROOT/'PCT/docs/README.md',report]
    put('delivery_manifest',{'version':'pct_p1b_delivery_manifest_v1','self_excluded':True,
        'scope':'P1-B new package/snapshots plus current code/test/config/schema/report/navigation. Historical packages unchanged; old referenced source digests not re-signed.',
        'files':[{'path':str(p.relative_to(ROOT)),'size':p.stat().st_size,'sha256':sha(p)} for p in sorted(set(files)) if '__pycache__' not in p.parts]})


if __name__=='__main__':main()
