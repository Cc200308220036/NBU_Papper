"""Actual full 360-episode replay, parallel CPU execution; read-only delivery."""
import sys
sys.path.insert(0,'semantic_pallet_planner/src')
import multiprocessing
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from semantic_pallet_planner.o4.common import read,write,digest
from semantic_pallet_planner.o4.buffer.buffer_evaluation import episode,stable,summary
from semantic_pallet_planner.o4.buffer.cases import run_constructs
from semantic_pallet_planner.o4.buffer.validation import gold_results,diagnostics
from semantic_pallet_planner.runners.o4_buffer import recompute,path_for,read_jsonl,offline_network_guard,delivery_hashes
ROOT=Path('semantic_pallet_planner/outputs/EXP_O4_F_BUFFER_20261021_01')
OUT=Path('report/analysis/O4_F_BUFFER_20261021_01')

def verify(payload):
    row,scenario,attributes,task,config=payload
    if row.get('_stream'):
        old=read_jsonl(path_for(ROOT,row['method'],row['backend'],row['task_id']))
        row=summary(scenario,task,row['method'],row['backend'],old,old[-1]['after_state'])
    with offline_network_guard() as ledger:
        actual,events,_=episode(scenario,attributes,task,row['method'],row['backend'],config)
        old=read_jsonl(path_for(ROOT,row['method'],row['backend'],row['task_id']))
        return {'task_id':row['task_id'],'method':row['method'],'backend':row['backend'],
                'passed':actual==row and stable(events)==stable(old),
                'expected_digest':digest(stable({'row':row,'events':old})),
                'actual_digest':digest(stable({'row':actual,'events':events})),
                'network_attempts':ledger['network_attempts']}

def main():
    inputs=read(ROOT/'private/input_snapshot.json');tasks={t['task_id']:t for t in inputs['tasks']}
    keys=[(t['task_id'],m,b) for t in inputs['tasks'] for m,b in [(x,'oracle_ast') for x in ('single_greedy','buffer_fifo','buffer_heuristic','buffer_search')]+[('buffer_search','public_parser')]]
    checks=[];submitted=set();futures={}
    with ProcessPoolExecutor(max_workers=4,mp_context=multiprocessing.get_context('fork')) as pool:
        while len(checks)<len(keys):
            for tid,m,b in keys:
                key=(tid,m,b)
                if key in submitted or not (ROOT/'checkpoints'/f'{m}__{b}'/(tid+'.json')).exists():continue
                t=tasks[tid];sid=t['scenario_id']
                row={'_stream':True,'task_id':tid,'method':m,'backend':b}
                payload=(row,inputs['scenarios'][sid],inputs['data']['attributes'][sid]['objects'],t,inputs['generator_config'])
                futures[pool.submit(verify,payload)]=key;submitted.add(key)
            done=[f for f in futures if f.done()]
            for f in done:
                checks.append(f.result());del futures[f]
                if len(checks)%20==0:print('replayed',len(checks),'/',len(keys),flush=True)
            if len(checks)<len(keys):time.sleep(2)
    # Wait for the primary writer's terminal sealed delivery, then verify it read-only.
    while True:
        manifest=ROOT/'delivery_manifest.json'
        if manifest.exists():
            try:
                files=read(manifest)['files']
                if 'replay_report.json' in files:break
            except (ValueError,KeyError):pass
        time.sleep(2)
    rows=read(ROOT/'metrics/per_episode.json');before=delivery_hashes(ROOT)
    structural=recompute(ROOT)
    case_checks={}
    with offline_network_guard() as ledger:
        for name,actual in [('gold',gold_results(inputs['generator_config'])),('constructs',run_constructs(inputs['generator_config'])),('diagnostics',diagnostics(inputs['generator_config']))]:
            case_checks[name]=stable(read(ROOT/f'cases/{name}.json'))==stable(actual)
    after=delivery_hashes(ROOT)
    failures=[]
    if len(checks)!=360 or not all(c['passed'] and c['network_attempts']==0 for c in checks):failures.append('full_episode_recomputation')
    if structural['status']!='PASS':failures.extend(structural['failures'])
    if not all(case_checks.values()):failures.append('case_recomputation')
    if before!=after:failures.append('read_only')
    result={'status':'PASS' if not failures else 'FAIL','failures':failures,'read_only':before==after,'full_planner_rerun':True,
            'episodes_checked':len(checks),'episode_checks':checks,'case_checks':case_checks,'structural_replay':structural,
            'network_attempts':sum(c['network_attempts'] for c in checks)+ledger['network_attempts'],
            'command':'python report/analysis/O4_F_BUFFER_20261021_01/parallel_full_replay.py','execution':'streamed from completed primary checkpoints; every episode rerun from empty' }
    write(OUT/'full_rerun_replay.json',result)
    print(result['status'],result['failures'],flush=True)
    if failures:raise SystemExit(1)
if __name__=='__main__':main()
