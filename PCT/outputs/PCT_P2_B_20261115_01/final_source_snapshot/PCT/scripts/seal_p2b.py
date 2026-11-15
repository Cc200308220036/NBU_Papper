"""Seal P2-B only; no inference, order, candidate, monitor, LP or transport."""
import ast
import hashlib
import json
from pathlib import Path
import re
import subprocess

ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'PCT/outputs/PCT_P2_B_20261115_01'
REPORT=ROOT/'PCT/docs/PCT_P2B几何编码选择与验收_20261115_01.md'


def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()


def save(name,value):(OUT/name).write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n')


def main():
    final=OUT/'attempt_06';test=final/'tests'
    command=json.loads((final/'commands_and_results.json').read_text())
    assert command['exit_code']==0 and command['source_unchanged_during_run']
    assert 'Ran 6 tests' in (final/'tests.log').read_text() and (final/'tests.log').read_text().rstrip().endswith('OK')
    repeat_commands=json.loads((final/'fresh_process_commands.json').read_text());assert len(repeat_commands)==2 and all(r['exit_code']==0 for r in repeat_commands)
    repeated=[json.loads((final/f'repeat_{i}.json').read_text()) for i in range(2)]
    assert repeated[0]['pid']!=repeated[1]['pid'] and all(v['matches_saved_single_step'] and v['model_calls']==1 and v['forbidden_calls']==[] for v in repeated)
    pre=json.loads((final/'pre_execution_identity.json').read_text())
    for path,h in pre['source_sha256'].items():assert sha(ROOT/path)==h,path
    # Old P2-A code identity stays byte-identical, including the numeric core.
    old=json.loads((ROOT/'PCT/outputs/PCT_P2_A_20261114_01/identity.json').read_text())
    assert all(sha(ROOT/p)==h for p,h in old['source_sha256'].items())
    rejections=json.loads((test/'rejections.json').read_text());assert len(rejections)==65
    model=json.loads((OUT/'model_manifest.json').read_text())
    assert model['weights_sha256']==sha(OUT/'weight_tensors.json')==pre['weights_sha256']
    assert (OUT/'model_manifest.json').read_bytes()==(test/'model_manifest.json').read_bytes()
    (OUT/'PCT_UPSTREAM_LICENSE').write_bytes((ROOT/'PCT/src/pct_baseline/vendor/pct/LICENSE').read_bytes())
    save('baseline.json',{'branch':subprocess.check_output(['git','branch','--show-current'],cwd=ROOT,text=True).strip(),
        'head':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
        'qa_historical_head':'b1a4ffbbcbf56f8ade8bd928f3ffaf9e4d40fe21','initial_worktree':'CLEAN','initial_staging':'EMPTY',
        'current_head_includes_p2a_qa':True,'predecessor_hash_check':'predecessor_checks.json'})
    matrix=[
      {'id':'B23','status':'PASS','scope':'geo6/8/6, float64 corner/Lref then float32, exact original candidate mapping, no sort/dedup/filter',
       'evidence':['attempt_06/tests/coordinates_False.json','attempt_06/tests/coordinates_True.json','attempt_06/tests/identical_symmetric_leaves.json','attempt_06/tests/empty_pallet.json','attempt_06/tests/capacity40_and_display_order.json']},
      {'id':'B24','status':'PASS','scope':'B1/B3, valid counts1/3/16, placed40 accepted and41 rejected,17 leaves rejected, padding exactly0, empty/singleton no inference, illegal outputs rejected',
       'evidence':['attempt_06/tests/batch.json','attempt_06/tests/route_0.json','attempt_06/tests/route_1.json','attempt_06/tests/route_3.json','attempt_06/tests/rejections.json']},
      {'id':'B25','status':'PASS','scope':'strict pinned model/feature/structure/core/file/parameter identities; repeat/reload and two fresh processes; saved single-step binding reuse without forward',
       'evidence':['model_manifest.json','weight_tensors.json','attempt_06/tests/repeatability.json','attempt_06/repeat_0.json','attempt_06/repeat_1.json','attempt_06/tests/saved_selection.json','attempt_06/tests/saved_public_inputs.json','attempt_06/tests/public_context_builder.json','attempt_06/tests/rejections.json']}]
    save('acceptance.json',{'version':'pct_p2b_acceptance_v1','status':'DEVELOPMENT_PASS_PENDING_INDEPENDENT_QA','matrix':matrix,
        'final_tests':{'methods':6,'skips':0,'expected_rejections':65,'fresh_single_step_processes':2},
        'weights':'RANDOM_INITIALIZATION_ENGINEERING_ONLY','order_execution':'NOT_RUN_NOT_ADMITTED','P2C_P3':'NOT_RUN_NOT_AUTHORIZED',
        'remote_requests_authorized':0,'remote_requests':0,'training_updates':0,'independent_QA':'PENDING'})
    save('limitations.json',{
        'execution':'No new execution permit or public protocol. Old P1-B/P1-C still geometry_b1 only; pct_local selection explicitly rejected by old validator.',
        'context_config':'Existing geometry config is a public-context validation carrier only, not a PCT run config. Independent single-step receipt binds actual PCT model identity.',
        'model':'P2-A engineering random weights only; no trained/externally downloaded weights or policy benefit.',
        'provenance_labels':'declared_TRAINED/EXTERNAL test manifests use the same known random weights and synthetic DECLARATION_ONLY evidence; not real trained/external models.',
        'fixtures':'Manually constructed public geometry capacity/bounds fixtures do not certify physical feasibility or natural candidate reachability; some 40-node fixtures deliberately repeat geometry.',
        'public_context':'One stored public observation+pool reconstructed by actual ContextBuilder and selected once; no new candidate generation or order replay.',
        'saved_selection':'Revalidates saved output legality and context/candidate/expected-model binding, not network recomputation, cryptographic authenticity, journal recovery or exactly-once order execution.',
        'raw_projection':'raw dict projection ignores unrelated fields; actual selector rejects unknown private fields using closed public context validation before projection.',
        'runtime':'CPU float32 Torch2.15.0 single-thread deterministic inference, fixed one-layer/one-head P2-A core; other runtimes unverified.',
        'cost':'inference_s includes identity checks plus local forward, not a benchmark or P3 cost analysis.',
        'NOT_RUN':['full orders','candidate generation','LP','monitor','commit','formal22 tasks','P2-C load extension','P3','training','weight downloads','remote requests','full native paper performance','PCT order recovery'],
        'P1C_Q01':'OPEN; clarify before P3 cost statistics without changing old events/seals.',
        'data':'Exposed data boundaries, synthetic packaging, satisfiability UNKNOWN and zero independent holdout sources unchanged.',
        'dependency_installations':0,'old_identity_or_seal_resigned':False})
    save('handoff.json',{'version':'pct_p2b_handoff_v1','status':'B23_B24_B25_DEVELOPMENT_PASS','independent_QA':'PENDING',
        'report':str(REPORT.relative_to(ROOT)),'manifest':'PCT/outputs/PCT_P2_B_20261115_01/delivery_manifest.json',
        'interfaces':{'encoder':'pct_baseline.geo_encoding.encode_geometry','loader':'pct_baseline.geo_model.load_model','selector':'pct_baseline.geo_selector.PCTGeoSelector','saved_validator':'pct_baseline.geo_selector.validate_saved_selection'},
        'model_version':'pct_adapted_geo_v1','model_manifest_sha256':sha(OUT/'model_manifest.json'),'weights_sha256':sha(OUT/'weight_tensors.json'),
        'single_step_record_version':'pct_geo_single_step_v1','order_execution_admitted':False,
        'next_action':'Independent quality review of P2-B only','next_stage_authorized':False,
        'P1C_Q01':'OPEN_NON_BLOCKING_FOR_P2B; before P3 costs','next_task_prompt':'NOT_CREATED','stop':True})
    operations=[]
    for name in ['attempt_01','attempt_02','attempt_03','attempt_04','attempt_05','attempt_06']:
        path=OUT/name
        commands=path/'commands_and_results.json'
        if commands.exists():operations.append({'attempt':name,'receipt':str(commands.relative_to(OUT)),'exit_code':json.loads(commands.read_text())['exit_code']})
        else:operations.append({'attempt':name,'command':'PYTHONPATH=PCT/src:PCT/tests:semantic_pallet_planner/src PYTHONDONTWRITEBYTECODE=1 PCT_P2B_EVIDENCE_DIR=PCT/outputs/PCT_P2_B_20261115_01/attempt_01 <NBU_PY> -m unittest -v test_p2b_geometry','exit_code':1,'log':'attempt_01.log'})
    save('commands_and_results.json',{'version':'pct_p2b_commands_v1','operations':operations,
        'fresh_processes':['attempt_05/fresh_process_commands.json','attempt_06/fresh_process_commands.json'],
        'final_status':'6 methods and 2 fresh single-step processes PASS; 65 expected rejections',
        'failures_preserved':{'attempt_01':'test helper omitted expected FileExistsError','attempt_03':'test incorrectly expected noncanonical Snapshot key order'},
        'later_successful_runs':'attempt_02 four methods; attempt_04 six; attempt_05 six+2 fresh; attempt_06 stores complete empty input/singleton reuse and runtime mutation negatives',
        'no_models_remote':True,'no_dependency_changes':True})
    sources=[ROOT/p for p in ['PCT/src/pct_baseline/geo_encoding.py','PCT/src/pct_baseline/geo_model.py','PCT/src/pct_baseline/geo_selector.py',
        'PCT/tests/test_p2b_geometry.py','PCT/tests/p2b_fixtures.py','PCT/tests/p2b_repeat_worker.py','PCT/scripts/verify_p2b.py','PCT/scripts/seal_p2b.py']]
    public_paths=['semantic_pallet_planner/src/semantic_pallet_planner/jev_select/'+p for p in ['context.py','selector.py','episode.py','execution.py','packaging_runtime.py','stability/monitor.py']]
    public_paths+=['PCT/src/pct_baseline/'+p for p in ['execution.py','recovery.py','protocol.py','network_safety.py']]
    save('identity.json',{'version':'pct_p2b_identity_v1','head':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
        'source_sha256':{str(p.relative_to(ROOT)):sha(p) for p in sources},'pre_execution_identity':'attempt_06/pre_execution_identity.json',
        'public_and_previous_code_sha256':{p:sha(ROOT/p) for p in public_paths},
        'p2a_frozen_source_files_unchanged':len(old['source_sha256']),
        'model_version':'pct_adapted_geo_v1','model_manifest_sha256':sha(OUT/'model_manifest.json'),'weights_sha256':sha(OUT/'weight_tensors.json'),
        'weight_origin':'PCT/outputs/PCT_P2_A_20261114_01/weight_tensors.json','weight_origin_label':'RANDOM_INITIALIZATION_ENGINEERING_ONLY',
        'feature_contract':model['feature_contract'],'architecture':model['architecture'],'runtime':model['runtime'],'environment':'environment.json'})
    for p in sources+[REPORT,ROOT/'PCT/README.md',ROOT/'PCT/docs/README.md']:
        if p.suffix=='.py':ast.parse(p.read_text())
        q=OUT/'final_source_snapshot'/p.relative_to(ROOT);q.parent.mkdir(parents=True,exist_ok=True);q.write_bytes(p.read_bytes())
    missing=[]
    for p in [REPORT,ROOT/'PCT/README.md',ROOT/'PCT/docs/README.md']:
        for link in re.findall(r'\]\(([^)]+)\)',p.read_text()):
            if link.startswith(('https:','http:','#')):continue
            q=(p.parent/link.split('#')[0]).resolve()
            if not q.exists() and q!=OUT/'delivery_manifest.json':missing.append({'document':str(p.relative_to(ROOT)),'target':link})
    assert not missing,missing
    assert subprocess.run(['git','diff','--check'],cwd=ROOT).returncode==0
    assert not subprocess.check_output(['git','diff','--cached','--name-only'],cwd=ROOT,text=True)
    assert not subprocess.check_output(['git','-C','Online-3D-BPP-PCT','status','--short'],cwd=ROOT,text=True)
    assert subprocess.check_output(['git','branch','--show-current'],cwd=ROOT,text=True).strip()=='dev/PCT'
    assert subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()=='52510de38d5d61f8c0165af6d558a2932cb8fa55'
    assert all(p.startswith('PCT/') for p in subprocess.check_output(['git','diff','--name-only'],cwd=ROOT,text=True).splitlines())
    save('final_delivery_checks.json',{'local_links':'PASS','source_AST':'PASS','source_matches_final_execution':'PASS',
        'old_p2a_code_sha256':'UNCHANGED','PCT_only_changes':True,'upstream_worktree':'CLEAN','index':'EMPTY','branch_head':'UNCHANGED',
        'git_diff_check':'PASS','dependencies':'UNCHANGED','manifest_self_excluded':True})
    files=[p for p in OUT.rglob('*') if p.is_file() and p!=OUT/'delivery_manifest.json']+sources+[REPORT,ROOT/'PCT/README.md',ROOT/'PCT/docs/README.md']
    save('delivery_manifest.json',{'version':'pct_p2b_delivery_manifest_v1','self_excluded':True,
        'scope':'P2-B new artifacts, own final code/report/navigation and snapshots only; no prior archive re-signing; paths are references, not digest cycles',
        'files':[{'path':str(p.relative_to(ROOT)),'size':p.stat().st_size,'sha256':sha(p)} for p in sorted(set(files))]})
    manifest=json.loads((OUT/'delivery_manifest.json').read_text())
    for f in manifest['files']:assert sha(ROOT/f['path'])==f['sha256'],f['path']
    print(f"P2-B development delivery sealed: {len(manifest['files'])} files verified; B23-B25 PASS, independent QA pending")


if __name__=='__main__':main()
