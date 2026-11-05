"""Offline CLI launcher for saved-evidence tests/reanalysis (stdlib only).

Usage: python -m ...packaging_readonly_guard RECEIPT MODULE [args...]
For archived imports launch this file by path (not -m, which preloads the
current package). MODULE=script runs an archived verifier. Subprocesses used by that
verifier install the frozen worker's own read-only dispatch guards.
"""
import json
import os
from pathlib import Path
import runpy
import sys


def install(repo):
    counts = {k:0 for k in ('network','credential','historical_write','execution_dispatch')}
    outputs = repo/'semantic_pallet_planner/outputs'
    protected = list(outputs.glob('JEV_JN*')) + [outputs/'DATA_JEV_PACKAGING_LOAD_20261102_02']
    protected += [x for x in (repo/'docs/03_阶段产出分析/Jev').glob('*.md') if x.name != 'README.md']
    credentials = {'typesafe_api_key.md','typwsafe_api_key.md','deepseek_api_key.md','deepseek_api.md','.env'}
    def audit(event, args):
        if event in ('socket.connect','socket.getaddrinfo','socket.connect_ex'):
            counts['network'] += 1; raise RuntimeError('READONLY_NETWORK_FORBIDDEN')
        if event == 'open' and isinstance(args[0], (str,bytes,os.PathLike)):
            path = Path(os.fsdecode(args[0])).resolve(); mode = args[1] or ''; flags = args[2]
            if path.name in credentials or path.name.endswith('_api_key.md'):
                counts['credential'] += 1; raise RuntimeError('READONLY_CREDENTIAL_FORBIDDEN')
            writing = any(c in mode for c in 'wax+') or flags & (os.O_WRONLY|os.O_RDWR|os.O_CREAT|os.O_TRUNC)
            if writing and any(path.is_relative_to(p) for p in protected):
                counts['historical_write'] += 1; raise RuntimeError('READONLY_PARENT_WRITE_FORBIDDEN')
        if event in ('os.remove','os.rename','os.rmdir','os.mkdir','os.chmod','os.link','os.symlink','os.truncate'):
            if any(Path(os.fsdecode(a)).resolve().is_relative_to(p) for a in args[:2] if isinstance(a,(str,bytes)) for p in protected):
                counts['historical_write'] += 1; raise RuntimeError('READONLY_PARENT_MUTATION_FORBIDDEN')
    blocked = {'run_episode','commit_physical','monitor_selected_action','assess_candidate','linprog'}
    def profile(frame, event, arg):
        if event != 'call': return
        name = frame.f_code.co_name; filename = Path(frame.f_code.co_filename).name
        forbidden = (name in blocked and ('jev_select' in frame.f_code.co_filename or 'scipy' in frame.f_code.co_filename))
        forbidden |= filename in ('candidates.py',) and name == 'build'
        forbidden |= filename in ('packaging_runtime.py','selection.py','selector.py','packaging_remote.py','packaging_memory_protocol.py') and name == 'select'
        forbidden |= filename in ('packaging_counterfactual.py','packaging_comparisons.py') and name in ('prepare','run','create_child','stage_runtime')
        forbidden |= filename in ('packaging_contrast_generation.py','packaging_contrast_validation.py') and name in ('prepare','run')
        forbidden |= filename=='memory_generation.py' and name in ('_credential','remote_complete','_send')
        forbidden |= filename=='packaging_pilot_memory.py' and name=='resolve'
        forbidden |= filename in ('packaging_experience.py','packaging_contrast.py') and name in ('retrieve','_retrieve_validated')
        forbidden |= filename=='packaging_memory_pilot.py' and name in ('prepare','run','summarize')
        if forbidden:
            counts['execution_dispatch'] += 1; raise RuntimeError('READONLY_DISPATCH_FORBIDDEN:'+filename+':'+name)
    sys.addaudithook(audit); sys.setprofile(profile)
    return counts


def main():
    receipt = Path(sys.argv[1]); module = sys.argv[2]; args = sys.argv[3:]
    repo = Path.cwd().resolve(); counts = install(repo)
    status = 'ERROR'
    try:
        if module == 'script':
            sys.argv = args; runpy.run_path(args[0], run_name='__main__')
        else:
            sys.argv = [module, *args]; runpy.run_module(module, run_name='__main__', alter_sys=True)
        status = 'PASS'
    except SystemExit as exc:
        if exc.code in (None, 0): status = 'PASS'
        raise
    finally:
        sys.setprofile(None)
        receipt.parent.mkdir(parents=True, exist_ok=True)
        receipt.write_text(json.dumps({'guard':'offline+credential+historical-readonly+execution-dispatch',
                                       'status':status,'counts':counts},indent=2)+'\n')


if __name__ == '__main__': main()
