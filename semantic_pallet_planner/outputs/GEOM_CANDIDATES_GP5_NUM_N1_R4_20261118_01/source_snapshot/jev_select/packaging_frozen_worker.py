"""JN2-B control adapter. Execute this file with PYTHONPATH pointing ONLY to A's package copy.

No physical/selection algorithm is defined here. All execution and saved-record
validation use unchanged modules from that frozen package. REPO rebasing changes
only artifact path resolution after relocation, never configuration or source bytes.
"""
from pathlib import Path
import argparse
import json
import os
import sys


def install_guards(repo, readonly):
    counts={k:0 for k in ('network','credential','historical_write')}
    protected=[repo/'semantic_pallet_planner/outputs'/n for n in ('JEV_JN2_20261104_01','JEV_JN1_20261103_03','DATA_JEV_PACKAGING_LOAD_20261102_02')]
    def audit(event,args):
        if event in ('socket.connect','socket.getaddrinfo','socket.connect_ex'):
            counts['network']+=1;raise RuntimeError('JN2_B_NETWORK_FORBIDDEN')
        if event=='open' and isinstance(args[0],(str,bytes,os.PathLike)):
            p=Path(os.fsdecode(args[0])).resolve();mode=args[1] or '';flags=args[2]
            if p.name in ('typesafe_api_key.md','deepseek_api_key.md','.env'):
                counts['credential']+=1;raise RuntimeError('JN2_B_CREDENTIAL_FORBIDDEN')
            if (any(c in mode for c in 'wax+') or flags & (os.O_WRONLY|os.O_RDWR|os.O_CREAT|os.O_TRUNC)) and any(p.is_relative_to(x) for x in protected):
                counts['historical_write']+=1;raise RuntimeError('JN2_B_PARENT_WRITE_FORBIDDEN')
        if event in ('os.remove','os.rename','os.rmdir'):
            if any(Path(os.fsdecode(a)).resolve().is_relative_to(p) for a in args[:2] if isinstance(a,(str,bytes)) for p in protected):
                counts['historical_write']+=1;raise RuntimeError('JN2_B_PARENT_MUTATION_FORBIDDEN')
    sys.addaudithook(audit)
    if readonly:
        import semantic_pallet_planner.jev_select.episode as ep
        import semantic_pallet_planner.jev_select.execution as ex
        import semantic_pallet_planner.jev_select.stability.monitor as mon
        import semantic_pallet_planner.jev_select.stability.balance_adapter as ba
        from semantic_pallet_planner.jev_select.candidates import CandidateProvider
        from semantic_pallet_planner.jev_select.packaging_runtime import LocalPackagingDouble
        import scipy.optimize
        for owner,name in ((ep,'run_episode'),(ex,'commit_physical'),(mon,'monitor_selected_action'),(ba,'assess_candidate'),(CandidateProvider,'build'),(LocalPackagingDouble,'select'),(scipy.optimize,'linprog')):
            key='dispatch_'+name;counts[key]=0
            def forbidden(*a,_key=key,**kw):
                counts[_key]+=1;raise AssertionError('READONLY_'+_key)
            setattr(owner,name,forbidden)
    return counts


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--repo',required=True);parser.add_argument('--parent-a',required=True)
    parser.add_argument('--command',choices=['identity','audit-a','snapshot','run','validate'],required=True)
    parser.add_argument('--decision');parser.add_argument('--fork');parser.add_argument('--response',required=True)
    a=parser.parse_args();repo=Path(a.repo).resolve();parent=repo/a.parent_a
    counts=install_guards(repo,a.command!='run')
    from semantic_pallet_planner.jev_select import packaging_counterfactual as f
    from semantic_pallet_planner.jev_select.stability.runtime import environment
    f.common.REPO=repo
    p=f.read(parent/'branch_plan.json')
    f.require(f.source_manifest()==p['source_manifest'],'frozen_worker_wrong_source')
    package=Path(f.__file__).resolve().parents[1]
    f.require(package.is_relative_to(repo/'semantic_pallet_planner/outputs') and package!=repo/'semantic_pallet_planner/src/semantic_pallet_planner','frozen_worker_not_isolated')
    from semantic_pallet_planner.jev_select.stability.monitor import preflight
    preflight(p['config'])
    if a.command=='identity':
        value={'source_digest':f.digest(f.source_manifest()),'environment':environment(),'monitor':p['config']['stability_monitor'],
               'physical_manifest':f.physical_manifest(),'package':package.relative_to(repo).as_posix()}
    elif a.command=='audit-a':value=f.validate_output(parent)
    elif a.command=='snapshot':
        s=f.restore_training_fork(repo/p['parent_identity']['parent'],a.decision)
        task=f.read(repo/s['field_evidence']['task'])
        cfg=f.load_monitor_config(data_identity=p['parent_identity']['data_identity'],task_digest=f.digest(task),method=f.METHOD,enabled=True)
        value={'snapshot':s,'task':task,'config':cfg,'selection':f.interventions(s)}
    elif a.command=='validate':value=f.validate_output(repo/a.fork)
    else:value=f.run(repo/a.fork,resume=(repo/a.fork/'execution_receipt.json').exists())
    f.write(a.response,{'status':'OK','command':a.command,'value':value,'guard_counts':counts})


if __name__=='__main__':main()
