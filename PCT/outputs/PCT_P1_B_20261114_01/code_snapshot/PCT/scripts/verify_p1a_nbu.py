"""P1-A conda follow-up: offline validation, exclusive new receipts only.

Allowed subprocesses: Git reads, pip freeze/check (no install/network), data CLI,
Python AST/import/unit tests. Unit construction is guarded against actual order,
candidate-generation, stability/LP and model-dispatch calls. Reads no credentials.
"""
import argparse
import ast
import hashlib
import importlib.metadata as metadata
import json
import os
from pathlib import Path
import platform
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'PCT/src'))
from pct_baseline.contracts import read,sha,write_new


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output',required=True);args=parser.parse_args()
    out=Path(args.output);out.mkdir(parents=True,exist_ok=True)
    env=dict(os.environ,PYTHONPATH='PCT/src:semantic_pallet_planner/src',PYTHONDONTWRITEBYTECODE='1')
    commands=[]
    def run(name,argv,display):
        result=subprocess.run(argv,cwd=ROOT,env=env,text=True,capture_output=True)
        row={'command':display,'exit_code':result.returncode,'stdout':result.stdout,'stderr':result.stderr}
        write_new(out/(name+'.json'),row);commands.append({'command':display,'exit_code':result.returncode,'evidence':str(out/(name+'.json'))})
        if result.returncode:raise RuntimeError(name+' failed; original log saved')
        return result.stdout
    run('pip_freeze',[sys.executable,'-m','pip','freeze','--all'],'"$NBU_PY" -m pip freeze --all')
    run('pip_check',[sys.executable,'-m','pip','check'],'"$NBU_PY" -m pip check')
    run('public_import',[sys.executable,'-c','import semantic_pallet_planner.jev_select.contracts; import numpy; print("public contracts and numpy imported")'],
        'PYTHONPATH=semantic_pallet_planner/src "$NBU_PY" -c <recorded public import check>')
    guard='''import sys,unittest
violations=[]
def profile(frame,event,arg):
    if event!='call':return
    module=frame.f_globals.get('__name__','');name=frame.f_code.co_name
    forbidden=(module.startswith('semantic_pallet_planner') and (
        name in ('run_episode','_run_episode_v2','commit_physical','assess_candidate','monitor_selected_action') or
        (name in ('generate','_generate') and ('.planner.' in module or '.o4.' in module)) or
        '.transport' in module)) or (module.startswith('scipy.optimize') and name=='linprog')
    if forbidden:
        violations.append([module,name]);raise AssertionError('unauthorized business dispatch '+str(violations[-1]))
sys.setprofile(profile)
result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.discover('PCT/tests'))
sys.setprofile(None)
assert result.wasSuccessful() and not result.skipped and result.testsRun==20,(result.testsRun,result.skipped)
assert not violations,violations
print('20 passed, zero skips; order/candidate-generation/LP/monitor/transport call violations:',violations)
'''
    write_new(out/'dispatch_guard_source.json',{'python_source':guard,'boundary':'constructed context/data only; no model/physical admission'})
    run('guarded_tests',[sys.executable,'-c',guard],'PYTHONPATH=PCT/src:semantic_pallet_planner/src "$NBU_PY" -c <dispatch_guard_source.json>')
    run('prepare_data',[sys.executable,'-m','pct_baseline.cli','prepare-data','--spec','PCT/configs/data_b1_v1.json','--output',str(out/'data')],
        'PYTHONPATH=PCT/src "$NBU_PY" -m pct_baseline.cli prepare-data --spec PCT/configs/data_b1_v1.json --output '+str(out/'data'))
    run('full_schema',[sys.executable,'-m','pct_baseline.cli','validate-data','--dataset',str(out/'data'),'--full-schema'],
        'PYTHONPATH=PCT/src "$NBU_PY" -m pct_baseline.cli validate-data --dataset '+str(out/'data')+' --full-schema')
    assert read(out/'data/dataset.json')==read(ROOT/'PCT/outputs/PCT_P1_A_20261114_01/data/dataset.json')
    files=list((ROOT/'PCT/src').rglob('*.py'))+list((ROOT/'PCT/tests').glob('*.py'))+list((ROOT/'PCT/scripts').glob('*.py'))
    public=ROOT/'semantic_pallet_planner/src/semantic_pallet_planner/jev_select'
    files += [public/name for name in ['packaging_versions.py','contracts.py','config.py','packaging_runtime.py','candidates.py','context.py']]
    for path in files:ast.parse(path.read_text(),filename=str(path.relative_to(ROOT)))
    write_new(out/'ast.json',{'status':'PASS','python':sys.version,'command':'ast.parse PCT Python and six integration public files','files':[str(p.relative_to(ROOT)) for p in files]})
    old=[]
    for directory in [public/'schemas',public/'configs']:
        paths=subprocess.run(['git','ls-tree','-r','--name-only','2e4edb32',str(directory.relative_to(ROOT))],cwd=ROOT,text=True,capture_output=True,check=True).stdout.splitlines()
        for path in paths:
            original=subprocess.run(['git','show','2e4edb32:'+path],cwd=ROOT,capture_output=True,check=True).stdout
            old.append({'path':path,'original_sha256':hashlib.sha256(original).hexdigest(),'actual_sha256':sha(ROOT/path)})
    assert all(r['original_sha256']==r['actual_sha256'] for r in old)
    write_new(out/'legacy_resources.json',{'status':'PASS','baseline':'2e4edb3215100f862a9e5c46fc03324ed1f41cb8','resources':old})
    history=[]
    for package in ['PCT_P0_CONTRACT_20261114_01','PCT_P0_QA_20261114_01','PCT_P1_A_20261114_01']:
        for path in (ROOT/'PCT/outputs'/package).rglob('*'):
            if path.is_file() and '__pycache__' not in path.parts:
                relative=str(path.relative_to(ROOT))
                original=subprocess.run(['git','show','HEAD:'+relative],cwd=ROOT,capture_output=True,check=True).stdout
                assert path.read_bytes()==original,relative
                history.append({'path':relative,'sha256':sha(path)})
    write_new(out/'historical_packages.json',{'status':'UNCHANGED','files':history})
    run('git_diff_check',['git','diff','--check'],'git diff --check')
    packages={name:metadata.version(name) for name in ['pip','numpy','jsonschema','attrs','referencing','jsonschema-specifications','rpds-py','typing-extensions']}
    write_new(out/'environment.json',{'executable':sys.executable,'executable_sha256':sha(sys.executable),'version':sys.version,
        'abi':sys.implementation.cache_tag,'platform':platform.platform(),'packages':packages,'locator':'Existing ~/miniconda3/envs/NBU/bin/python; conda itself not on PATH',
        'install_command':'"$NBU_PY" -m pip install --disable-pip-version-check jsonschema==4.23.0 numpy==2.3.5',
        'install_exit_code':0,'authorization':'User explicitly authorized needed dependency installation in NBU conda environment',
        'prior_environment':'Python3.12.16, pip26.2.2, jsonschema and numpy not installed',
        'scope':'Only named packages and necessary transitive dependencies; no torch/gym/scipy/pytest installed',
        'lock_evidence':'pip_freeze.json; installation metadata RECORD identities in package_records.json'})
    write_new(out/'package_records.json',{'packages':[{ 'distribution':name,'version':metadata.version(name),
        'RECORD_sha256':hashlib.sha256((metadata.distribution(name).read_text('RECORD') or '').encode()).hexdigest()} for name in packages]})
    write_new(out/'commands_and_results.json',{'commands':commands,'unit':'P1-A follow-up only','installation':'environment.json','boundary':'No credentials/model calls/order/candidate generation/LP; dispatch guard violations zero',
        'initial_tests':'tests_initial.log:18 passed before pinning original comparison; tests_final.log:20 passed after fixing test baseline and adding negative cases',
        'ast':'ast.json','legacy_resource_bytes':'legacy_resources.json','historical_outputs':'historical_packages.json'})


if __name__=='__main__':main()
