"""Network/credential/old-artifact ban for explicitly Fake engineering scripts."""
import json,os,runpy,sys
from pathlib import Path
counts={'network':0,'credential':0,'historical_write':0}
repo=Path.cwd().resolve();old=[repo/'semantic_pallet_planner/outputs'/n for n in ('JEV_JN4_20261105_01','JEV_JN3_20261105_01','JEV_JN3_20261104_01','JEV_JN3_20261104_02','DATA_JEV_PACKAGING_LOAD_20261102_02')]
def audit(event,args):
    if event in ('socket.connect','socket.connect_ex','socket.getaddrinfo'):
        counts['network']+=1;raise RuntimeError('NETWORK_FORBIDDEN')
    if event=='open' and isinstance(args[0],(str,bytes,os.PathLike)):
        path=Path(os.fsdecode(args[0]));name=path.name.lower()
        if name in ('.env','typesafe_api_key.md','typwsafe_api_key.md','deepseek_api.md') or name.endswith('_api_key.md'):
            counts['credential']+=1;raise RuntimeError('CREDENTIAL_FORBIDDEN')
        mode=args[1] or '';flags=args[2]
        if (any(c in mode for c in 'wax+') or flags&(os.O_WRONLY|os.O_RDWR|os.O_CREAT|os.O_TRUNC)) and any(path.resolve().is_relative_to(p) for p in old):
            counts['historical_write']+=1;raise RuntimeError('HISTORICAL_WRITE_FORBIDDEN')
sys.addaudithook(audit)
receipt=Path(sys.argv[1]);script=sys.argv[2];sys.argv=sys.argv[2:];status='ERROR'
try:
    runpy.run_path(script,run_name='__main__');status='PASS'
finally:receipt.write_text(json.dumps({'status':status,'counts':counts,'scope':'explicit constructed tasks + Fake transport only'},indent=2)+'\n')
