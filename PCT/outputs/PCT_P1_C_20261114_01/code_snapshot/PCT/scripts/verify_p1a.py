"""Write a new P1-A verification receipt only. Read scripts before invoking.

Subprocess allowlist: Git read-only, Python AST/import/unittest/data validation.
No install, credentials, network, model, generator invocation or LP. Only the
specified new evidence directory is written, using exclusive creation.
"""
import argparse
import ast
import hashlib
import importlib.metadata
import importlib.util
import json
import os
from pathlib import Path
import platform
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'PCT/src'))
from pct_baseline.contracts import read,sha,write_new,digest


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output',required=True)
    args=parser.parse_args();out=Path(args.output);out.mkdir(parents=True,exist_ok=False)
    env=dict(os.environ,PYTHONPATH='PCT/src:semantic_pallet_planner/src',PYTHONDONTWRITEBYTECODE='1')
    commands=[]
    def run(label,argv,display,expected=0):
        result=subprocess.run(argv,cwd=ROOT,env=env,text=True,capture_output=True)
        log={'command':display,'exit_code':result.returncode,'stdout':result.stdout,'stderr':result.stderr,
             'expected_exit':expected,'result':'EXPECTED' if (result.returncode==expected if isinstance(expected,int) else result.returncode!=0) else 'UNEXPECTED'}
        write_new(out/(label+'.json'),log);commands.append({'command':display,'exit_code':result.returncode,'log':str(out/(label+'.json')),'result':log['result']})
        return result
    run('baseline',['git','status','--short'],'git status --short')
    run('branch',['git','branch','--show-current'],'git branch --show-current')
    run('head',['git','rev-parse','HEAD'],'git rev-parse HEAD')
    run('staged',['git','diff','--cached','--stat'],'git diff --cached --stat')
    run('upstream',['git','-C','Online-3D-BPP-PCT','status','--short'],'git -C Online-3D-BPP-PCT status --short')
    run('upstream_head',['git','-C','Online-3D-BPP-PCT','rev-parse','HEAD'],'git -C Online-3D-BPP-PCT rev-parse HEAD')
    run('diff_check',['git','diff','--check'],'git diff --check')
    run('tests',[sys.executable,'-m','unittest','discover','-s','PCT/tests','-v'],'PYTHONPATH=PCT/src:semantic_pallet_planner/src "$PCT_PY" -m unittest discover -s PCT/tests -v')
    run('data',[sys.executable,'-m','pct_baseline.cli','validate-data','--dataset','PCT/outputs/PCT_P1_A_20261114_01/data'],
        'PYTHONPATH=PCT/src "$PCT_PY" -m pct_baseline.cli validate-data --dataset PCT/outputs/PCT_P1_A_20261114_01/data')
    run('full_schema',[sys.executable,'-m','pct_baseline.cli','validate-data','--dataset','PCT/outputs/PCT_P1_A_20261114_01/data','--full-schema'],
        'PYTHONPATH=PCT/src "$PCT_PY" -m pct_baseline.cli validate-data --dataset PCT/outputs/PCT_P1_A_20261114_01/data --full-schema',expected='nonzero')
    run('public_import',[sys.executable,'-c','import semantic_pallet_planner.jev_select.contracts'],
        'PYTHONPATH=semantic_pallet_planner/src "$PCT_PY" -c "import semantic_pallet_planner.jev_select.contracts"',expected='nonzero')
    guard="""import sys
from pct_baseline.dataset import validate_data
print(validate_data('.', 'PCT/outputs/PCT_P1_A_20261114_01/data'))
forbidden=[n for n in sys.modules if n.startswith(('semantic_pallet_planner','torch','gym','scipy','urllib.request','http.client'))]
assert not forbidden,forbidden
print('No planner, selector, generator, LP, transport or network client imported')
"""
    run('import_boundary',[sys.executable,'-c',guard],'PYTHONPATH=PCT/src "$PCT_PY" -c <recorded import_boundary guard>')
    changed=subprocess.run(['git','diff','--name-only'],cwd=ROOT,text=True,capture_output=True,check=True).stdout.splitlines()
    source_paths=[ROOT/path for path in changed if path.endswith('.py')]+list((ROOT/'PCT/src').rglob('*.py'))+list((ROOT/'PCT/tests').glob('*.py'))+list((ROOT/'PCT/scripts').glob('*.py'))
    ast_rows=[]
    for path in source_paths:
        try:ast.parse(path.read_text(),filename=str(path.relative_to(ROOT)));status='PASS';error=None
        except SyntaxError as exc:status='FAIL';error=str(exc)
        ast_rows.append({'path':str(path.relative_to(ROOT)),'status':status,'error':error})
    write_new(out/'ast.json',{'command':'"$PCT_PY" PCT/scripts/verify_p1a.py --output <new evidence directory> (ast.parse over changed public + PCT Python files)',
        'python':sys.version,'files':ast_rows})
    old_resources=[]
    for directory in ['semantic_pallet_planner/src/semantic_pallet_planner/jev_select/schemas','semantic_pallet_planner/src/semantic_pallet_planner/jev_select/configs']:
        paths=subprocess.run(['git','ls-files',directory],cwd=ROOT,text=True,capture_output=True,check=True).stdout.splitlines()
        for path in paths:
            original=subprocess.run(['git','show','HEAD:'+path],cwd=ROOT,capture_output=True,check=True).stdout
            old_resources.append({'path':path,'baseline_sha256':hashlib.sha256(original).hexdigest(),'actual_sha256':sha(ROOT/path),'unchanged':original==(ROOT/path).read_bytes()})
    write_new(out/'legacy_resources.json',{'status':'PASS' if all(r['unchanged'] for r in old_resources) else 'FAIL','resources':old_resources})
    packages={}
    for name in ['numpy','jsonschema','attrs','referencing','jsonschema-specifications','rpds-py','pytest','scipy','PyYAML']:
        try:packages[name]=importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:packages[name]='NOT_INSTALLED'
    write_new(out/'environment.json',{'executable':sys.executable,'executable_sha256':sha(sys.executable),'python':sys.version,
        'platform':platform.platform(),'abi':sys.implementation.cache_tag,'packages':packages,
        'install':'NOT_RUN','locator':'Found by rg --files under existing ~/.cache/codex-runtimes; not an exhaustive whole-machine search',
        'required_preparation':{'interpreter':'existing CPython 3.12.14','install':['jsonschema==4.23.0 and required transitive dependencies'],
            'not_required':['torch','gym','scipy','pytest','GPU'],'environment':'isolated PCT environment or authorized existing interpreter; no installation performed'}})
    write_new(out/'commands_and_results.json',{'commands':commands,'ast':'ast.json','legacy_byte_checks':'legacy_resources.json',
        'notes':['Stdlib tests completed; integration skips remain NOT_RUN; see tests.json for exact counts. Exit 0 is not full acceptance',
                 'initial interpreter probe used unsupported zsh command -v -a and unmatched glob, then corrected to which -a; no mutation',
                 'initial targeted rg used a nonexistent schema pathname; subsequent source reading located actual validation; no mutation'],
        'credential_reads':0,'model_requests':0,'orders':0,'candidate_generation':0,'LP':0})


if __name__=='__main__':main()
