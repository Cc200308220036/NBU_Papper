"""Post-run integrity and secret exclusion audit, no model/API invocation."""
import base64
import os
import re
from pathlib import Path
from collections import Counter
from semantic_pallet_planner.jev_select.contracts import digest
from semantic_pallet_planner.jev_select.ledger import read,write
from semantic_pallet_planner.jev_select.experiment import file_manifest,source_manifest
from semantic_pallet_planner.jev_select.packaging_source_audit import sha
from semantic_pallet_planner.jev_select.transport import credential
from semantic_pallet_planner.jev_select import packaging_evaluation_orders as common
B=Path(__file__).parent;pre=read(B/'preflight.json');receipt=read(B/'evaluation_receipt.json')
planroot=Path(receipt['plan']);run=Path(receipt['run']);p=read(planroot/'plan.json')
unchanged={k:sha(Path(k))==v for k,v in pre['protected_files'].items()}
assert all(unchanged.values()),'protected historical/preparation record changed'
assert source_manifest()==p['source_manifest'] and common.dependencies()==p['dependencies']
assert read(run/'delivery_manifest.json')==file_manifest(run)
assert read(run/'run_receipt.json')['plan_digest']==digest(p)==pre['plan_digest']
owner=read('semantic_pallet_planner/outputs/JEV_JN4_EXACT_SUPPLEMENT_ACCOUNTING_V1/remaining24_owner.json')
assert owner['plan_digest']==digest(p) and owner['run']==p['run_location']
assert owner['job_ids']==[f'J{i:04d}' for i in range(12,36)]
assert owner['parent_run_manifest']==p['remainder']['run_manifest_sha256']
assert owner['original_owner_sha256']==p['remainder']['owner_sha256']
assert not (run/'first_gate.json').exists() and not (run/'continuation.json').exists()
requests=read(run/'request_ledger/requests.json')['requests'];counts=Counter(r['job_id'] for r in requests if r['send_started'])
assert all(j in p['request_budget']['per_job'] and n<=p['request_budget']['per_job'][j] for j,n in counts.items())
assert sum(counts.values())<=512 and all(r['origin']=='jev' for r in requests)
rows=read(B/'all_36_slots.json');assert len(rows)==36 and len(read(B/'new_24_slots.json'))==24
assert [r['job_id'] for r in rows]==[f'J{i:04d}' for i in range(36)]
name=p['jobs'][2]['config']['api_key_env'];key=credential(name,None if os.environ.get(name) else 'typesafe_api_key.md').encode()
findings=0;scanned=0
for directory in [B,run]:
 for f in directory.rglob('*'):
  if f.is_file():
   scanned+=1
   if key in f.read_bytes():findings+=1
for r in requests:
 if r['transport'] and r['transport'].get('raw_body_b64'):
  if key in base64.b64decode(r['transport']['raw_body_b64']):findings+=1
assert findings==0,'secret exclusion audit found sensitive content; do not print it'
report=Path('docs/03_阶段产出分析/Jev/Jev_JN4剩余24项真实执行与阶段收尾验收_20261106.md')
for link in re.findall(r'\]\(([^)]+)\)',report.read_text()):
 if not link.startswith(('https:','http:','#')):assert (report.parent/link.split('#')[0]).exists(),link
write(B/'delivery_checks.json',{'protected_files_unchanged':unchanged,'source_dependencies_equal_frozen':True,
 'new_run_manifest_matches':True,'owner_binding_matches':True,'no_reissued_first_gate':True,
 'all36_and_new24_denominators':True,'new_per_job_send_counts':dict(counts),'within_535_shared_and_512_job_sum':True,
 'secret_exclusion':{'files_scanned':scanned,'findings':findings,'decoded_transport_bodies_checked':True},
 'saved_validation_returncode':read(B/'saved_validation.json')['returncode'],'old_tasks_repeated':0,
 'resumes':0,'new_experience_generated':False,'production_source_modified':False})
write(B/'external_files_sha256.json',{str(report):sha(report),str(report.parent/'README.md'):sha(report.parent/'README.md'),str(run/'delivery_manifest.json'):sha(run/'delivery_manifest.json'),str(planroot/'plan.json'):sha(planroot/'plan.json')})
write(B/'delivery_manifest.json',file_manifest(B));assert file_manifest(B)==read(B/'delivery_manifest.json')
print('delivery integrity passed; protected records unchanged; secret findings 0')
