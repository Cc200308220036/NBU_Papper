"""Recheck preserved corrupted archives via verify-only worker. No recovery/LP."""
import hashlib,json,os,subprocess
from pathlib import Path
Q=Path(__file__).parent;D=Path('PCT/outputs/PCT_P1_C_20261114_01')
def hashes(root):return {str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest() for p in root.rglob('*') if p.is_file()}
def main():
 py=json.loads((D/'environment.json').read_text())['executable'];records=[]
 paths=[D/'attempt_02'/('negative_'+s) for s in ('task','config','candidate','strategy','sequence','json','monitor','partial')]
 paths += [D/'saved_supplement'/('saved_'+s) for s in ('summary','episode_state','terminal_reason','model_placeholder','unknown_field')]
 for path in paths:
  before=hashes(path)
  r=subprocess.run([py,'PCT/tests/p1c_worker.py','verify','--root',str(path)],env=dict(os.environ,PYTHONDONTWRITEBYTECODE='1',PYTHONPATH='PCT/src:semantic_pallet_planner/src:PCT/tests'),text=True,capture_output=True)
  assert r.returncode==1,(path,r.stdout,r.stderr)
  assert before==hashes(path)
  records.append({'path':str(path),'exit_code':r.returncode,'stdout':r.stdout,'stderr':r.stderr,'unchanged':True})
 (Q/'negative_checks.json').write_text(json.dumps(records,ensure_ascii=False,indent=2)+'\n')
 print('PASS:',len(records),'saved-corruption negatives rejected without writes')
if __name__=='__main__':main()
