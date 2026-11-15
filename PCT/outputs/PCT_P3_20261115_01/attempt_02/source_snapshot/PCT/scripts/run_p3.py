"""Fixed P3 freeze/dispatch; no remote service or credentials, no retries."""
import argparse
import copy
import difflib
import json
import os
from pathlib import Path
import random
import resource
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/'PCT/src'),str(ROOT/'semantic_pallet_planner/src')]
import numpy as np
import torch
from pct_baseline.contracts import read,sha,digest,require,write_new
from pct_baseline.persistence import atomic_new,JobLock
from pct_baseline import p3_runtime as rt
from pct_baseline import p3_training as tr
from pct_baseline import dataset


def dump(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True);atomic_new(path,value)


def preflight(out):
    out.mkdir(parents=True,exist_ok=True)
    checks=[]
    for package in ['PCT_P2_C_20261115_01','PCT_P2_C_QA_20261115_01']:
        base=Path('PCT/outputs')/package;m=read(base/'delivery_manifest.json')
        differences=[]
        for row in m['files']:
            if not Path(row['path']).is_file() or sha(row['path'])!=row['sha256']:differences.append(row['path'])
        require(all(p in ['PCT/README.md','PCT/docs/README.md'] for p in differences),'P3_PREDECESSOR_DRIFT')
        checks.append({'package':package,'files':len(m['files']),'differences':differences,
                       'meaning':'navigation changed after prior freeze; history not resigned'})
    _,rows=dataset.authenticate(ROOT)
    spec=dataset.execution_spec(ROOT,'PCT/configs/data_b1_v1.json')
    tasks=[dataset.derive(row,parent,identity,spec) for name in rt.TASKS for row,parent,identity in rows if row['task_id']==name]
    require(len(tasks)==2 and sum(len(t['items']) for t in tasks)==33,'P3_DENOMINATOR')
    from semantic_pallet_planner.jev_select.contracts import validate_schema
    for t in tasks:validate_schema('task',t)
    model_dirs={
        'pct_geo_b1':Path('PCT/outputs/PCT_P2_B_20261115_01/attempt_06/tests'),
        'pct_load_b1':Path('PCT/outputs/PCT_P2_C_20261115_01/attempt_03/tests')}
    bindings={}
    for method,base in model_dirs.items():
        weights=Path('PCT/outputs/PCT_P2_A_20261114_01/weight_tensors.json') if method=='pct_geo_b1' else base/'weight_tensors.json'
        bindings[method]=rt.model_binding(base/'model_manifest.json',weights)
        rt.load_bound(bindings[method])
    dump(out/'predecessor_checks.json',checks)
    for t in tasks:dump(out/'tasks'/(t['task_id']+'.json'),t)
    return tasks,bindings


def freeze(out,tasks,bindings):
    jobs=[]
    cuts={('pct_geo_b1',0):'DECISION_READY',('pct_geo_b1',1):'SELECTED',
          ('pct_load_b1',0):'MONITORED',('pct_load_b1',1):'COMMITTED'}
    for method in rt.METHODS:
        for i,t in enumerate(tasks):
            jobs.append({'job_id':f'diagnostic_{method}_{i}','method':method,'task_id':t['task_id'],
                         'task_digest':digest(t),'binding':bindings.get(method),'cut_phase':cuts.get((method,i)),
                         'output':str(out/'jobs'/f'diagnostic_{method}_{i}')})
    plan={'version':'pct_p3_fixed_plan_v1','tasks':[{'task_id':t['task_id'],'digest':digest(t),'items':len(t['items'])} for t in tasks],
          'jobs':jobs,'training':{'attempt_task_sequence':[tasks[i%2]['task_id'] for i in range(16)],
          'method':'pct_load_b1','seed':0,'batch_orders':8,'updates_max':2,'actions_max':264,
          'optimizer':'Adam','lr':1e-4,'grad_norm_clip':.5,'n':5,'gamma':1.,'entropy_coefficient':0.,
          'diagnostic_only':True,'update_boundary_resume':'reload update1 optimizer/model/RNG before batch2; gradient-equivalence probe without optimizer.step'},
          'matrix_caps':{'jobs':6,'monitors':99,'network_choices':66},'remote_requests':0,
          'source':rt.source_identity(),'environment':rt.environment(),
          'stop_policy':'technical failure stops remaining jobs and training; all remaining slots NOT_RUN; natural empty pool/instability continue; unassessable stops batch',
          'model_recovery_cuts':'within original six jobs; each cut at first occurrence only; no additional completed order',
          'training_end':'complete-order boundaries only; zero transitions or invalid loss stops, no extra collection'}
    plan['plan_digest']=digest(plan);dump(out/'plan.json',plan)
    # Save complete source bytes before any candidate generation/monitor or update.
    paths=list(Path('PCT/src').rglob('*.py'))+list(Path('PCT/src').rglob('*.schema.json'))+[Path(__file__).relative_to(ROOT),Path('PCT/tests/test_p3_training.py'),Path('PCT/tests/test_p3_integration.py')]
    for name in ['packaging_versions.py','contracts.py','packaging_runtime.py','stability/monitor.py','episode.py']:
        paths.append(Path('semantic_pallet_planner/src/semantic_pallet_planner/jev_select')/name)
    sources={str(p):sha(p) for p in paths}
    for p in paths:
        target=out/'source_snapshot'/p;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(p.read_bytes())
    dump(out/'pre_execution_identity.json',{'source_sha256':sources,'environment':rt.environment(),
        'head':subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),
        'python_executable_sha256':sha(sys.executable),'plan_digest':plan['plan_digest']})
    return plan


def dispatch_worker(root,cut=None):
    command=[sys.executable,__file__,'worker','--output',str(root)]
    if cut:command+=['--cut',cut]
    p=subprocess.run(command,capture_output=True,text=True)
    # Distinct invocation logs, no retry on failure.
    index=len(list(root.glob('worker_*.json')))
    dump(root/f'worker_{index:02d}.json',{'command':['$NBU_PY','PCT/scripts/run_p3.py',*command[2:]],
                                       'exit_code':p.returncode,'stdout':p.stdout,'stderr':p.stderr})
    require(p.returncode==0,'P3_WORKER_FAILED:'+str(root))


def matrix(plan,out,tasks):
    results=[]
    for job in plan['jobs']:
        task=next(t for t in tasks if t['task_id']==job['task_id']);b=job['binding']
        config=rt.build_config(task,job['method'],plan['plan_digest'],digest(b) if b else None)
        root=Path(job['output']);rt.create_job(task,config,b,root,job['job_id'])
        if job['cut_phase']:
            dispatch_worker(root,job['cut_phase'])
            # Resume only when the planned cut actually occurred. A naturally
            # terminated order is never rerun to reach a requested cut.
            _,rows=rt.read_records(root)
            if rows[-1]['checkpoint']['phase']!='TERMINATED':dispatch_worker(root)
        else:dispatch_worker(root)
        ep=read(root/'episode.json');reason=ep['checkpoint']['reason']
        results.append({'job_id':job['job_id'],'reason':reason,'summary':ep['summary']})
        dump(out/'matrix_progress'/f'{len(results):02d}.json',results[-1])
        require(ep['summary']['policy_ranking_eligible'],'P3_TECHNICAL_MATRIX_STOP:'+str(reason))
    dump(out/'matrix_results.json',results)
    return results


def export_model(core,path,update):
    from pct_baseline.load_model import make_manifest
    path.mkdir(parents=True,exist_ok=False)
    weights=path/'weight_tensors.json'
    dump(weights,{k:{'dtype':str(v.dtype),'shape':list(v.shape),'values':v.detach().tolist()} for k,v in core.state_dict().items()})
    manifest=make_manifest(weights,provenance={'kind':'TRAINED','seed':0,
        'evidence':f'P3 small-step engineering diagnostic only; update {update}, not formal trained model'})
    dump(path/'model_manifest.json',manifest)
    return rt.model_binding(path/'model_manifest.json',weights)


def trajectory(root):
    ep=read(root/'episode.json');require(ep['summary']['policy_ranking_eligible'],'P3_TRAIN_TECHNICAL_STOP')
    transitions=[]
    container=ep['final_state']['container'];cv=container['length_mm']*container['width_mm']*container['max_height_mm']
    for ev in ep['events']:
        if ev.get('selection') is None:continue
        r=read(root/'records'/(ev['decision_id']+'.json'))
        require(r['selection']==ev['selection'],'P3_TRAIN_SELECTION_RECORD')
        before=sum(math_volume(p) for p in ev['before']['placed_items'])
        after=sum(math_volume(p) for p in ev['after']['placed_items'])
        reward=tr.committed_reward(before,after,cv)
        require((ev['event']=='PLACE')==(reward>0),'P3_REWARD_COMMIT')
        transitions.append({'record':str(root/'records'/(ev['decision_id']+'.json')),'reward':reward,
                            'choice':ev['route']=='CHOICE_REQUIRED','leaf_index':r['output']['leaf_index'],
                            'value':r['output']['value'],'encoding':r['encoding']})
    require(abs(sum(t['reward'] for t in transitions)-10*ep['summary']['fixed_container_utilization'])<1e-8,'P3_REWARD_SUM')
    return transitions


def math_volume(p):
    import math
    return math.prod(p['oriented_size_mm'])


def training(plan,out,tasks,initial_binding):
    from pct_baseline.load_model import tensor_identity
    from pct_baseline.load_encoding import encode_load
    from semantic_pallet_planner.jev_select.contracts import DecisionContext
    bound=initial_binding;model=rt.load_bound(bound);core=model._model
    optimizer=torch.optim.Adam(core.parameters(),lr=1e-4)
    snapshots=out/'training'/'snapshots';snapshots.mkdir(parents=True,exist_ok=True)
    identity={'plan_digest':plan['plan_digest'],'source':rt.source_identity(),'environment':rt.environment(),
              'feature_contract':bound['features'],'initial_model':initial_binding}
    cursor=0;update_records=[]
    position={'update_id':0,'attempt_cursor':0,'batch_shards':[],'policy_snapshot_id':digest(bound)}
    tr.save_snapshot(snapshots/'update_0',core,optimizer,identity=identity,position=position)
    for update in (1,2):
        trajectories=[];shards=[]
        # Strictly reload the frozen immutable exported collection model.
        for slot in range(8):
            task=tasks[cursor%2];job_id=f'training_{cursor:02d}';root=out/'training'/job_id
            config=rt.build_config(task,'pct_load_b1',plan['plan_digest'],digest(bound),mode='training')
            rt.create_job(task,config,bound,root,job_id)
            ep=rt.run_job(root)
            ts=trajectory(root);trajectories.append(ts);shards.append(str(root/'episode.json'));cursor+=1
        require(any(trajectories),'P3_ZERO_TRANSITION_BATCH_NO_UPDATE')
        before={k:tensor_identity(v) for k,v in core.state_dict().items()}
        # Graph evaluation uses the same snapshot as collection, with gradients
        # enabled. No inference_mode outputs are used as trainable tensors.
        values=[];logps=[];targets=[];choices=[];segments=[];probs=[]
        for ts in trajectories:
            if not ts:continue
            target,seg=tr.segmented_targets(torch.tensor([t['reward'] for t in ts]),torch.tensor([t['value'] for t in ts]),terminal=True)
            segments.append(seg);targets.append(target)
            for t in ts:
                x=torch.tensor([t['encoding']['packed']],dtype=torch.float32)
                _,_,entropy,hidden,dist=core.actor(x,deterministic=True,normFactor=1,evaluate=True)
                value=core.critic(hidden).reshape(())
                require(bool(torch.isfinite(dist.probs).all()) and abs(float(value.detach())-t['value'])<1e-5,'P3_COLLECTION_SNAPSHOT_CHANGED')
                probability=dist.probs[0,t['leaf_index']]
                require(bool(probability>0),'P3_TRAIN_PROBABILITY')
                values.append(value);logps.append(probability.log());choices.append(t['choice']);probs.append(float(probability.detach()))
        loss,actor,critic=tr.a2c_loss(torch.stack(values),torch.stack(logps),torch.cat(targets),torch.tensor(choices))
        optimizer.zero_grad(set_to_none=True);loss.backward()
        require(all(p.grad is None or bool(torch.isfinite(p.grad).all()) for p in core.parameters()),'P3_GRADIENT_NONFINITE')
        norm=torch.nn.utils.clip_grad_norm_(core.parameters(),.5,error_if_nonfinite=True)
        gradient={k:tensor_identity(p.grad) for k,p in core.named_parameters() if p.grad is not None}
        optimizer.step()  # only two allowed calls, one per fixed batch
        require(all(bool(torch.isfinite(p).all()) for p in core.parameters()),'P3_PARAMETER_NONFINITE')
        after={k:tensor_identity(v) for k,v in core.state_dict().items()}
        require(before!=after,'P3_PARAMETERS_UNCHANGED_NO_EXTRA_COLLECTION')
        bound=export_model(core,out/'training'/f'model_update_{update}',update)
        position={'update_id':update,'attempt_cursor':cursor,'batch_shards':shards,'policy_snapshot_id':digest(bound)}
        record=tr.save_snapshot(snapshots/f'update_{update}',core,optimizer,identity=identity,position=position)
        # Prove populated Adam state and all RNG roundtrip at real update boundary.
        expected_model=copy.deepcopy(core.state_dict());expected_optimizer=copy.deepcopy(optimizer.state_dict())
        expected_rng=tr.rng_state()
        fresh=rt.load_bound(bound)._model;fresh_optimizer=torch.optim.Adam(fresh.parameters(),lr=1e-4)
        pos=tr.load_snapshot(snapshots/f'update_{update}',fresh,fresh_optimizer,expected_identity=identity,expected_record_digest=record['record_digest'])
        require(pos==position and all(torch.equal(expected_model[k],fresh.state_dict()[k]) for k in expected_model),'P3_MODEL_RESTORE')
        def same(a,b):
            if isinstance(a,torch.Tensor):return torch.equal(a,b)
            if isinstance(a,dict):return set(a)==set(b) and all(same(a[k],b[k]) for k in a)
            if isinstance(a,(tuple,list)):return len(a)==len(b) and all(same(x,y) for x,y in zip(a,b))
            if isinstance(a,np.ndarray):return np.array_equal(a,b)
            return a==b
        require(same(expected_optimizer,fresh_optimizer.state_dict()) and same(expected_rng,tr.rng_state()),'P3_OPTIMIZER_RNG_RESTORE')
        # Continue with restored objects, never redo the already applied update.
        core=fresh;optimizer=fresh_optimizer
        info={'update_id':update,'attempt_cursor':cursor,'transition_count':len(values),'choice_count':sum(choices),
              'singleton_count':len(values)-sum(choices),'loss':float(loss.detach()),'actor_loss':float(actor.detach()),
              'critic_loss':float(critic.detach()),'unclipped_grad_norm':float(norm),'gradients':gradient,
              'before':before,'after':after,'parameters_changed':before!=after,'segments':segments,
              'probabilities':probs,'critic_gradient_forwards':len(values),'policy_gradient_choice_forwards':sum(choices),
              'singleton_critic_gradient_forwards':len(values)-sum(choices),'optimizer_rng_roundtrip':'EXACT',
              'snapshot_record_digest':record['record_digest'],'reward_sum':sum(t['reward'] for ts in trajectories for t in ts)}
        dump(out/'training'/f'update_{update}.json',info);update_records.append(info)
    return update_records


def main():
    ap=argparse.ArgumentParser();ap.add_argument('mode',choices=['run','worker']);ap.add_argument('--output',type=Path,required=True);ap.add_argument('--cut');args=ap.parse_args()
    torch.set_num_threads(1);torch.use_deterministic_algorithms(True)
    if args.mode=='worker':
        rt.run_job(args.output,args.cut);return
    out=args.output;random.seed(0);np.random.seed(0);torch.manual_seed(0);start=time.perf_counter()
    status={'version':'pct_p3_dispatch_status_v1','matrix':'NOT_RUN','training':'NOT_RUN','error':None}
    try:
        tasks,bindings=preflight(out);plan=freeze(out,tasks,bindings)
        matrix(plan,out,tasks);status['matrix']='COMPLETE'
        training(plan,out,tasks,bindings['pct_load_b1']);status['training']='TWO_UPDATES_COMPLETE'
    except BaseException as exc:
        status['error']={'type':type(exc).__name__,'detail':str(exc)}
        raise
    finally:
        status.update(elapsed_s=time.perf_counter()-start,peak_process_rss_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
                      peak_child_rss_bytes=resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss,
                      rss_unit='bytes on macOS; per-process peaks, not simultaneous aggregate',remote_requests=0)
        dump(out/'dispatch_status.json',status)

if __name__=='__main__':main()
