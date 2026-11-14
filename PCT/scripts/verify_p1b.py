"""P1-B bounded verification. No installation or old-output mutation.

Runs reviewed unittest constructions (<=3 items each) and P1-A regression.
Only P1-B needs actual LP; no official dataset/matrix execution, no model.
Raw failures remain in their unique output directory; never overwrites receipts.
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
sys.path.insert(0,str(ROOT/'semantic_pallet_planner/src'))
from pct_baseline.contracts import sha,read,write_new


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output',required=True);parser.add_argument('--complete-checks',action='store_true');args=parser.parse_args()
    out=Path(args.output);out.mkdir(parents=True,exist_ok=args.complete_checks)
    env=dict(os.environ,PYTHONPATH='PCT/src:semantic_pallet_planner/src',PYTHONDONTWRITEBYTECODE='1')
    commands=[]
    def run(name,argv,display,extra_env=None):
        result=subprocess.run(argv,cwd=ROOT,env=dict(env,**(extra_env or {})),text=True,capture_output=True)
        row={'command':display,'argv':argv,'exit_code':result.returncode,'stdout':result.stdout,'stderr':result.stderr}
        write_new(out/(name+'.json'),row)
        commands.append({'command':display,'exit_code':result.returncode,'evidence':str(out/(name+'.json'))})
        if result.returncode:raise RuntimeError(name+' failed; original result preserved')
        return row
    code='''import json,unittest
suite=unittest.defaultTestLoader.discover('PCT/tests',pattern=PATTERN)
result=unittest.TextTestRunner(verbosity=2).run(suite)
print(json.dumps({'tests':result.testsRun,'failures':len(result.failures),'errors':len(result.errors),'skips':len(result.skipped)}))
assert result.wasSuccessful() and not result.skipped
'''
    if not args.complete_checks:
        run('p1b_tests',[sys.executable,'-c',code.replace('PATTERN',repr('test_p1b_execution.py'))],
            'PYTHONPATH=PCT/src:semantic_pallet_planner/src PCT_P1B_EVIDENCE_DIR=<new cases> "$NBU_PY" -c <reviewed unittest runner: test_p1b_execution.py>',
            {'PCT_P1B_EVIDENCE_DIR':str(out/'cases')})
        run('p1a_regression',[sys.executable,'-c',code.replace('PATTERN',repr('test_b1_*.py'))],
            'PYTHONPATH=PCT/src:semantic_pallet_planner/src "$NBU_PY" -c <reviewed unittest runner: test_b1_*.py>')
        run('pip_check',[sys.executable,'-m','pip','check'],'"$NBU_PY" -m pip check')
        run('pip_freeze',[sys.executable,'-m','pip','freeze','--all'],'"$NBU_PY" -m pip freeze --all')
    else:
        for name in ('p1b_tests','p1a_regression','pip_check','pip_freeze'):
            saved=read(out/(name+'.json'))
            assert saved['exit_code']==0
            if name in ('p1b_tests','p1a_regression'):
                stats=json.loads(saved['stdout'])
                assert stats['failures']==stats['errors']==stats['skips']==0
            commands.append({'command':saved['command'],'exit_code':saved['exit_code'],'evidence':str(out/(name+'.json')),'reused_completed_test_receipt':True})
    from semantic_pallet_planner.jev_select.stability.monitor import exact_freeze
    import scipy.optimize._highspy._core as core
    frozen=exact_freeze()
    write_new(out/'environment.json',{'python':sys.version,'executable':sys.executable,'executable_sha256':sha(sys.executable),
        'abi':sys.implementation.cache_tag,'platform':platform.platform(),
        'dependencies':{name:metadata.version(name) for name in ['numpy','scipy','jsonschema','attrs','referencing','jsonschema-specifications','rpds-py','typing-extensions']},
        'highs_version':'.'.join(str(getattr(core,'HIGHS_VERSION_'+part)) for part in ['MAJOR','MINOR','PATCH']),
        'highs_core_file':core.__file__,'highs_core_sha256':sha(core.__file__),
        'installation_this_script':'NONE; actual authorized pip installation is independently recorded by parent pip_install.log / pip_install_report.json'})
    write_new(out/'exact_freeze.json',frozen)
    resources=[]
    public=ROOT/'semantic_pallet_planner/src/semantic_pallet_planner/jev_select'
    for directory in ['schemas','configs']:
        for path in sorted((public/directory).glob('*')):
            if not path.is_file():continue
            relative=str(path.relative_to(ROOT))
            original=subprocess.run(['git','show','25be41c7:'+relative],cwd=ROOT,capture_output=True,check=True).stdout
            resources.append({'path':relative,'baseline_sha256':hashlib.sha256(original).hexdigest(),'actual_sha256':sha(path)})
    assert all(r['baseline_sha256']==r['actual_sha256'] for r in resources)
    write_new(out/'legacy_resources.json',{'status':'PASS','resources':resources})
    source=list((ROOT/'PCT/src').rglob('*.py'))+list((ROOT/'PCT/tests').glob('*.py'))+list((ROOT/'PCT/scripts').glob('*.py'))
    source += [public/name for name in ['packaging_versions.py','selector.py','episode.py','stability/monitor.py']]
    for path in source:ast.parse(path.read_text(),filename=str(path.relative_to(ROOT)))
    write_new(out/'ast.json',{'status':'PASS','files':[str(p.relative_to(ROOT)) for p in source],'python':sys.version})
    # Preserve historical output bytes, independent of shared source/navigation changes.
    history=[]
    for name in ['PCT_P0_CONTRACT_20261114_01','PCT_P0_QA_20261114_01','PCT_P1_A_20261114_01','PCT_P1_A_NBU_20261114_02','PCT_P1_A_QA_20261114_01']:
        root=ROOT/'PCT/outputs'/name;m=read(root/'delivery_manifest.json')
        entries=m.get('sha256',{}) if 'sha256' in m else {r['path']:r['sha256'] for r in m['files']}
        for path,expected in entries.items():
            if path.startswith(str(root.relative_to(ROOT))+'/'):
                assert sha(ROOT/path)==expected,path
                history.append({'path':path,'sha256':expected})
    write_new(out/'historical_outputs.json',{'status':'UNCHANGED','files':history})
    run('git_diff_check',['git','diff','--check'],'git diff --check')
    write_new(out/'commands_and_results.json',{'commands':commands,'local_p1b':'p1b_tests.json','local_regression':'p1a_regression.json',
        'installation':'Not repeated; parent actual pip records','models':0,'training':0,'credential_reads':0,
        'scope':'Only constructions, no historical-order run, P1-C resume/locks NOT_RUN',
        'guards':'Each P1-B test blocks socket.connect/connect_ex and transport.credential in its process; subprocess contents separately reviewed (Git read-only and old extension diagnosis only); not a whole-process formal proof'})


if __name__=='__main__':main()
