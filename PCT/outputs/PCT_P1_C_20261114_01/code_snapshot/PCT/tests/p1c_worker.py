"""Reviewed subprocess harness: <=3 boxes, actual or labeled control-stub kernel.
All roles are recorded across processes. No models, transport or credentials.
"""
import argparse
import copy
from dataclasses import asdict
import json
import os
from pathlib import Path
import socket
import sys
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[2]
for path in ('PCT/src','semantic_pallet_planner/src','PCT/tests'):sys.path.insert(0,str(ROOT/path))
from pct_baseline.contracts import read,digest,canonical
from pct_baseline.persistence import RecoveryError,JobLock


def main():
    parser=argparse.ArgumentParser();parser.add_argument('action',choices=['prepare','run','verify','hold-lock','probe']);parser.add_argument('--root',required=True)
    parser.add_argument('--scenario',choices=['stable','unstable','stub_unstable'],default='stable')
    parser.add_argument('--cut',choices=['DECISION_READY','SELECTED','MONITORED','COMMITTED']);parser.add_argument('--probe')
    parser.add_argument('--dependency-drift',action='store_true');parser.add_argument('--extra-source-file')
    args=parser.parse_args();root=Path(args.root)
    def network(*a,**kw):raise AssertionError('NO_NETWORK_OR_CREDENTIALS')
    socket.socket.connect=network;socket.socket.connect_ex=network
    from semantic_pallet_planner.jev_select import transport
    original_credential=transport.credential
    transport.credential=network
    if args.action=='prepare':
        from p1b_fixtures import task,item
        from pct_baseline.recovery import create_job
        objects=([item('one')] if args.scenario=='stable' else
            [item('base',(140,200,100)),item('shelf',(200,200,100)),item('heavy',(100,200,100),mass=100)])
        t=task('P1C_'+args.scenario,objects,(1000,800,600))
        header=create_job(t,root,extra_source_files=['PCT/tests/p1c_worker.py','PCT/tests/p1b_fixtures.py']+([args.extra_source_file] if args.extra_source_file else []))
        print(json.dumps({'status':'PREPARED','header_digest':header['header_digest']}));return
    if args.action=='hold-lock':
        with JobLock(root):
            print('LOCKED',flush=True);sys.stdin.readline()
        return
    if args.action in ('verify','probe'):
        violations=[]
        def no_business(frame,event,arg):
            if event!='call':return
            module=frame.f_globals.get('__name__','');name=frame.f_code.co_name
            forbidden=(module.startswith(('semantic_pallet_planner','pct_baseline')) and (
                name in ('run_episode','_run_episode_v2','commit_physical','assess_candidate','monitor_selected_action','decision_inputs') or
                (name in ('select','result') and ('selector' in module or module=='pct_baseline.execution')) or
                (name in ('generate','_generate','_cached_generation') and ('.o4.' in module or '.planner.' in module)) or
                (name=='build' and module in ('semantic_pallet_planner.jev_select.candidates','semantic_pallet_planner.jev_select.context')) or
                (module=='semantic_pallet_planner.jev_select.transport' and name not in ('strict_json',)))) or module.startswith('scipy.optimize') and name in ('linprog','_linprog_highs')
            if forbidden:
                violations.append(module+'.'+name);raise AssertionError('FORBIDDEN_BUSINESS_CALL:'+violations[-1])
        sys.setprofile(no_business)
        if args.action=='probe':
            try:
                if args.probe=='order':
                    from semantic_pallet_planner.jev_select.episode import run_episode
                    run_episode(None,None,None,job_id='X',method='geometry_b1')
                elif args.probe=='candidate':
                    from semantic_pallet_planner.jev_select.candidates import CandidateProvider
                    CandidateProvider().build(None,None,None)
                elif args.probe=='selector':
                    from pct_baseline.execution import GeometrySelector
                    GeometrySelector({}).select(None,decision_id='X')
                elif args.probe=='transport':original_credential(None)
                elif args.probe=='lp':
                    from scipy.optimize import linprog
                    linprog([1.])
            except AssertionError as exc:
                sys.setprofile(None);print(json.dumps({'status':'BLOCKED','violations':violations,'error':str(exc)}));return
            raise AssertionError('PROBE_NOT_BLOCKED')
        from pct_baseline.saved import validate_job
        value=validate_job(root)
        sys.setprofile(None)
        assert not violations
        print(json.dumps({'status':value['status'],'phase':value['last_phase'],'records':value['records'],'forbidden_calls':violations,'scipy_imported':'scipy' in sys.modules}));return
    from pct_baseline import recovery
    from pct_baseline.execution import GeometrySelector
    from semantic_pallet_planner.jev_select.stability import exact_adapter
    from semantic_pallet_planner.jev_select.stability.exact_contracts import ExactResult
    header=read(root/'header.json');scenario=header['task']['task_id'].removeprefix('CONSTRUCTED_P1C_')
    if args.dependency_drift:
        original=recovery.environment_identity
        def changed():
            value=original();value['packages']['scipy']='INJECTED_CURRENT_DEPENDENCY_DRIFT';return value
        recovery.environment_identity=changed
    # Real loss of process after an already fsynced stage; OS releases flock.
    def cut(cp):
        target=0 if scenario=='stable' else 1 if args.cut=='COMMITTED' else 2
        if args.cut and cp['phase']==args.cut and cp['decision']==target:os._exit(75)
    from contextlib import ExitStack
    with ExitStack() as stack:
        if scenario!='stable':
            from semantic_pallet_planner.domain import internal_item,restore_placed
            from semantic_pallet_planner.planner.constraints import evaluate_pose
            from semantic_pallet_planner.jev_select.contracts import CandidateBundle
            from semantic_pallet_planner.jev_select.candidates import CandidateProvider
            poses={'base':(-70,-100,0),'shelf':(-100,-100,100),'heavy':(30,-100,200)}
            def prescribed(provider,state,req,generator,*,config):
                obj=state['pending_items'][0]['item'];size=obj['dimensions_mm'];x,y,z=poses[obj['item_id']]
                settings=copy.deepcopy(generator);settings['container']=state['container']
                raw,error=evaluate_pose(internal_item(obj),restore_placed(state['placed_items']),x,y,z,size['length'],size['width'],0,settings)
                assert error is None
                physical=[raw['visible']]
                return CandidateBundle.from_dict({'version':'jev_candidate_bundle_b1_v1','observation_digest':req['observation_digest'],'candidate_backend':'e2_original_v1',
                    'generator_config_digest':digest(generator),'physical_candidates':physical,'physical_digest':digest(physical),'generation_counts':[],
                    'selectable_pool':'unfiltered','selectable_candidates':[],'selectable_digest':digest([]),'policy_digest':None,
                    'experiment_protocol':config['experiment_protocol'],'business_mode':'physical_only'})
            stack.enter_context(patch.object(CandidateProvider,'build',prescribed))
        if scenario=='stub_unstable':
            def stub(placed_state,candidate,config):
                status='UNSTABLE' if candidate.item_id=='heavy' else 'STABLE'
                return ExactResult(status,'CONTROL_STUB_'+status,digest(asdict(placed_state)),digest(asdict(candidate)),candidate.item_id,
                    digest(asdict(config)),header['config']['stability_monitor']['algorithm_identity'],'STABLE',None,None,None,None,0,{'test_stub':True},0)
            stack.enter_context(patch.object(exact_adapter,'assess_candidate',stub))
        def profile(frame,event,arg):
            if event!='call':return
            module=frame.f_globals.get('__name__','');name=frame.f_code.co_name;locals_=frame.f_locals;role=None;payload={}
            if name=='build' and module=='semantic_pallet_planner.jev_select.context':role='context'
            elif (name=='build' and module=='semantic_pallet_planner.jev_select.candidates') or name=='prescribed':role='candidate_pool'
            elif name=='select' and module=='pct_baseline.execution':role='selector'
            elif name=='result' and module=='semantic_pallet_planner.jev_select.selector':role='selection_result'
            elif module.endswith('stability.exact_adapter') and name=='assess_candidate' or name=='stub':
                role='assessment'
                payload={'placed_state':asdict(locals_['placed_state']),'candidate':asdict(locals_['candidate']),
                    'config':asdict(locals_['config']),'algorithm_identity':header['config']['stability_monitor']['algorithm_identity'],
                    'dependency_identity':header['identities']['environment'],'evidence_kind':'CONTROL_STUB' if name=='stub' else 'REAL_EXACT_V3'}
            elif module=='semantic_pallet_planner.jev_select.execution' and name=='commit_physical':role='commit'
            if role:
                row={'pid':os.getpid(),'role':role,'decision_id':locals_.get('decision_id'),'payload':payload}
                context=locals_.get('context')
                if context is not None and hasattr(context,'data'):row['decision_id']=context.data['local_binding']['decision_id']
                with (root/'calls.jsonl').open('a') as stream:stream.write(canonical(row)+'\n');stream.flush();os.fsync(stream.fileno())
        sys.setprofile(profile)
        try:value=recovery.run_job(root,cut=cut)
        finally:sys.setprofile(None)
        print(json.dumps({'status':value['checkpoint']['reason'],'placed':value['final_state']['placed_count'],'pid':os.getpid()}))


if __name__=='__main__':
    try:main()
    except Exception as exc:
        print(json.dumps({'status':'ERROR','error_type':type(exc).__name__,'detail':str(exc)}));sys.exit(1)
