"""Read-only final saved-byte, budget, comparison and parent protection checks."""
import hashlib,json,collections
from pathlib import Path
from semantic_pallet_planner.jev_select.ledger import read
from semantic_pallet_planner.jev_select.contracts import digest
from semantic_pallet_planner.jev_select.experiment import source_manifest
from semantic_pallet_planner.jev_select import packaging_reanalysis as evaluation
from derive_delivery import guards,metric_view
OUT=Path(__file__).resolve().parent;ROOT=Path.cwd()
C1=Path('semantic_pallet_planner/outputs/JEV_JM1_C1_REAL_BASELINES_20261112_01');B2=Path('semantic_pallet_planner/outputs/JEV_JM1_B2_FREEZE_CLOSURE_20261112_01')
guards();manifest=read(OUT/'delivery_manifest.json')
for e in manifest['files']:
 raw=(ROOT/e['path']).read_bytes();assert hashlib.sha256(raw).hexdigest()==e['sha256'] and len(raw)==e['bytes'],e['path']
assert source_manifest()==read(B2/'source_manifest.json')
for parent in (C1,B2):
 for e in read(parent/'delivery_manifest.json')['files']:
  raw=Path(e['path']).read_bytes();assert hashlib.sha256(raw).hexdigest()==e['sha256'] and len(raw)==e['bytes'],e['path']
ledger=read(OUT/'branch_ledger.json')['jobs'];plan=read(C1/'fork_plan.json');summary=read(OUT/'full_denominators.json')
assert len(ledger)==len(plan['jobs'])==18
assert {r['job_id'] for r in ledger}=={j['job_id'] for j in plan['jobs']}
lookup={r['job_id']:r for r in ledger};totals=collections.Counter();journals=0
for r in ledger:
 ex=read(r['execution_ref']['path']);root=Path(r['storage_root'])
 permit=read(OUT/'permits'/(r['job_id']+'.json'))
 assert permit==dict(version='jev_jm_v13_send_permit_v1',execution_digest=digest(ex),allocation_id=ex['allocation_id'],max_sends=ex['max_sends'],authorized=True)
 if r['status']=='NOT_RUN':assert not root.exists();continue
 if r.get('saved_validation')!='PASS':continue
 activation=read(root/'activation.json');assert activation['execution']==ex
 previous=digest(activation);cp=activation['initial_checkpoint'];previous_events=[]
 for n,p in enumerate(sorted((root/'stages').glob('*.json')),1):
  journal=read(p);assert journal['sequence']==n and journal['previous_digest']==previous
  assert journal['record_digest']==digest({k:v for k,v in journal.items() if k!='record_digest'})
  assert journal['execution_digest']==digest(ex)
  cp=journal['checkpoint'];assert cp['events'][:len(previous_events)]==previous_events;previous_events=cp['events'];previous=digest(journal);journals+=1
 assert read(root/'checkpoint_head.json')['digest']==previous
 rows=read(root/'ledger/requests.json')['requests'];receipt=read(r['receipt_ref']['path'])
 assert metric_view(ex,cp,receipt,rows)==r['metrics']
 for p in (root/'ledger/contexts').glob('*.json'):assert read(p)['request_body']['state']['memories']==[]
 for row in rows:
  assert row['job_id']==ex['job_id']
  if r['technical_valid']:assert row['state']!='INTENT'
 totals.update({k:r['metrics'][k] for k in summary['totals']})
 assert r['metrics']['requests']<=ex['max_sends']
assert dict(totals)==summary['totals']
assert totals['requests']<=242
for slot,cap,count in [('r0',130,10),('r1',112,8)]:
 rs=[r for r in ledger if r['repeat_slot']==slot];assert len(rs)==count
 assert sum(r['metrics']['requests'] for r in rs if isinstance(r['metrics'],dict))<=cap
comparison_files=sorted((OUT/'comparisons').glob('*.json'))
assert len(comparison_files)==9
for p in comparison_files:
 c=read(p);a=lookup[c['reference_job']];b=lookup[c['alternative_job']]
 ea=read(a['execution_ref']['path']);eb=read(b['execution_ref']['path']);assert ea['start']==eb['start'] and ea['config']==eb['config'] and ea['task']==eb['task']
 if a['technical_valid'] and b['technical_valid'] and isinstance(a['metrics'],dict) and isinstance(b['metrics'],dict):assert evaluation.evaluate(a['metrics'],b['metrics'],rule_version=evaluation.RULE_VERSION)==c['evaluation']
 else:assert not c['evaluation']['comparison_valid'] and not c['technical_invalid_ranked']
for p in read(OUT/'evidence_levels_and_conflicts.json')['points']:
 if not p['repeat_registered']:assert p['evidence_grade']!='REPLICATED_LOCAL_OBSERVATION'
 if p['repeat_conflict']:assert p['evidence_grade']=='CONFLICTING_LOCAL_OBSERVATIONS'
assert read(OUT/'credential_safety.json')['status']=='PASS'
assert read(OUT/'handoff.json')['JM2_authorized']==0
print(json.dumps(dict(status='PASS',manifest_files=len(manifest['files']),frozen_source_files=len(source_manifest()),parent_manifests_unchanged=True,journal_rows=journals,jobs=18,pairs=9,requests=totals['requests'],saved_only=True,new_model_calls=0,new_LP=0)))
