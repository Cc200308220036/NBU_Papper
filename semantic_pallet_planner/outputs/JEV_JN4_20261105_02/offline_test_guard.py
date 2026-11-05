"""Network/credential ban around pytest; fixture episodes remain allowed."""
import json
import os
from pathlib import Path
import sys
import pytest
counts={'network':0,'credential':0}
def audit(event,args):
    if event in ('socket.connect','socket.connect_ex','socket.getaddrinfo'):
        counts['network']+=1;raise RuntimeError('JN4_A_NETWORK_FORBIDDEN')
    if event=='open' and isinstance(args[0],(str,bytes,os.PathLike)):
        name=Path(os.fsdecode(args[0])).name.lower()
        if name in ('.env','typesafe_api_key.md','typwsafe_api_key.md','deepseek_api.md') or name.endswith('_api_key.md'):
            counts['credential']+=1;raise RuntimeError('JN4_A_CREDENTIAL_FORBIDDEN')
sys.addaudithook(audit)
receipt=Path(sys.argv[1])
try:
    status=pytest.main(sys.argv[2:])
finally:
    receipt.write_text(json.dumps({'counts':counts,'exit_code':int(status) if 'status' in globals() else 'ERROR','scope':'constructed/development Fake only'},indent=2)+'\n')
raise SystemExit(status)
