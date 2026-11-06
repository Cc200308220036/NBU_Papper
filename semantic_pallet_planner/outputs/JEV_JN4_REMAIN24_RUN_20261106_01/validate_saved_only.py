"""Validate after all jobs have terminated; does not acquire execution ownership."""
import datetime
import subprocess
import sys
from pathlib import Path
from semantic_pallet_planner.jev_select.ledger import read,write
from semantic_pallet_planner.jev_select.packaging_source_audit import sha
B=Path(__file__).parent;run=Path('semantic_pallet_planner/outputs/JEV_JN4_REMAIN24_20261106_01/run')
statuses=[read(f) for f in (run/'jobs').glob('*/status.json')]
assert len(statuses)==24 and all(s['state']=='FINISHED' for s in statuses)
assert all(r['state'] not in ('INTENT','SENDING') for r in read(run/'request_ledger/requests.json')['requests'])
manifest_before=sha(run/'delivery_manifest.json');summary_before=sha(run/'summary.json')
start=datetime.datetime.now(datetime.timezone.utc).isoformat()
command=[sys.executable,'-m','semantic_pallet_planner.jev_select.packaging_exact_orders','validate-run','--output',str(run)]
with (B/'validate_run.log').open('w') as log:
 result=subprocess.run(command,stdout=log,stderr=subprocess.STDOUT,check=False)
write(B/'saved_validation.json',{'command':'PYTHONPATH=semantic_pallet_planner/src python3 -m semantic_pallet_planner.jev_select.packaging_exact_orders validate-run --output '+str(run),'returncode':result.returncode,'started_at':start,'checked_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'dispatch':'NONE_SAVED_FACTS_ONLY','all24_jobs_closed_before_validation':True,'run_manifest_unchanged_during_validation':manifest_before==sha(run/'delivery_manifest.json'),'run_summary_unchanged_during_validation':summary_before==sha(run/'summary.json')})
print('independent saved validation exited',result.returncode)
raise SystemExit(result.returncode)
