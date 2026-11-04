"""JN2 offline execution guard; no credential reads or network permitted."""
import json
import os
from pathlib import Path
import runpy
import sys

base=Path.cwd().resolve()
counts={'network_attempts_blocked':0,'credential_reads_blocked':0,'historical_writes_blocked':0}
protected=[base/'semantic_pallet_planner/outputs/JEV_JN2_20261104_01',base/'semantic_pallet_planner/outputs/JEV_JN1_20261103_03',base/'semantic_pallet_planner/outputs/DATA_JEV_PACKAGING_LOAD_20261102_02']
credentials={'typesafe_api_key.md','deepseek_api_key.md','.env'}
def audit(event,args):
    if event in ('socket.connect','socket.getaddrinfo','socket.connect_ex'):
        counts['network_attempts_blocked']+=1;raise RuntimeError('JN2_NETWORK_FORBIDDEN')
    if event=='open' and isinstance(args[0],(str,bytes,os.PathLike)):
        path=Path(os.fsdecode(args[0])).resolve();mode=args[1] or '';flags=args[2]
        writing=any(c in mode for c in 'wax+') or bool(flags & (os.O_WRONLY|os.O_RDWR|os.O_CREAT|os.O_TRUNC))
        if path.name in credentials:
            counts['credential_reads_blocked']+=1;raise RuntimeError('JN2_CREDENTIAL_FORBIDDEN')
        if writing and any(path.is_relative_to(p) for p in protected):
            counts['historical_writes_blocked']+=1;raise RuntimeError('JN2_PARENT_WRITE_FORBIDDEN')
    if event in ('os.remove','os.rename','os.rmdir'):
        paths=[Path(os.fsdecode(a)).resolve() for a in args[:2] if isinstance(a,(str,bytes))]
        if any(x.is_relative_to(p) for x in paths for p in protected):
            counts['historical_writes_blocked']+=1;raise RuntimeError('JN2_PARENT_MUTATION_FORBIDDEN')
receipt=Path(sys.argv[1]);module=sys.argv[2];sys.argv=[module,*sys.argv[3:]]
sys.addaudithook(audit)
try:
    if module=='script':
        script=sys.argv[1];sys.argv=sys.argv[1:]
        runpy.run_path(script,run_name='__main__')
    else:
        runpy.run_module(module,run_name='__main__',alter_sys=True)
finally:
    receipt.parent.mkdir(parents=True,exist_ok=True)
    receipt.write_text(json.dumps({'guard':'offline+credential+parent-readonly','counts':counts},indent=2)+'\n')
