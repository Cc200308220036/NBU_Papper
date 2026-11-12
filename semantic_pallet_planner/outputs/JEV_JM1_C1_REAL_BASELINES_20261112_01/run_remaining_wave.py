"""Sequential registered slots only. Stop on first technical failure; no retries."""
import os,sys,subprocess,json
from pathlib import Path
out=Path(__file__).resolve().parent
wave=int(sys.argv[1]);jobs=[2,3] if wave==1 else [4,5,6]
assert wave in (1,2)
for i in jobs:
 prior=json.loads((out/f'job_{i-1}_receipt.json').read_text());assert prior['technical_valid'] is True
 with (out/f'job_{i}.stdout').open('x') as stdout,(out/f'job_{i}.stderr').open('x') as stderr:
  p=subprocess.run([sys.executable,str(out/'run_registered_job.py'),str(i)],stdout=stdout,stderr=stderr)
 if p.returncode!=0:sys.exit(p.returncode)
 receipt=json.loads((out/f'job_{i}_receipt.json').read_text())
 print(json.dumps(dict(job=i,reason=receipt.get('reason'),technical_valid=receipt['technical_valid'],requests=receipt.get('counts',{}).get('requests')),ensure_ascii=False),flush=True)
 if not receipt['technical_valid']:sys.exit(2)
