"""Run original local suite with real network/credential and history writes blocked."""
import os
import sys
from pathlib import Path
import json

OUT=Path(__file__).resolve().parent
REPO=OUT.parents[2]
OLD=OUT.parent/'JEV_JN1_20261103_01'
# Remove sensitive environment entries without loading their values. Tests set
# their own explicitly synthetic tokens for injected urllib openers.
for name in list(os.environ):
    if any(part in name.lower() for part in ('api_key','token','secret','password','credential')):
        os.environ.pop(name, None)
sys.dont_write_bytecode=True
counters={'network_attempts':0,'credential_file_reads':0,'historical_writes':0}
def audit(event,args):
    if event in ('socket.connect','socket.getaddrinfo','socket.gethostbyname','socket.sendto','socket.bind'):
        counters['network_attempts']+=1
        raise AssertionError('real network forbidden for source completion')
    if event=='open' and isinstance(args[0],(str,bytes)):
        name=os.fsdecode(args[0]);lower=name.lower()
        if any(x in lower for x in ('typesafe_api_key','deepseek_api.md','.env','credentials')):
            counters['credential_file_reads']+=1
            raise AssertionError('credential file forbidden for source completion')
        mode=args[1];flags=args[2]
        writing=(isinstance(mode,str) and any(x in mode for x in 'wax+')) or (isinstance(flags,int) and flags & (os.O_WRONLY|os.O_RDWR|os.O_CREAT|os.O_TRUNC|os.O_APPEND))
        if writing and Path(name).resolve().is_relative_to(OLD.resolve()):
            counters['historical_writes']+=1
            raise AssertionError('historical write forbidden')
sys.addaudithook(audit)
import pytest
paths=[
'semantic_pallet_planner/tests/unit/test_packaging_remote.py',
'semantic_pallet_planner/tests/unit/test_packaging_full_order.py',
'semantic_pallet_planner/tests/unit/test_stability_monitor.py',
'semantic_pallet_planner/src/semantic_pallet_planner/jev_select/tests/unit/test_packaging_runtime.py',
'semantic_pallet_planner/src/semantic_pallet_planner/jev_select/tests/unit/test_j4_transport.py']
code=pytest.main([*paths,'-q','--disable-warnings','--junitxml='+str(OUT/'tests/current_local.xml')])
(OUT/'tests/offline_guards.json').write_text(json.dumps({'version':'jev_source_completion_test_guards_v1','counters':counters,
 'real_api_requests':0,'real_credential_loading':False,'synthetic_token_note':'transport tests only set explicit fixture tokens with mock urllib opener',
 'pytest_exit_code':int(code)},indent=2)+'\n')
raise SystemExit(code)
