"""One authorized invocation of the frozen run; no retries, probes or plan changes."""
import os
import subprocess
import sys
import datetime
from pathlib import Path
from semantic_pallet_planner.jev_select.transport import credential
from semantic_pallet_planner.jev_select.contracts import JevSelectError
from semantic_pallet_planner.jev_select.ledger import read,write
b=Path(__file__).parent
plan='semantic_pallet_planner/outputs/JEV_JN4_REMAIN24_20261106_01/plan'
p=read(Path(plan)/'plan.json');name=p['jobs'][2]['config']['api_key_env']
env=os.environ.copy()
try:
    if env.get(name):
        key=credential(name);source='EXISTING_ENVIRONMENT'
    else:
        key=credential(name,'typesafe_api_key.md');source='EXISTING_CREDENTIAL_FILE_VIA_CREDENTIAL_LOADER'
except Exception:
    write(b/'credential_status.json',{'configured':False,'secret_logged':False})
    raise SystemExit('credential configuration failed; no run invoked')
env[name]=key
write(b/'credential_status.json',{'configured':True,'source':source,'secret_logged':False})
command=[sys.executable,'-m','semantic_pallet_planner.jev_select.packaging_exact_orders','run','--plan',plan]
start=datetime.datetime.now(datetime.timezone.utc).isoformat()
write(b/'execution_command.json',{'command':'PYTHONPATH=semantic_pallet_planner/src python3 -m semantic_pallet_planner.jev_select.packaging_exact_orders run --plan '+plan,'started_at':start,'resumes':0,'probe_calls':0,'automatic_retries':0})
with (b/'execution.log').open('w') as log:
    result=subprocess.run(command,env=env,stdout=log,stderr=subprocess.STDOUT,check=False)
write(b/'execution_exit.json',{'returncode':result.returncode,'finished_at':datetime.datetime.now(datetime.timezone.utc).isoformat()})
print('frozen run exited',result.returncode)
raise SystemExit(result.returncode)
