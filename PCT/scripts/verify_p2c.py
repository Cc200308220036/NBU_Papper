"""Freeze pre-execution sources/environment; run B26-B28 only."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import importlib.metadata

ROOT=Path(__file__).resolve().parents[2]
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
    ap=argparse.ArgumentParser();ap.add_argument('--output',type=Path,required=True);a=ap.parse_args();out=a.output;out.mkdir(parents=True,exist_ok=False)
    def save(name,v):(out/name).write_text(json.dumps(v,indent=2,ensure_ascii=False)+'\n')
    paths=list(Path('PCT/src').rglob('*.py'))+list(Path('PCT/tests').glob('*p2c*.py'))+[Path('PCT/tests/p2b_fixtures.py'),Path('PCT/tests/p1b_fixtures.py'),Path(__file__).relative_to(ROOT)]
    paths += [Path('semantic_pallet_planner/src/semantic_pallet_planner/jev_select')/x for x in ['context.py','packaging_runtime.py','contracts.py']]
    before={str(p):sha(p) for p in paths}
    for p in paths:
        q=out/'source_snapshot'/p;q.parent.mkdir(parents=True,exist_ok=True);q.write_bytes(p.read_bytes())
    old=json.loads(Path('PCT/outputs/PCT_P2_B_20261115_01/environment.json').read_text());packages={k:importlib.metadata.version(k) for k in old['packages']}
    assert packages==old['packages']
    save('pre_execution_identity.json',{'source_sha256':before,'head':subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),'branch':subprocess.check_output(['git','branch','--show-current'],text=True).strip(),'python':sys.version,'executable':sys.executable,'executable_sha256':sha(Path(sys.executable)),'packages':packages,'matches_p2b_packages':True,'stage_weights':'generated deterministically before load/forward in test setUpClass; full tensors and pin archived in tests/model_manifest.json'})
    cmd=[sys.executable,'-m','unittest','-v','test_p2c_load'];env=dict(os.environ,PYTHONPATH='PCT/src:PCT/tests:semantic_pallet_planner/src',PYTHONDONTWRITEBYTECODE='1',PCT_P2C_EVIDENCE_DIR=str(out/'tests'))
    p=subprocess.run(cmd,env=env,text=True,capture_output=True);(out/'tests.log').write_text(p.stdout+p.stderr)
    unchanged=before=={str(p):sha(p) for p in paths}
    save('commands_and_results.json',{'command':['$NBU_PY',*cmd[1:]],'environment':{'PYTHONPATH':env['PYTHONPATH'],'PYTHONDONTWRITEBYTECODE':'1','PCT_P2C_EVIDENCE_DIR':str(out/'tests')},'exit_code':p.returncode,'source_unchanged':unchanged})
    print(p.stdout+p.stderr);assert unchanged;sys.exit(p.returncode)
if __name__=='__main__':main()
