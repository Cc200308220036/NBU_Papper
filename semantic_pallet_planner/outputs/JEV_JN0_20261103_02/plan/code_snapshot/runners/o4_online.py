"""O4-C offline complete-order rollout, paired audit and read-only replay.

Flash/remote execution belongs to O4-D and is intentionally unavailable here.
"""
import argparse
import contextlib
import copy
import csv
import hashlib
import io
import json
import socket
from collections import Counter,defaultdict
from pathlib import Path
from unittest.mock import patch

import yaml

from ..config import WORKSPACE,load_config,generator_config
from ..domain import PalletState
from ..evaluation.replay_values_v2 import replay_values_equal
from ..o4.common import canonical,digest,read,write
from ..o4.online.episode import episode
from ..o4.online.validation import evaluate_fixed,invariance_checks,legacy_equivalence,diagnostics
from ..o4.online.cases import opportunity_cases,run_opportunities
from ..repository import DatasetRepository
from .o4 import snapshot_existing,check_protected

VERSION='o4_c_online_v1'
DEFAULT_BASELINE=WORKSPACE/'semantic_pallet_planner/outputs/EXP_O4_AB_OFFLINE_20261021_01'
DEFAULT_CONFIG=WORKSPACE/'semantic_pallet_planner/configs/o4_c_online.yaml'
METHODS=('public_parser','oracle_ast')


def sha(path):
    with Path(path).open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()


def load_online_config(path=None):
    cfg=yaml.safe_load(Path(path or DEFAULT_CONFIG).read_text())
    expected={'schema_version':'o4_c_online_config_v1','seed':20261021,'buffer_size':1,'top_k':16,
        'topk_mode':'diverse_v1','methods':list(METHODS),'layout':'relaxed_geometry',
        'soft_order':['heavy_low','heavy_center'],'soft_budgets':[.05,.25],
        'policy_epsilon':1e-6,'ranking_epsilon':1e-12,'replay_abs_tolerance':1e-9,
        'remote':False,'execution_mode':'safe'}
    if canonical(cfg)!=canonical(expected):raise ValueError('C v1 configuration is frozen; change requires a new version')
    return cfg


@contextlib.contextmanager
def offline_network_guard():
    ledger={'network_attempts':0,'remote_calls':0}
    def blocked(*args,**kwargs):
        ledger['network_attempts']+=1
        raise RuntimeError('O4-C forbids network access')
    with patch.object(socket,'create_connection',blocked),patch.object(socket.socket,'connect',blocked),patch.object(socket.socket,'connect_ex',blocked):
        yield ledger


def source_hashes():
    package=WORKSPACE/'semantic_pallet_planner/src/semantic_pallet_planner'
    paths=[p for p in package.rglob('*.py') if '__pycache__' not in p.parts]
    paths+=list((package/'schemas').glob('*.json'))+[DEFAULT_CONFIG,WORKSPACE/'semantic_pallet_planner/configs/o4_ab_offline.yaml']
    return {str(p.relative_to(WORKSPACE)):sha(p) for p in sorted(paths)}


def delivery_hashes(root):
    root=Path(root)
    return {str(p.relative_to(root)):sha(p) for p in sorted(root.rglob('*'))
            if p.is_file() and p.relative_to(root)!=Path('delivery_manifest.json')}


def seal(root):write(Path(root)/'delivery_manifest.json',{'files':delivery_hashes(root)})


def verify_ab(baseline):
    baseline=Path(baseline).resolve()
    stored=read(baseline/'delivery_manifest.json')['files']
    actual={str(p.relative_to(baseline)):sha(p) for p in baseline.rglob('*') if p.is_file() and p.name!='delivery_manifest.json'}
    if actual!=stored:raise ValueError('A/B delivery file hashes changed')
    manifest=read(baseline/'manifest.json')
    if any(sha(WORKSPACE/name)!=value for name,value in manifest['source_sha256'].items()):
        raise ValueError('frozen A/B source changed')
    data=read(baseline/'private/data.json')
    if digest(data)!=manifest['data_digest']:raise ValueError('A/B data digest mismatch')
    acceptance=read(baseline/'acceptance_report.json')
    if acceptance['status']!='PASS' or len(data['order_tasks'])!=72 or len(data['pairs'])!=144:
        raise ValueError('requires accepted full A/B development baseline')
    return data,{'path':str(baseline),'manifest_sha256':sha(baseline/'manifest.json'),
                 'delivery_manifest_sha256':sha(baseline/'delivery_manifest.json'),'data_digest':digest(data)}


def write_jsonl(path,records):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(''.join(canonical(r)+'\n' for r in records))


def read_jsonl(path):return [json.loads(line) for line in Path(path).read_text().splitlines() if line]


def episode_path(root,method,task_id):return Path(root)/'episodes'/method/task_id/'steps.jsonl'


def aggregate(rows):
    groups=defaultdict(list)
    for r in rows:groups[(r['method'],r['configuration'])].append(r)
    result=[]
    for (method,configuration),items in sorted(groups.items()):
        result.append({'method':method,'configuration':configuration,'planned_tasks':len(items),
            'completed':sum(r['completed'] for r in items),'clean_completed':sum(r['clean_completed'] for r in items),
            'completion_rate':sum(r['completed'] for r in items)/len(items),
            'clean_completion_rate':sum(r['clean_completed'] for r in items)/len(items),
            'mean_item_ratio':sum(r['placed_item_ratio'] for r in items)/len(items),
            'mean_volume_ratio':sum(r['placed_volume_ratio'] for r in items)/len(items),
            'placed_items':sum(r['placed_items'] for r in items),
            'final_business_violation_count':sum(r['final_business_violation_count'] for r in items),
            'physical_violations':sum(r['physical_violations'] for r in items),
            'termination_counts':dict(Counter(r['termination_reason'] for r in items))})
    return result


def csv_text(rows):
    buffer=io.StringIO(newline='')
    fields=['task_id','scenario_id','source_order_key','configuration','method','planned_items','placed_items',
        'completed','clean_completed','placed_item_ratio','placed_volume_ratio','final_business_violation_count',
        'violating_steps','business_violation_step_rate','ever_violating','physical_violations','termination_reason','decision_records','remote_calls']
    writer=csv.DictWriter(buffer,fieldnames=fields,lineterminator='\n',extrasaction='ignore')
    writer.writeheader();writer.writerows(rows)
    return buffer.getvalue()


def evaluate_orders(inputs,root=None,*,repeat=False):
    rows=[];agreements=[];replications=[]
    for task in inputs['tasks']:
        sid=task['scenario_id'];scenario=inputs['scenarios'][sid]
        attributes=inputs['data']['attributes'][sid]['objects'];runs={}
        for method in METHODS:
            row,events=episode(scenario,attributes,task,method,inputs['generator_config'])
            rows.append(row);runs[method]=(row,events)
            if root is not None:
                write_jsonl(episode_path(root,method,task['task_id']),events)
                for event in events:
                    write(Path(root)/'selector_inputs'/method/task['task_id']/f"{event['step_index']:03d}.json",event['request'])
            if repeat:
                row2,events2=episode(scenario,attributes,task,method,inputs['generator_config'])
                replications.append({'task_id':task['task_id'],'method':method,
                    'first_digest':digest({'summary':row,'events':events}),'repeat_digest':digest({'summary':row2,'events':events2}),
                    'passed':replay_values_equal(row,row2) and replay_values_equal(events,events2)})
        left,left_events=runs['public_parser'];right,right_events=runs['oracle_ast']
        left={k:v for k,v in left.items() if k!='method'};right={k:v for k,v in right.items() if k!='method'}
        agreements.append({'task_id':task['task_id'],'episodes':2,
            'candidate_sets_equal':replay_values_equal([e['raw_candidates'] for e in left_events],[e['raw_candidates'] for e in right_events]),
            'requests_equal':replay_values_equal([e['request'] for e in left_events],[e['request'] for e in right_events]),
            'trajectory_equal':replay_values_equal(left_events,right_events),
            'summary_equal':replay_values_equal(left,right),
            'passed':replay_values_equal(left_events,right_events) and replay_values_equal(left,right)})
    return rows,agreements,replications


def initial_checks(inputs,fixed,opportunities,invariants,legacy,diag,rows,agreements,replications,protected,ledger):
    all_tasks=len(inputs['tasks'])==72 and len({t['task_id'] for t in inputs['tasks']})==72
    return {
        'C1':all_tasks and len(rows)==144 and all(r['termination_reason'] for r in rows),
        'C2':len(fixed['records'])==144 and fixed['passed'],
        'C3':len(opportunities)>=6 and all(r['passed'] for r in opportunities) and
             sum(r['action_changed'] for r in opportunities)>=3 and all(r['passed'] for r in invariants),
        'C4':len(agreements)==len(inputs['tasks']) and all(r['passed'] for r in agreements) and all(r['passed'] for r in legacy),
        'C5':all(r['physical_violations']==0 and r['physical_rejections']==0 for r in rows) and all(r['passed'] for r in diag),
        'C6':len(replications)==len(rows) and all(r['passed'] for r in replications),
        'C7':False,
        'C8':protected['status']=='PASS' and ledger['network_attempts']==ledger['remote_calls']==0,
    }


def counts(inputs,rows,fixed):
    return {'source_orders':len({t['source_order_key'] for t in inputs['tasks']}),
        'planned_tasks_per_method':len(inputs['tasks']),'planned_episodes':2*len(inputs['tasks']),
        'recorded_episodes':len(rows),'decision_records':sum(r['decision_records'] for r in rows),
        'placed_items':sum(r['placed_items'] for r in rows),'fixed_records':len(fixed['records']),
        'fixed_reference_opportunity_pairs':fixed['opportunity_pairs'],'fixed_action_change_pairs':fixed['action_change_pairs'],
        'remote_calls':0,'network_attempts':0}


def audit_soft_budgets(root,inputs):
    checked=0;failures=[]
    for task in inputs['tasks']:
        for method in METHODS:
            for event in read_jsonl(episode_path(root,method,task['task_id'])):
                trace=event['trace']
                if 'soft_loss_from_anchor' not in trace:continue
                for loss,budget in zip(trace['soft_loss_from_anchor'],(.05,.25)):
                    if loss is not None:
                        checked+=1
                        if loss>budget+1e-6:failures.append(event['request']['request_id'])
    return {'status':'PASS' if not failures else 'FAIL','checks':checked,'failures':failures}


def replay(output,*,check_protection=True):
    root=Path(output).resolve()
    with offline_network_guard() as ledger:
        try:
            if read(root/'delivery_manifest.json')['files']!=delivery_hashes(root):
                return {'status':'FAIL','failures':['delivery file set/hash mismatch'],'read_only':True}
            manifest=read(root/'manifest.json')
            if manifest['source_sha256']!=source_hashes():raise ValueError('C source/schema/config drift')
            inputs=read(root/'private/input_snapshot.json')
            if digest(inputs)!=manifest['input_digest']:raise ValueError('input snapshot digest mismatch')
            data,baseline=verify_ab(manifest['baseline']['path'])
            if baseline!=manifest['baseline'] or inputs['data']!=data:raise ValueError('A/B baseline/input mismatch')
            if inputs['tasks']!=data['order_tasks'][:len(inputs['tasks'])]:raise ValueError('task plan differs from frozen baseline')
            if read(root/'config.snapshot.json')!=load_online_config():raise ValueError('configuration drift')
            for name,value in manifest['source_sha256'].items():
                if sha(root/'code_snapshot'/name)!=value:raise ValueError('source snapshot drift')
            repository=DatasetRepository(inputs['dataset_root'])
            for sid,scenario in inputs['scenarios'].items():
                if repository.get_scenario(sid)!=scenario:raise ValueError('source scenario differs from snapshot')
            if check_protection and check_protected(read(root/'audit/protected.before.json'))['status']!='PASS':
                raise ValueError('protected input/source changed')
            fixed=evaluate_fixed(data);opportunities=run_opportunities(inputs['opportunity_cases'])
            invariants=invariance_checks();legacy=legacy_equivalence(data);diag=diagnostics(inputs['generator_config'])
            rows=[];failures=[];runs=defaultdict(dict)
            for task in inputs['tasks']:
                sid=task['scenario_id']
                for method in METHODS:
                    row,events=episode(inputs['scenarios'][sid],data['attributes'][sid]['objects'],task,method,inputs['generator_config'])
                    saved=read_jsonl(episode_path(root,method,task['task_id']))
                    if not replay_values_equal(saved,events):failures.append(f"episode:{method}/{task['task_id']}")
                    for e in events:
                        request=read(root/'selector_inputs'/method/task['task_id']/f"{e['step_index']:03d}.json")
                        if not replay_values_equal(request,e['request']):failures.append('public request drift')
                    rows.append(row);runs[task['task_id']][method]=(row,events)
            expected={'fixed':fixed,'opportunities':opportunities,'invariance':invariants,'legacy_equivalence':legacy,
                      'diagnostics':diag,'per_episode':rows,'summary':aggregate(rows)}
            for name,value in expected.items():
                if not replay_values_equal(read(root/f'metrics/{name}.json'),value):failures.append(name+' recomputation')
            if (root/'metrics/per_episode.csv').read_text()!=csv_text(rows):failures.append('CSV recomputation')
            repetitions=read(root/'audit/repeat_run.json')
            expected_keys={(t['task_id'],m) for t in inputs['tasks'] for m in METHODS}
            if len(repetitions)!=len(rows) or {(r['task_id'],r['method']) for r in repetitions}!=expected_keys:
                failures.append('repeat evidence coverage')
            original_rows={(r['task_id'],r['method']):r for r in read(root/'metrics/per_episode.json')}
            for record in repetitions:
                key=(record['task_id'],record['method'])
                saved_events=read_jsonl(episode_path(root,record['method'],record['task_id']))
                value=digest({'summary':original_rows[key],'events':saved_events})
                if record['first_digest']!=value or record['repeat_digest']!=value or not record['passed']:
                    failures.append('repeat evidence mismatch')
            agreement=read(root/'audit/parser_oracle_agreement.json')
            if len(agreement)!=len(inputs['tasks']):failures.append('agreement coverage')
            tamper=read(root/'audit/tamper.json')
            if {r['kind'] for r in tamper}!={'AST','action','mapping','summary'} or not all(r['detected'] for r in tamper):
                failures.append('tamper audit coverage')
            for record in agreement:
                l,le=runs[record['task_id']]['public_parser'];r,re=runs[record['task_id']]['oracle_ast']
                if not record['passed'] or not replay_values_equal(le,re):failures.append('agreement mismatch')
            if not all(r['passed'] for r in opportunities+invariants+legacy+diag):failures.append('diagnostics failure')
            if not fixed['passed']:failures.append('fixed failure')
            budget=audit_soft_budgets(root,inputs)
            if budget!=read(root/'audit/soft_budgets.json') or budget['status']!='PASS':failures.append('soft budgets')
            acceptance=read(root/'offline_acceptance.json')
            if acceptance['counts']!=counts(inputs,rows,fixed):failures.append('acceptance counts')
            if any(acceptance['criteria'][k] is not True for k in acceptance['criteria'] if k!='C1'):
                failures.append('acceptance criteria')
            if len(inputs['tasks'])==72 and not acceptance['criteria']['C1']:failures.append('full matrix gate')
            return {'status':'PASS' if not failures else 'FAIL','failures':failures,
                    'counts':counts(inputs,rows,fixed),'read_only':True,'network_attempts':ledger['network_attempts']}
        except (ValueError,KeyError,OSError,TypeError) as exc:
            return {'status':'FAIL','failures':[str(exc)],'read_only':True}


def tamper_audit(root,task):
    path=episode_path(root,'public_parser',task['task_id'])
    original=path.read_bytes();summary_path=root/'metrics/summary.json';summary=summary_path.read_bytes()
    rows=[]
    for kind in ('AST','action','mapping','summary'):
        try:
            if kind=='summary':
                values=read(summary_path);values[0]['completed']+=1;write(summary_path,values)
            else:
                events=read_jsonl(path)
                target=next(e for e in events if e['response'] is not None)
                if kind=='AST':target['response']['policy_ast']['rules']=[]
                elif kind=='action':target['committed_label']='C99'
                else:target['candidate_mapping']['C99']={'tampered':True}
                write_jsonl(path,events)
            result=replay(root)
            rows.append({'kind':kind,'detected':result['status']=='FAIL','reason':result['failures']})
        finally:
            path.write_bytes(original);summary_path.write_bytes(summary)
    return rows


def run(output,*,baseline=DEFAULT_BASELINE,config=None,protection_before=None,task_limit=None):
    with offline_network_guard() as ledger:
        return _run(output,baseline,config,protection_before,task_limit,ledger)


def _run(output,baseline,config,protection_before,task_limit,ledger):
    root=Path(output).resolve();cfg=load_online_config(config)
    if root.exists():raise FileExistsError('choose a new output directory')
    baseline=Path(baseline).resolve()
    forbidden=[WORKSPACE/'semantic_pallet_dataset_v1',WORKSPACE/'semantic_pallet_planner/src',baseline]
    if any(root==p or p in root.parents for p in forbidden):raise ValueError('output would modify protected inputs')
    protected=read(protection_before) if protection_before else snapshot_existing()
    if check_protected(protected)['status']!='PASS':raise ValueError('protected files changed before C')
    data,baseline_info=verify_ab(baseline)
    tasks=data['order_tasks'] if task_limit is None else data['order_tasks'][:task_limit]
    if not tasks or (task_limit is not None and task_limit<1):raise ValueError('positive smoke task limit required')
    repo=DatasetRepository(read(baseline/'manifest.json')['dataset_root'])
    cfg_gen=generator_config(load_config(dataset=str(repo.root),top_k=16,topk_mode='diverse_v1'))
    inputs={'data':data,'tasks':tasks,'dataset_root':str(repo.root),'generator_config':cfg_gen,
            'scenarios':{t['scenario_id']:repo.get_scenario(t['scenario_id']) for t in tasks},
            'opportunity_cases':opportunity_cases()}
    root.mkdir(parents=True)
    write(root/'private/input_snapshot.json',inputs);write(root/'config.snapshot.json',cfg)
    write(root/'plan.json',{'methods':list(METHODS),'tasks':tasks,'planned_episodes':2*len(tasks),
                          'source_role':'development','independent_sources':len({t['source_order_key'] for t in tasks}),
                          'fixed_records':144,'remote_calls':0,'full_matrix':task_limit is None})
    frozen=source_hashes()
    for name in frozen:
        target=root/'code_snapshot'/name;target.parent.mkdir(parents=True,exist_ok=True)
        target.write_bytes((WORKSPACE/name).read_bytes())
    write(root/'manifest.json',{'version':VERSION,'source_sha256':frozen,'input_digest':digest(inputs),
        'baseline':baseline_info,'role':'development','remote':False,'full_o4_status':'INCOMPLETE'})
    fixed=evaluate_fixed(data);opportunities=run_opportunities(inputs['opportunity_cases'])
    invariants=invariance_checks();legacy=legacy_equivalence(data);diag=diagnostics(cfg_gen)
    rows,agreements,replications=evaluate_orders(inputs,root,repeat=True)
    for name,value in {'fixed':fixed,'opportunities':opportunities,'invariance':invariants,
                       'legacy_equivalence':legacy,'diagnostics':diag,'per_episode':rows,'summary':aggregate(rows)}.items():
        write(root/f'metrics/{name}.json',value)
    (root/'metrics/per_episode.csv').write_text(csv_text(rows))
    write(root/'audit/repeat_run.json',replications);write(root/'audit/parser_oracle_agreement.json',agreements)
    write(root/'audit/protected.before.json',protected)
    protection=check_protected(protected);write(root/'audit/protected.after.json',protection)
    budgets=audit_soft_budgets(root,inputs);write(root/'audit/soft_budgets.json',budgets)
    write(root/'audit/network.json',ledger)
    criteria=initial_checks(inputs,fixed,opportunities,invariants,legacy,diag,rows,agreements,replications,protection,ledger)
    criteria['C5']=criteria['C5'] and budgets['status']=='PASS'
    acceptance={'status':'PENDING','scope':'O4_C_OFFLINE' if task_limit is None else 'O4_C_SMOKE',
                'criteria':criteria,'counts':counts(inputs,rows,fixed),'full_o4_status':'INCOMPLETE',
                'deferred':{'A5':'FORMAL_IMAGES','A6':'HUMAN_REVIEW','F':'NOT_RUN','D':'NOT_RUN'},
                'evidence':{'C1':'metrics/per_episode.json','C2':'metrics/fixed.json',
                 'C3':'metrics/opportunities.json + metrics/invariance.json',
                 'C4':'audit/parser_oracle_agreement.json + metrics/legacy_equivalence.json',
                 'C5':'metrics/diagnostics.json + audit/soft_budgets.json',
                 'C6':'audit/repeat_run.json + replay_report.json','C7':'audit/tamper.json',
                 'C8':'audit/protected.after.json + audit/network.json'}}
    write(root/'offline_acceptance.json',acceptance)
    seal(root)
    tampered=tamper_audit(root,tasks[0]);write(root/'audit/tamper.json',tampered)
    criteria['C7']=all(r['detected'] for r in tampered)
    acceptance['status']='PASS' if all(criteria.values()) else ('PARTIAL' if task_limit is not None and all(v for k,v in criteria.items() if k!='C1') else 'FAIL')
    acceptance['criteria']=criteria
    write(root/'offline_acceptance.json',acceptance)
    (root/'README.md').write_text('# O4-C完整订单离线交付\n\n'
        +f"范围状态：{acceptance['status']}；完整O4尚未完成。\n\n"
        +'固定业务AST后的独立在线轨迹、原始提议/提交、物理与参考业务复核、配对、重复运行和回放均保存。\n'
        +'public_parser和oracle_ast共用O4 relaxed_geometry排序；Oracle只提供特权AST，不是全局最优规划器。\n'
        +'所有任务保留在分母；构造机会对不代表自然订单总体收益。Flash调用0，O4-F/D及正式图像未执行。\n\n'
        +'回放：python -m semantic_pallet_planner.runners.o4_online replay --output <本目录>\n')
    seal(root)
    verified=replay(root)
    write(root/'replay_report.json',verified)
    if verified['status']!='PASS':
        acceptance['status']='FAIL';acceptance['replay_failures']=verified['failures']
        write(root/'offline_acceptance.json',acceptance)
    seal(root)
    return acceptance


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('command',choices=['acceptance','smoke','replay'])
    p.add_argument('--output',required=True);p.add_argument('--baseline',default=str(DEFAULT_BASELINE))
    p.add_argument('--config',default=str(DEFAULT_CONFIG));p.add_argument('--protection-before')
    p.add_argument('--limit-tasks',type=int,default=2,help='smoke only; never satisfies full C1')
    args=p.parse_args(argv)
    if args.command=='replay':result=replay(args.output)
    else:result=run(args.output,baseline=args.baseline,config=args.config,protection_before=args.protection_before,
                    task_limit=args.limit_tasks if args.command=='smoke' else None)
    print(canonical(result))
    if result['status'] not in ('PASS','PARTIAL'):raise SystemExit(1)

if __name__=='__main__':main()
