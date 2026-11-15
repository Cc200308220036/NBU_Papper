"""Run only B23-B25 public fixtures/single-step tests, freezing sources first."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[2]


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--output',type=Path,required=True);args=ap.parse_args()
    out=args.output.resolve();out.mkdir(parents=True,exist_ok=False)
    def save(name,v):(out/name).write_text(json.dumps(v,indent=2,ensure_ascii=False)+'\n')
    def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
    sources=[ROOT/p for p in ['PCT/src/pct_baseline/geo_encoding.py','PCT/src/pct_baseline/geo_model.py','PCT/src/pct_baseline/geo_selector.py','PCT/tests/test_p2b_geometry.py','PCT/tests/p2b_fixtures.py','PCT/tests/p1b_fixtures.py','PCT/scripts/verify_p2b.py','PCT/tests/p2b_repeat_worker.py']]
    sources+=[ROOT/'PCT/src/pct_baseline/network_safety.py',*(ROOT/'PCT/src/pct_baseline/vendor/pct').glob('*.py')]
    before={str(p.relative_to(ROOT)):sha(p) for p in sources}
    for p in sources:
        q=out/'source_snapshot'/p.relative_to(ROOT);q.parent.mkdir(parents=True,exist_ok=True);q.write_bytes(p.read_bytes())
    save('pre_execution_identity.json',{'source_sha256':before,'head':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),'executable_sha256':sha(Path(sys.executable)),
        'weights_file':'PCT/outputs/PCT_P2_A_20261114_01/weight_tensors.json','weights_sha256':sha(ROOT/'PCT/outputs/PCT_P2_A_20261114_01/weight_tensors.json')})
    env=dict(os.environ,PYTHONPATH='PCT/src:PCT/tests:semantic_pallet_planner/src',PYTHONDONTWRITEBYTECODE='1',PCT_P2B_EVIDENCE_DIR=str(out/'tests'))
    cmd=[sys.executable,'-m','unittest','-v','test_p2b_geometry']
    p=subprocess.run(cmd,cwd=ROOT,env=env,text=True,capture_output=True)
    (out/'tests.log').write_text(p.stdout+p.stderr)
    repeats=[]
    if p.returncode==0:
        for i in range(2):
            rc=[sys.executable,'PCT/tests/p2b_repeat_worker.py','--evidence',str((out/'tests').relative_to(ROOT)),'--output',str((out/f'repeat_{i}.json').relative_to(ROOT))]
            rp=subprocess.run(rc,cwd=ROOT,env=env,text=True,capture_output=True)
            repeats.append({'command':['<NBU_PY>',*rc[1:]],'exit_code':rp.returncode,'stdout':rp.stdout,'stderr':rp.stderr})
        save('fresh_process_commands.json',repeats)
    after={str(p.relative_to(ROOT)):sha(p) for p in sources}
    save('commands_and_results.json',{'command':['<NBU_PY>',*cmd[1:]],'cwd':'repository root',
        'environment':{k:env[k] if k!='PCT_P2B_EVIDENCE_DIR' else str((out/'tests').relative_to(ROOT)) for k in ['PYTHONPATH','PYTHONDONTWRITEBYTECODE','PCT_P2B_EVIDENCE_DIR']},
        'exit_code':p.returncode,'source_unchanged_during_run':before==after,'scope':'no orders, candidates, LP, monitor, commit, remote or training'})
    assert before==after,'Source changed during tests'
    print(p.stdout+p.stderr,end='')
    for r in repeats:print(r['stdout']+r['stderr'],end='')
    sys.exit(p.returncode or (1 if any(r['exit_code'] for r in repeats) else 0))


if __name__=='__main__':main()
