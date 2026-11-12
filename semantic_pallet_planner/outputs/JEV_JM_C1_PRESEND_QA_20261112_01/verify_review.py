"""Independent stdlib audit of failed pre-send receipt; no business imports."""
import hashlib,json,subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3];OUT=Path(__file__).resolve().parent
B=ROOT/'semantic_pallet_planner/outputs/JEV_JM1_C1_PRESEND_CHECK_20261112_01'
F=ROOT/'semantic_pallet_planner/outputs/JEV_JM1_B2_FREEZE_CLOSURE_20261112_01'
def load(p):return json.loads(p.read_text())
def sha(raw):return hashlib.sha256(raw).hexdigest()
def digest(v):return sha(json.dumps(v,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode())
manifest=load(B/'delivery_manifest.json')
for row in manifest['files']:
 raw=(ROOT/row['path']).read_bytes();assert sha(raw)==row['sha256'] and len(raw)==row['bytes'],row['path']
snapshot=load(F/'source_manifest.json');package=ROOT/'semantic_pallet_planner/src/semantic_pallet_planner'
actual={p.relative_to(package).as_posix():sha(p.read_bytes()) for p in sorted(package.rglob('*')) if p.is_file() and p.suffix in ('.py','.json') and not {'tests','__pycache__'}.intersection(p.relative_to(package).parts)}
assert actual==snapshot
receipt=load(B/'preflight_receipt.json');checks={r['check']:r for r in receipt['checks']};f=load(F/'formal_freeze.json')
assert f['receipt_digest']==digest({k:v for k,v in f.items() if k!='receipt_digest'})
expected='/home/cyw/anaconda3/bin/python';used='/home/cyw/anaconda3/bin/python3'
assert checks['monitor_environment_identity']['details']==[{'field':'/execution_environment/executable','saved':expected,'current':used}]
assert checks['monitor_environment_identity']['status']=='FAIL'
assert checks['python_dependencies_source']['details']['actual']==checks['python_dependencies_source']['details']['saved']==f['runtime_identity']
assert checks['python_dependencies_source']['details']['executable']==used
for j,r in zip(f['jobs'],receipt['jobs']):
 e=load(ROOT/j['execution_ref']['path']);assert e['config']['stability_monitor']['execution_environment']['executable']==expected
 assert j['execution_digest']==digest(e) and r['job_id']==j['job_id'] and r['execution_ref']==j['execution_ref']
 assert r['storage_root']==j['storage_root'] and r['max_sends']==j['max_sends']
 assert r['status']=='NOT_RUN' and r['actual_sends']==0
assert len(receipt['jobs'])==6 and sum(r['max_sends'] for r in receipt['jobs'])==103
assert not receipt['execution_authorized'] and receipt['real_calls_authorized']==0 and not any(receipt['operations'].values())
commands=load(B/'commands_and_results.json')
fail=[c for c in commands['commands'] if c.get('exit_code')==1];assert len(fail)==1 and 'jm13_monitor_identity' in fail[0]['error']
assert fail[0]['command'].split()[2]=='python3'
pending=load(B/'pending_execution_checklist.json');assert pending['authorized_sends']==0 and not pending['execution_authorized']
assert pending['jobs']==receipt['jobs'] and pending['global_baseline_upper']==103
source=(ROOT/'semantic_pallet_planner/src/semantic_pallet_planner/jev_select/stability/runtime.py').read_text()
assert "'executable':sys.executable" in source
collector=(B/'verify_preflight.py').read_text();assert "status='STOP_MONITOR_IDENTITY_MISMATCH'" in collector
assert not subprocess.check_output(['git','diff','8b15b534','HEAD','--','semantic_pallet_planner/src','semantic_pallet_planner/tests'],cwd=ROOT)
result={'version':'jm_c1_presend_independent_qa_checks_v1','head':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),'delivery_files':len(manifest['files']),'frozen_runtime_files':len(actual),'freeze_identity':f['receipt_digest'],'confirmed_source_of_identity_field':'stability.runtime.environment uses sys.executable','reported_only_monitor_delta':checks['monitor_environment_identity']['details'],'all_six_saved_executables':expected,'operation_side_failed_invocation':used,'baseline_jobs':6,'baseline_cap':103,'operations':'6NOT_RUN and0 sends are operation-side archived claims checked for internal consistency','actual_Linux_executable_presence_or_alias_identity':'NOT_VERIFIED_FROM_MAC','production_validator_current_run':'NOT_RUN','collector_status_behavior':'old script hardcodes STOP; do not treat rerun output as automatic current status','root_cause_scope':'invocation path differs from frozen environment; not a demonstrated source/algorithm defect','status':'PASS_SAVED_STOP_EVIDENCE_REVIEW_SEND_READINESS_NOT_READY'}
(OUT/'static_checks.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n');print(json.dumps(result,ensure_ascii=False))
