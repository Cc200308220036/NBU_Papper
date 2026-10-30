"""O4-F offline buffer acceptance, checkpoint resume and read-only replay. No Flash/API."""
import argparse
import copy
import csv
import io
import json
import math
import multiprocessing
import shutil
import statistics
from collections import defaultdict,Counter
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
import yaml
from ..config import WORKSPACE
from ..o4.common import read,write,digest,canonical
from ..o4.buffer.buffer_evaluation import episode,stable,audit_events,METHODS,summary
from ..o4.buffer.buffer_state import public_state
from ..o4.buffer.cases import run_constructs
from ..o4.buffer.validation import gold_results,diagnostics
from .o4 import snapshot_existing,check_protected
from .o4_online import offline_network_guard,sha,delivery_hashes,seal,write_jsonl,read_jsonl,verify_ab

DEFAULT_CONFIG=WORKSPACE/'semantic_pallet_planner/configs/o4_buffer_offline.yaml'
DEFAULT_C=WORKSPACE/'semantic_pallet_planner/outputs/EXP_O4_C_ONLINE_20261021_01'


def config(path=None):
    value=yaml.safe_load(Path(path or DEFAULT_CONFIG).read_text())
    expected={'schema_version':'o4_buffer_config_v1','seed':20261021,'capacities':[1,2,3],
              'comparison_capacities':[1,3],'receiver':'fill_then_plan','eos_mode':'empty_read','top_k_per_item':16,
              'topk_mode':'diverse_v1','search_depth':3,'beam_width':8,'max_successor_evaluations':256,
              'layout':'relaxed_geometry','soft_budgets':[.05,.25],'ranking_epsilon':1e-12,'remote':False}
    if value!=expected:raise ValueError('F v1 config is frozen; changes require a new version')
    return value


def sources():
    package=WORKSPACE/'semantic_pallet_planner/src/semantic_pallet_planner'
    paths=list(package.rglob('*.py'))+list((package/'schemas').glob('*.json'))+[DEFAULT_CONFIG]
    return {str(p.relative_to(WORKSPACE)):sha(p) for p in sorted(paths) if '__pycache__' not in p.parts}


def verify_c(root):
    root=Path(root).resolve()
    if read(root/'delivery_manifest.json')['files']!=delivery_hashes(root):raise ValueError('C delivery changed')
    manifest=read(root/'manifest.json')
    # Historical inventories are checked as frozen subsets. New F files are not C source changes.
    if any(sha(WORKSPACE/name)!=value for name,value in manifest['source_sha256'].items()):raise ValueError('frozen C source changed')
    inputs=read(root/'private/input_snapshot.json')
    if digest(inputs)!=manifest['input_digest']:raise ValueError('C input changed')
    acceptance=read(root/'offline_acceptance.json')
    if acceptance['status']!='PASS' or not all(acceptance['criteria'].values()):raise ValueError('requires accepted C')
    data,ab=verify_ab(manifest['baseline']['path'])
    if data!=inputs['data'] or ab!=manifest['baseline']:raise ValueError('A/B input mismatch')
    return inputs,{'path':str(root),'manifest_sha256':sha(root/'manifest.json'),
                  'delivery_manifest_sha256':sha(root/'delivery_manifest.json')}


def path_for(root,method,backend,task):return Path(root)/'episodes'/f'{method}__{backend}'/task/'events.jsonl'


def job(payload):
    """One task; workers are CPU processes, not model clients or delegated agents."""
    root,inputs,task,cfg=payload;sid=task['scenario_id'];s=inputs['scenarios'][sid];a=inputs['data']['attributes'][sid]['objects']
    records=[];evidence=[];runs={}
    with offline_network_guard() as ledger:
        for method,backend in [(m,'oracle_ast') for m in METHODS]+[('buffer_search','public_parser')]:
            row,events,_=episode(s,a,task,method,backend,inputs['generator_config'])
            write_jsonl(path_for(root,method,backend,task['task_id']),events)
            # Real independent repeat and interrupted/restarted execution, all planned methods.
            repeat,re,_=episode(s,a,task,method,backend,inputs['generator_config'])
            _,_,checkpoint=episode(s,a,task,method,backend,inputs['generator_config'],pause_after=2)
            resumed,recovered,_=episode(s,a,task,method,backend,inputs['generator_config'],checkpoint=checkpoint)
            cpfile={'scenario':s,'attributes':a,'task':task,'method':method,'backend':backend,
                    'generator_config':inputs['generator_config'],'checkpoint':checkpoint}
            write(Path(root)/'checkpoints'/f'{method}__{backend}'/(task['task_id']+'.json'),cpfile)
            event_audit=audit_events(events)
            comparison={'task_id':task['task_id'],'method':method,'backend':backend,
                        'original_digest':digest(stable({'row':row,'events':events})),
                        'repeat_digest':digest(stable({'row':repeat,'events':re})),
                        'resume_digest':digest(stable({'row':resumed,'events':recovered})),
                        'repeat_passed':row==repeat and stable(events)==stable(re),
                        'resume_passed':row==resumed and stable(events)==stable(recovered),'event_audit':event_audit}
            evidence.append(comparison);records.append(row);runs[(method,backend)]=(row,events)
        left=runs[('buffer_search','oracle_ast')];right=runs[('buffer_search','public_parser')]
        parser_agreement=stable(left[1])==stable(right[1]) and {k:v for k,v in left[0].items() if k!='backend'}=={k:v for k,v in right[0].items() if k!='backend'}
        def poses(events):return [{'pick_item_id':e['action']['pick_item_id'],'pose':e['chosen_candidate']['pose']} for e in events if e['kind']=='PLACE']
        single=runs[('single_greedy','oracle_ast')];fifo=runs[('buffer_fifo','oracle_ast')]
        stored=read_jsonl(Path(inputs['c_path'])/'episodes/oracle_ast'/task['task_id']/'steps.jsonl')
        expected=[{'pick_item_id':e['candidate_mapping'][e['committed_label']]['pick_item_id'],
                   'pose':e['candidate_mapping'][e['committed_label']]['pose']} for e in stored if e['committed_label']]
        compatibility={'task_id':task['task_id'],'single_matches_c':poses(single[1])==expected,
                       'fifo_matches_single':poses(fifo[1])==poses(single[1]),'parser_oracle_equal':parser_agreement,
                       'network':ledger}
    return records,evidence,compatibility


def summarize(rows):
    grouped=defaultdict(list)
    for r in rows:grouped[(r['method'],r['backend'])].append(r)
    result=[]
    for (m,b),values in sorted(grouped.items()):
        result.append({'method':m,'backend':b,'planned_tasks':len(values),'completed':sum(x['completed'] for x in values),
            'clean_completed':sum(x['clean_completed'] for x in values),'completion_rate':sum(x['completed'] for x in values)/len(values),
            'mean_item_ratio':statistics.mean(x['placed_item_ratio'] for x in values),'mean_volume_ratio':statistics.mean(x['placed_volume_ratio'] for x in values),
            'termination_counts':dict(Counter(x['termination_reason'] for x in values)),
            'physical_violations':sum(x['physical_violations'] for x in values),'reference_violations':sum(x['final_business_violation_count'] for x in values),
            'inversions':sum(x['inversions'] for x in values),'non_head_commits':sum(x['non_head_commits'] for x in values),
            'search_truncated_count':sum(x['search_truncated_count'] for x in values)})
    return result


def resource_metrics(root,rows):
    times=[];generation=[];evaluations=[];depths=[];beams=[];trunc=[]
    for r in rows:
        for e in read_jsonl(path_for(root,r['method'],r['backend'],r['task_id'])):
            if 'planning_seconds' in e:times.append(e['planning_seconds'])
            tr=e.get('search_trace')
            audits=[n['audit'] for n in tr['nodes']] if tr else ([e['root_audit']] if 'root_audit' in e else [])
            generation.extend(g['elapsed_seconds'] for a in audits for g in a['generation'])
            if tr:evaluations.append(tr['evaluations']);depths.append(tr['max_depth']);beams.append(tr['max_beam']);trunc.append(tr['search_truncated'])
    def quantiles(values):
        v=sorted(values)
        return {'count':len(v),'p50_seconds':statistics.median(v) if v else None,'p95_seconds':v[max(0,math.ceil(.95*len(v))-1)] if v else None,'max_seconds':max(v,default=None)}
    return {'planning':quantiles(times),'candidate_generation':quantiles(generation),'generation_calls':len(generation),
            'successor_evaluations':evaluations,'max_evaluations':max(evaluations,default=0),
            'max_depth':max(depths,default=0),'max_beam':max(beams,default=0),
            'truncation_rate':sum(trunc)/len(trunc) if trunc else 0.,'budget_exceedances':sum(x>256 for x in evaluations),
            'timing_scope':'measured CPU planning/generation; not simulated arrival or robot throughput'}


def write_metrics(root,rows):
    write(root/'metrics/per_episode.json',rows);write(root/'metrics/summary.json',summarize(rows))
    groups=defaultdict(list)
    for r in rows:groups[(r['method'],r['backend'],r['source_order_key'])].append(r)
    write(root/'metrics/per_source.json',[{'method':m,'backend':b,'source':s,'tasks':len(v),
          'completed':sum(x['completed'] for x in v),'mean_item_ratio':statistics.mean(x['placed_item_ratio'] for x in v),
          'mean_volume_ratio':statistics.mean(x['placed_volume_ratio'] for x in v)} for (m,b,s),v in sorted(groups.items())])
    buf=io.StringIO();fields=['task_id','source_order_key','configuration','method','backend','planned_items','placed_items','completed','clean_completed','placed_item_ratio','placed_volume_ratio','termination_reason','wait_requests','non_head_commits','inversions','search_truncated_count']
    writer=csv.DictWriter(buf,fieldnames=fields,extrasaction='ignore',lineterminator='\n');writer.writeheader();writer.writerows(rows)
    (root/'metrics/per_episode.csv').write_text(buf.getvalue())
    write(root/'metrics/resources.json',resource_metrics(root,rows))


def _recompute(root,*,rerun=False):
    """Read-only verification; rerun reconstructs the full planner from frozen inputs."""
    root=Path(root);failures=[]
    if read(root/'delivery_manifest.json')['files']!=delivery_hashes(root):return {'status':'FAIL','failures':['delivery_hash'],'read_only':True}
    manifest=read(root/'manifest.json');inputs=read(root/'private/input_snapshot.json')
    if manifest['sources']!=sources():failures.append('source_drift')
    for name,value in manifest['sources'].items():
        if sha(root/'code_snapshot'/name)!=value:failures.append('code_snapshot_drift')
    if read(root/'config.snapshot.json')!=config():failures.append('configuration_drift')
    original,c_info=verify_c(manifest['c_baseline']['path'])
    if c_info!=manifest['c_baseline'] or inputs['tasks']!=original['tasks'][:len(inputs['tasks'])]:failures.append('baseline_task_drift')
    if manifest['input_digest']!=digest(inputs):failures.append('input_digest')
    if check_protected(read(root/'audit/protected.before.json'))['status']!='PASS':failures.append('protection')
    stored_rows=read(root/'metrics/per_episode.json');rows=[]
    keys={(r['task_id'],r['method'],r['backend']) for r in stored_rows}
    expected={(t['task_id'],m,b) for t in inputs['tasks'] for m,b in [(x,'oracle_ast') for x in METHODS]+[('buffer_search','public_parser')]}
    if keys!=expected or len(stored_rows)!=len(expected):failures.append('matrix_coverage')
    for old in stored_rows:
        events=read_jsonl(path_for(root,old['method'],old['backend'],old['task_id']))
        task=next(t for t in inputs['tasks'] if t['task_id']==old['task_id']);scenario=inputs['scenarios'][task['scenario_id']]
        if audit_events(events)['status']!='PASS':failures.append('event_audit:'+old['task_id'])
        for i,e in enumerate(events):
            if public_state(e['before_state'],task['instruction_text'])!=e['public_state'] or public_state(e['after_state'],task['instruction_text'])!=e['after_public_state']:failures.append('state_binding')
            if i and events[i-1]['after_state']!=e['before_state']:failures.append('event_chain')
        row=summary(scenario,task,old['method'],old['backend'],events,events[-1]['after_state']);rows.append(row)
        if row!=old:failures.append('metric_recomputation')
        if rerun:
            actual,trace,_=episode(scenario,inputs['data']['attributes'][task['scenario_id']]['objects'],task,old['method'],old['backend'],inputs['generator_config'])
            if actual!=old or stable(trace)!=stable(events):failures.append('trajectory_recomputation')
    if read(root/'metrics/summary.json')!=summarize(rows):failures.append('summary_recomputation')
    if read(root/'metrics/resources.json')!=resource_metrics(root,rows):failures.append('resources_recomputation')
    if rerun:
        for name,actual in [('gold',gold_results(inputs['generator_config'])),('constructs',run_constructs(inputs['generator_config'])),('diagnostics',diagnostics(inputs['generator_config']))]:
            if stable(read(root/f'cases/{name}.json'))!=stable(actual):failures.append('case_recomputation:'+name)
    repeats=read(root/'audit/repeat_resume.json')
    if len(repeats)!=len(rows):failures.append('repeat_coverage')
    for rec,row in zip(repeats,rows):
        ev=read_jsonl(path_for(root,row['method'],row['backend'],row['task_id']))
        h=digest(stable({'row':row,'events':ev}))
        if not rec['repeat_passed'] or not rec['resume_passed'] or any(rec[k]!=h for k in ('original_digest','repeat_digest','resume_digest')):failures.append('repeat_resume_digest')
    return {'status':'PASS' if not failures else 'FAIL','failures':sorted(set(failures)),'read_only':True,'episodes_checked':len(rows),'full_planner_rerun':rerun}


def recompute(root,*,rerun=False):
    try:return _recompute(root,rerun=rerun)
    except (ValueError,KeyError,TypeError,OSError,IndexError) as exc:
        return {'status':'FAIL','failures':[str(exc)],'read_only':True}


def tamper(root,rows):
    path=path_for(root,'buffer_search','oracle_ast',rows[0]['task_id']);original=path.read_bytes();manifest_path=root/'delivery_manifest.json';manifest_original=manifest_path.read_bytes();results=[]
    for kind in ('capacity','EOS','pending_set','simulated_commit'):
        events=read_jsonl(path)
        if kind=='capacity':events[0]['after_state']['buffer_capacity']=2
        elif kind=='EOS':events[0]['after_state']['end_of_stream']=True
        elif kind=='pending_set':events[0]['after_state']['pending_items']=[]
        else:
            e=next(e for e in events if e['kind']=='PLACE');e['search_trace']['chosen_path'][0]['pose']['z_base_mm']+=1
        try:
            write_jsonl(path,events);seal(root);result=recompute(root);results.append({'kind':kind,'detected':result['status']=='FAIL','reasons':result['failures']})
        finally:
            path.write_bytes(original);manifest_path.write_bytes(manifest_original)
    return results


def run(output,*,c_baseline=DEFAULT_C,config_path=None,limit=None,workers=1,protection_before=None):
    cfg=config(config_path);root=Path(output).resolve()
    if root.exists():raise FileExistsError('existing output directories are never overwritten')
    if workers<1 or workers>4:raise ValueError('workers must be 1..4')
    if any(p==root or p in root.parents for p in [WORKSPACE/'semantic_pallet_dataset_v1',WORKSPACE/'semantic_pallet_planner/src',Path(c_baseline).resolve()]):raise ValueError('protected output path')
    protected=read(protection_before) if protection_before else snapshot_existing()
    if check_protected(protected)['status']!='PASS':raise ValueError('protection changed before F')
    inputs,c_info=verify_c(c_baseline);inputs=copy.deepcopy(inputs);inputs['c_path']=str(Path(c_baseline).resolve())
    inputs['tasks']=inputs['tasks'][:limit] if limit else inputs['tasks']
    if limit is not None and limit<1:raise ValueError('positive task count')
    root.mkdir(parents=True)
    write(root/'private/input_snapshot.json',inputs);write(root/'config.snapshot.json',cfg)
    write(root/'audit/protected.before.json',protected)
    inventory=sources()
    for name in inventory:
        target=root/'code_snapshot'/name;target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(WORKSPACE/name,target)
    write(root/'manifest.json',{'version':'o4_f_buffer_v1','sources':inventory,'input_digest':digest(inputs),'c_baseline':c_info,'role':'development'})
    write(root/'plan.json',{'tasks':inputs['tasks'],'methods':list(METHODS),'logical_episodes':5*len(inputs['tasks']),
            'reused_episodes':0,'fresh_primary_episodes':5*len(inputs['tasks']),'repeat_episodes':5*len(inputs['tasks']),
            'resumed_episodes':5*len(inputs['tasks']),'source_role':'seen_train_development','independent_sources':len({t['source_order_key'] for t in inputs['tasks']}),
            'eos_mode':'empty_read','remote':False,'full_matrix':limit is None})
    with offline_network_guard() as ledger:
        gold=gold_results(inputs['generator_config']);constructs=run_constructs(inputs['generator_config']);diag=diagnostics(inputs['generator_config'])
        write(root/'cases/gold.json',gold);write(root/'cases/constructs.json',constructs);write(root/'cases/diagnostics.json',diag)
        payloads=[(str(root),inputs,t,cfg) for t in inputs['tasks']]
        rows=[];evidence=[];compat=[]
        if workers>1:
            with ProcessPoolExecutor(max_workers=workers,mp_context=multiprocessing.get_context('fork')) as pool:
                for r,e,c in pool.map(job,payloads):
                    rows.extend(r);evidence.extend(e);compat.append(c);print(f"F task {len(compat)}/{len(payloads)} completed",flush=True)
        else:
            for p in payloads:
                r,e,c=job(p);rows.extend(r);evidence.extend(e);compat.append(c);print(f"F task {len(compat)}/{len(payloads)} completed",flush=True)
        write_metrics(root,rows);write(root/'audit/repeat_resume.json',evidence);write(root/'audit/compatibility.json',compat)
        protect=check_protected(protected);write(root/'audit/protected.after.json',protect)
        attempts=ledger['network_attempts']+sum(c['network']['network_attempts'] for c in compat)
        write(root/'audit/network.json',{'network_attempts':attempts,'remote_calls':0})
        resources=read(root/'metrics/resources.json')
        criteria={'F1':len(gold)==24 and all(r['passed'] for r in gold) and all(r['event_audit']['status']=='PASS' for r in evidence),
          'F2':len(constructs)==12 and all(c['passed'] for c in constructs) and sum(c['decision_opportunity'] and c['reordered'] for c in constructs)==4 and sum(c['decision_opportunity'] and c['progress_gain']>0 for c in constructs)>=2 and sum(c['expected_no_progress_gain'] for c in constructs)>=4,
          'F3':len(rows)==360 and len(inputs['tasks'])==72 and all(c['parser_oracle_equal'] for c in compat),
          'F4':all(r['physical_violations']==r['final_business_violation_count']==r['reference_violating_commits']==0 for r in rows) and diag[0]['passed'],
          'F5':resources['budget_exceedances']==0 and resources['max_depth']<=3 and resources['max_beam']<=8,
          'F6':all(r['passed'] for r in diag if r['name'] not in ('wrong_valid_ast_visible','resume')),
          'F7':all(c['single_matches_c'] and c['fifo_matches_single'] for c in compat),
          'F8':all(r['repeat_passed'] and r['resume_passed'] for r in evidence),
          'F9':all(r['event_audit']['status']=='PASS' for r in evidence),
          'F10':protect['status']=='PASS' and attempts==0}
        acceptance={'status':'PENDING','scope':'O4_F_OFFLINE' if limit is None else 'O4_F_SMOKE','criteria':criteria,
                    'logical_episodes':len(rows),'reused_episodes':0,'fresh_primary_episodes':len(rows),'repeat_episodes':len(evidence),'resumed_episodes':len(evidence),
                    'deferred':{'A5':'FORMAL_IMAGES','A6':'HUMAN_REVIEW','D':'REAL_MODEL_NOT_RUN','E':'NOT_RUN'},'full_o4_status':'INCOMPLETE'}
        write(root/'buffer_acceptance.json',acceptance);seal(root)
        tampered=tamper(root,rows);write(root/'audit/tamper.json',tampered)
        criteria['F8']=criteria['F8'] and all(x['detected'] for x in tampered)
        acceptance['status']='PASS' if all(criteria.values()) else ('PARTIAL' if limit and all(v for k,v in criteria.items() if k!='F3') else 'FAIL')
        write(root/'buffer_acceptance.json',acceptance);seal(root)
        replay=recompute(root);write(root/'replay_report.json',replay)
        if replay['status']!='PASS':acceptance['status']='FAIL';acceptance['replay_failures']=replay['failures'];write(root/'buffer_acceptance.json',acceptance)
        seal(root)
    return acceptance


def resume(checkpoint,output):
    source=read(checkpoint);root=Path(output)
    if root.exists():raise FileExistsError('existing output directories are never overwritten')
    with offline_network_guard():
        row,events,_=episode(source['scenario'],source['attributes'],source['task'],source['method'],source['backend'],source['generator_config'],checkpoint=source['checkpoint'])
    root.mkdir(parents=True);write(root/'summary.json',row);write_jsonl(root/'events.jsonl',events)
    return {'status':'PASS','summary':row}


def rollout(output,*,c_baseline=DEFAULT_C,method='buffer_search',capacity=3,task_index=0):
    root=Path(output)
    if root.exists():raise FileExistsError('existing output directories are never overwritten')
    with offline_network_guard():
        inputs,_=verify_c(c_baseline);task=inputs['tasks'][task_index];sid=task['scenario_id']
        row,events,_=episode(inputs['scenarios'][sid],inputs['data']['attributes'][sid]['objects'],task,method,'oracle_ast',inputs['generator_config'],capacity=capacity)
    root.mkdir(parents=True);write(root/'summary.json',row);write_jsonl(root/'events.jsonl',events)
    return {'status':'PASS','scope':'single_task_rollout_not_full_acceptance','summary':row}


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('command',choices=['acceptance','smoke','replay','resume','rollout'])
    p.add_argument('--output',required=True);p.add_argument('--c-baseline',default=str(DEFAULT_C));p.add_argument('--config',default=str(DEFAULT_CONFIG))
    p.add_argument('--limit-tasks',type=int,default=2);p.add_argument('--workers',type=int,default=1);p.add_argument('--protection-before');p.add_argument('--checkpoint');p.add_argument('--rerun',action='store_true');p.add_argument('--capacity',type=int,choices=[1,2,3],default=3);p.add_argument('--method',choices=METHODS,default='buffer_search');p.add_argument('--task-index',type=int,default=0)
    a=p.parse_args(argv)
    if a.command=='replay':
        with offline_network_guard():result=recompute(a.output,rerun=a.rerun)
    elif a.command=='rollout':result=rollout(a.output,c_baseline=a.c_baseline,method=a.method,capacity=a.capacity,task_index=a.task_index)
    elif a.command=='resume':
        if not a.checkpoint:p.error('--checkpoint is required for resume')
        result=resume(a.checkpoint,a.output)
    else:result=run(a.output,c_baseline=a.c_baseline,config_path=a.config,limit=a.limit_tasks if a.command=='smoke' else None,workers=a.workers,protection_before=a.protection_before)
    print(canonical(result))
    if result['status'] not in ('PASS','PARTIAL'):raise SystemExit(1)

if __name__=='__main__':main()
