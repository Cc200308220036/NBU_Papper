"""Verify this delivery and protected saved bytes only; stdout, no business imports."""
import json,hashlib
from pathlib import Path
out=Path(__file__).resolve().parent
load=lambda p:json.loads(Path(p).read_text())
sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
m=load(out/'delivery_manifest.json')
for row in m['files']:
 p=Path(row['path']);assert p.stat().st_size==row['bytes'] and sha(p)==row['sha256'],row['path']
protected=load(out/'protected_inputs.json')['files']
for p,s in protected.items():assert sha(p)==s,p
r=load(out/'preflight_receipt.json');assert r['status']=='PASS_READ_ONLY_PREFLIGHT_NOT_EXECUTION_AUTHORIZATION'
assert len(r['checks'])==37 and all(x['status']=='PASS' for x in r['checks'])
c=load(out/'commands_and_results.json')['commands'];assert [x['exit_code'] for x in c]==[0,1,1]
assert load(out/'original_validator.stdout')['bytes']=='PASS'
for stage in ['baseline','suffix']:
 assert (out/(stage+'_gate.stderr')).read_text().rstrip().endswith('SamplingError: FREEZE_NOT_A_SEND_PERMIT')
checklist=load(out/'pending_execution_checklist.json');assert not checklist['execution_authorized'] and checklist['authorized_sends']==0
assert [j['max_sends'] for j in checklist['jobs']]==[19,14,18,19,15,18]
assert all(j['status']=='NOT_RUN' and j['reason']=='NO_REAL_EXECUTION_AUTHORIZATION' for j in checklist['jobs'])
h=load(out/'handoff.json');report=Path(h['report']);assert report.is_file() and report.name in report.with_name('README.md').read_text()
f=load('semantic_pallet_planner/outputs/JEV_JM1_B2_FREEZE_CLOSURE_20261112_01/formal_freeze.json')
assert not Path(f['runtime_root']).exists()
print(json.dumps(dict(version='jm_c1_original_entry_delivery_check_v1',status='PASS',manifest_files=len(m['files']),protected_inputs=len(protected),checks=37,baseline_jobs_not_run=6,authorized_sends=0,runtime_output_created=False),ensure_ascii=False))
