"""Offline layout ablations with source snapshots, public-only selection and replay."""
from __future__ import annotations

import argparse
import copy
import json
import math
import shutil
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
from jsonschema import Draft202012Validator

from ..config import WORKSPACE, generator_config, load_config
from ..domain import PalletState
from ..evaluation.attribute_metrics_v2 import reconstruct
from ..evaluation.geometry_oracle import check_candidate
from ..evaluation.layout_preservation import PROBE_FRACTIONS, MIN_HEADROOM_FRACTION
from ..evaluation.policy_v2 import evaluate, violations
from ..evaluation.replay_values_v2 import replay_values_equal
from ..evaluation.state import apply_candidate, state_metrics
from ..planner.generator import ExtremePointGenerator
from ..protocol import canonical_json, state_hash
from ..repository import DatasetRepository
from ..selectors.instruction_parser_o1b import resolved_public_policy
from ..selectors.layout_preserving import VARIANTS, SOFT_BUDGETS, select_layout
from ..vlm.pilot_protocol_v2 import digest
from .attribute_o3_online import step_state, task_plan
from .attribute_pilot_v2 import read_json, sha, write_csv, write_json
from .o3_online_adapter import public_request, screen

VERSION='layout_preservation_ablation_v1'
SOURCE=Path(__file__).resolve().parents[1]
PROTOCOL=WORKSPACE/'docs/02_阶段实施方案/O3/O3布局保留机制与消融协议_20261019.md'
REFERENCES={
    'safe':WORKSPACE/'semantic_pallet_planner/outputs/EXP_OPT_O3B_ONLINE_VALIDATION_20261016_REMOTE_01',
    'observe_business':WORKSPACE/'semantic_pallet_planner/outputs/EXP_OPT_O3B_BUSINESS_OBSERVE_20261016_REMOTE_01'}


def inventory(root):
    return {str(p.relative_to(root)):sha(p) for p in sorted(root.rglob('*')) if p.is_file()}


def episode(root,scenario,task,variant,mode,cfg):
    gen=ExtremePointGenerator(generator_config(cfg))
    validator=Draft202012Validator(read_json(SOURCE/'schemas/o3_request.schema.json'))
    directory=root/'episodes'/mode/variant/task['episode_id']
    directory.mkdir(parents=True)
    placed=[];events=[]
    for index in range(len(scenario['arrival_order'])):
        state=step_state(scenario,task,placed,index)
        generated=gen.generate(PalletState.from_dict(state))
        req,mapping,scan=public_request(state,generated.candidate_set.data['candidates'],task['instruction_text'],seed=cfg['seed'])
        validator.validate(req)
        assert scan['status']=='PASS'
        public_policy=resolved_public_policy(req['instruction_text'],req)
        evaluations=[evaluate(req,c,public_policy,req['container']) for c in req['candidates']]
        feasible=any(not e['after_violation_instances'] for e in evaluations)
        proposed=committed=None;trace={};would_block=False;blocked=False;physical=[];raw=None
        if not mapping:
            status='no_physical_candidate'
        elif mode=='safe' and not feasible:
            status='no_business_feasible_candidate'
        else:
            proposed,trace=select_layout(req,public_policy,variant,allow_business_violation=mode=='observe_business')
            screened,would_block,screen_status=screen(req,proposed,evaluations)
            if mode=='safe':
                committed,blocked,status=screened,would_block,screen_status
            else:
                committed,status=proposed,None
            if proposed is not None:
                c=mapping[proposed]
                raw=evaluate(req,c,task['truth_policy'],req['container'])
                if feasible:
                    assert not evaluations[next(i for i,c in enumerate(req['candidates']) if c['display_label']==proposed)]['after_violation_instances']
            if committed is not None:
                physical=check_candidate(req,{'container':req['container']},mapping[committed])
                if physical:
                    raise ValueError('physical rejection: '+str(physical))
                placed=apply_candidate(state,mapping[committed])
                status='all_items_placed' if index==len(scenario['arrival_order'])-1 else 'select'
            status=status or 'selector_abstain'
        after=step_state(scenario,task,placed,index+1)
        events.append({'step_index':index,'request':req,'candidate_set_digest':digest(req['candidates']),
            'proposed_label':proposed,'committed_label':committed,'trace':trace,
            'before_state_hash':req['state_hash'],
            'after_state_hash':state_hash(req['container'],after) if committed else req['state_hash'],
            'after_placed':copy.deepcopy(placed),'generation_audit':generated.audit.data,
            'would_screen_block':would_block,'screen_intervened':blocked,'physical_errors':physical,
            'raw_evaluation':raw,'status':status})
        if not committed or status=='all_items_placed':
            break
    final,_=violations(reconstruct(placed),task['truth_policy'])
    planned=len(scenario['arrival_order'])
    violating=sum(bool(e['committed_label']) and bool(e['raw_evaluation']['new_business_violation_count']+
                    e['raw_evaluation']['worsened_existing_violation_count']) for e in events)
    losses=[e['trace'].get('soft_loss_from_anchor',[]) for e in events if e['committed_label']]
    summary={'episode_id':task['episode_id'],'scenario_id':task['scenario_id'],
        'source_order_key':task['source_order_key'],'policy_id':task['policy_id'],
        'mode':mode,'variant':variant,'planned_items':planned,'placed_items':len(placed),
        'completed':len(placed)==planned,'clean_completed':len(placed)==planned and not final,
        'placed_item_ratio':len(placed)/planned,
        'placed_volume_ratio':sum(math.prod(p['oriented_size_mm']) for p in placed)/
          sum(math.prod(list(p['dimensions_mm'].values())) for p in scenario['items']),
        'final_business_violation_count':len(final),'final_violation_ids':final,
        'violating_steps':violating,'business_violation_step_rate':violating/len(placed) if placed else None,
        'changed_from_original_steps':sum(e['trace'].get('changed_from_original',False) for e in events),
        'max_soft_loss_from_anchor':max((x for loss in losses for x in loss if x is not None),default=0.),
        'termination_reason':events[-1]['status'],'physical_violations':0,
        'final_geometry':state_metrics(scenario['container'],placed)}
    (directory/'steps.jsonl').write_text(''.join(canonical_json(e)+'\n' for e in events))
    write_json(directory/'episode.json',{'task':task,'summary':summary,'events_digest':digest(events)})
    return summary


def replay(root,tasks,variants,modes,cfg,repo):
    failures=[];count=steps=0;baseline_steps=0
    gen=ExtremePointGenerator(generator_config(cfg))
    validator=Draft202012Validator(read_json(SOURCE/'schemas/o3_request.schema.json'))
    for mode in modes:
        for task in tasks:
            scenario=repo.get_scenario(task['scenario_id'])
            for variant in variants:
                directory=root/'episodes'/mode/variant/task['episode_id']
                record=read_json(directory/'episode.json')
                events=[json.loads(x) for x in (directory/'steps.jsonl').read_text().splitlines()]
                assert record['events_digest']==digest(events)
                placed=[]
                for index,e in enumerate(events):
                    prefix=f"{mode}/{variant}/{task['episode_id']}/{index}"
                    state=step_state(scenario,task,placed,index)
                    generated=gen.generate(PalletState.from_dict(state))
                    req,mapping,scan=public_request(state,generated.candidate_set.data['candidates'],task['instruction_text'],seed=cfg['seed'])
                    validator.validate(e['request'])
                    if not replay_values_equal(req,e['request']) or scan['status']!='PASS':
                        failures.append(prefix+':request')
                    if e['before_state_hash']!=req['state_hash'] or e['candidate_set_digest']!=digest(e['request']['candidates']):
                        failures.append(prefix+':bindings')
                    if generated.audit.data!=e['generation_audit']:
                        failures.append(prefix+':generation_audit')
                    policy=resolved_public_policy(req['instruction_text'],req)
                    values=[evaluate(req,c,policy,req['container']) for c in req['candidates']]
                    feasible=any(not v['after_violation_instances'] for v in values)
                    if not mapping:
                        label=None;trace={};status='no_physical_candidate'
                    elif mode=='safe' and not feasible:
                        label=None;trace={};status='no_business_feasible_candidate'
                    else:
                        label,trace=select_layout(req,policy,variant,allow_business_violation=mode=='observe_business')
                        status='all_items_placed' if index==len(scenario['arrival_order'])-1 else 'select'
                    if label!=e['proposed_label'] or label!=e['committed_label'] or not replay_values_equal(trace,e['trace']):
                        failures.append(prefix+':selection')
                    if e['status']!=status:
                        failures.append(prefix+':termination')
                    would_block=False
                    if label:
                        if check_candidate(req,{'container':req['container']},mapping[label]):
                            failures.append(prefix+':physics')
                        _,would_block,_=screen(req,label,values)
                        if mode=='safe' and would_block:
                            failures.append(prefix+':safe_screen')
                        raw=evaluate(req,mapping[label],task['truth_policy'],req['container'])
                        if not replay_values_equal(raw,e['raw_evaluation']):
                            failures.append(prefix+':business')
                        placed=apply_candidate(state,mapping[label])
                    elif e['raw_evaluation'] is not None:
                        failures.append(prefix+':null_business')
                    if e['would_screen_block']!=would_block or e['screen_intervened'] or e['physical_errors']:
                        failures.append(prefix+':screen_or_physics_record')
                    expected_hash=state_hash(req['container'],step_state(scenario,task,placed,index+1)) if label else req['state_hash']
                    if not replay_values_equal(placed,e['after_placed']) or e['after_state_hash']!=expected_hash:
                        failures.append(prefix+':transition')
                    if e['step_index']!=index or (not label and index!=len(events)-1):
                        failures.append(prefix+':event_order')
                    steps+=1
                final,_=violations(reconstruct(placed),task['truth_policy'])
                s=record['summary']
                planned=len(scenario['arrival_order'])
                violating=sum(bool(e['committed_label']) and bool(e['raw_evaluation']['new_business_violation_count']+
                    e['raw_evaluation']['worsened_existing_violation_count']) for e in events)
                losses=[e['trace'].get('soft_loss_from_anchor',[]) for e in events if e['committed_label']]
                expected={'episode_id':task['episode_id'],'scenario_id':task['scenario_id'],
                    'source_order_key':task['source_order_key'],'policy_id':task['policy_id'],
                    'mode':mode,'variant':variant,'planned_items':planned,'placed_items':len(placed),
                    'completed':len(placed)==planned,'clean_completed':len(placed)==planned and not final,
                    'placed_item_ratio':len(placed)/planned,
                    'placed_volume_ratio':sum(math.prod(p['oriented_size_mm']) for p in placed)/
                        sum(math.prod(list(p['dimensions_mm'].values())) for p in scenario['items']),
                    'final_business_violation_count':len(final),'final_violation_ids':final,
                    'violating_steps':violating,'business_violation_step_rate':violating/len(placed) if placed else None,
                    'changed_from_original_steps':sum(e['trace'].get('changed_from_original',False) for e in events),
                    'max_soft_loss_from_anchor':max((x for loss in losses for x in loss if x is not None),default=0.),
                    'termination_reason':events[-1]['status'],'physical_violations':0,
                    'final_geometry':state_metrics(scenario['container'],placed)}
                if not replay_values_equal(s,expected):
                    failures.append(prefix+':summary')
                count+=1
                if variant=='original' and task['source_split']=='validation':
                    reference=REFERENCES[mode]/'episodes/public_parser'/task['episode_id']/'steps.jsonl'
                    old=[json.loads(x) for x in reference.read_text().splitlines()]
                    if len(old)!=len(events) or any(a['before_state_hash']!=b['before_state_hash'] or
                        a['after_state_hash']!=b['after_state_hash'] or a['committed_label']!=b['committed_label']
                        for a,b in zip(old,events)):
                        failures.append(f'{mode}/{task["episode_id"]}:historical_baseline')
                    baseline_steps+=len(old)
    return {'status':'PASS' if not failures else 'FAIL','episodes':count,'steps':steps,
            'historical_baseline_steps_compared':baseline_steps,'failures':failures}


def report(root,rows):
    aggregate={};comparisons=[]
    for mode in sorted({r['mode'] for r in rows}):
        aggregate[mode]={}
        for variant in sorted({r['variant'] for r in rows}):
            data=[r for r in rows if r['mode']==mode and r['variant']==variant]
            total=sum(r['placed_items'] for r in data)
            aggregate[mode][variant]={'episodes':len(data),'completed':sum(r['completed'] for r in data),
                'clean_completed':sum(r['clean_completed'] for r in data),
                'mean_placed_item_ratio':float(np.mean([r['placed_item_ratio'] for r in data])),
                'mean_placed_volume_ratio':float(np.mean([r['placed_volume_ratio'] for r in data])),
                'violating_steps':sum(r['violating_steps'] for r in data),'placed_steps':total,
                'micro_violation_step_rate':sum(r['violating_steps'] for r in data)/total if total else None,
                'final_business_violation_instances':sum(r['final_business_violation_count'] for r in data),
                'changed_from_original_steps':sum(r['changed_from_original_steps'] for r in data),
                'termination_reasons':dict(Counter(r['termination_reason'] for r in data))}
        for reference in ('original','relaxed_geometry'):
            for variant in aggregate[mode]:
                if variant==reference or reference not in aggregate[mode]:
                    continue
                for metric in ('clean_completed','completed','placed_item_ratio','final_business_violation_count'):
                    groups=defaultdict(list)
                    lookup={(r['episode_id'],r['variant']):r for r in rows if r['mode']==mode}
                    for r in rows:
                        if r['mode']==mode and r['variant']==variant:
                            groups[r['source_order_key']].append(float(r[metric])-float(lookup[r['episode_id'],reference][metric]))
                    delta=np.array([np.mean(v) for _,v in sorted(groups.items())])
                    rng=np.random.default_rng(20261019)
                    boot=rng.choice(delta,size=(5000,len(delta)),replace=True).mean(axis=1)
                    comparisons.append({'mode':mode,'variant':variant,'reference':reference,'metric':metric,
                        'source_order_clusters':len(delta),'mean_difference':float(delta.mean()),
                        'exploratory_95_ci':np.quantile(boot,[.025,.975]).tolist(),
                        'multiplicity_adjusted':False,'new_test':False})
    write_json(root/'metrics/summary.json',aggregate)
    write_json(root/'metrics/paired_cluster_comparisons.json',comparisons)
    write_csv(root/'metrics/per_episode.csv',rows)
    lines=['# Layout preservation ablation — development results','',
           'Strict and relaxed policies are separate. No Flash calls. Seen validation, no new-test claim.','']
    for mode,values in aggregate.items():
        lines += [f'## {mode}','','| Variant | Completed | Clean | Mean item ratio | Violation steps / placed | Final instances |',
                  '|---|---:|---:|---:|---:|---:|']
        for name,v in values.items():
            lines.append(f"| {name} | {v['completed']}/{v['episodes']} | {v['clean_completed']}/{v['episodes']} | "
                         f"{v['mean_placed_item_ratio']:.2%} | {v['violating_steps']}/{v['placed_steps']} | {v['final_business_violation_instances']} |")
        lines.append('')
    (root/'results.md').write_text('\n'.join(lines)+'\n')
    return aggregate


def run(root,split='validation',limit_orders=10,variants=VARIANTS,modes=('safe','observe_business')):
    root=Path(root).resolve()
    if root.exists():
        raise FileExistsError('use a fresh output directory')
    if any(v not in VARIANTS for v in variants) or len(set(variants))!=len(variants):
        raise ValueError('invalid variants')
    if not modes or any(m not in REFERENCES for m in modes):
        raise ValueError('invalid execution modes')
    if any(root==r or root in r.parents or r in root.parents for r in REFERENCES.values()):
        raise ValueError('output overlaps protected source run')
    cfg=load_config(seed=20261015,top_k=16,topk_mode='diverse_v1',fallback_policy='abort')
    repo=DatasetRepository(cfg['dataset'])
    tasks,audit=task_plan(repo,split,limit_orders)
    original_inventories={m:inventory(r) for m,r in REFERENCES.items()}
    root.mkdir(parents=True)
    code={str(p.relative_to(SOURCE)):sha(p) for p in sorted(SOURCE.rglob('*')) if p.is_file() and p.suffix in ('.py','.json')}
    for name in code:
        dest=root/'code_snapshot'/name;dest.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(SOURCE/name,dest)
    shutil.copyfile(PROTOCOL,root/'protocol.snapshot.md')
    used={t['scenario_id'] for t in tasks}
    data={f'tasks/scenarios/{sid}.json':sha(repo.root/f'tasks/scenarios/{sid}.json') for sid in sorted(used)}
    data['configs/mvd_v0.1.json']=sha(repo.root/'configs/mvd_v0.1.json')
    write_json(root/'manifest.json',{'version':VERSION,'source_sha256':code,'dataset_sha256':data,
        'variants':list(variants),'modes':list(modes),'planned_episodes':len(tasks)*len(variants)*len(modes),
        'soft_budgets':SOFT_BUDGETS,'probe_fractions':PROBE_FRACTIONS,'min_headroom_fraction':MIN_HEADROOM_FRACTION,
        'protocol_sha256':sha(PROTOCOL),'remote_calls':0,'buffer_size':1,'top_k':16,
        'development_only':True,'new_test':False})
    write_json(root/'config.snapshot.json',cfg)
    write_json(root/'data/tasks.private.json',tasks)
    write_json(root/'data/source_audit.json',audit)
    write_json(root/'audit/protected_runs.before.json',original_inventories)
    rows=[]
    for mode in modes:
        for task in tasks:
            scenario=repo.get_scenario(task['scenario_id'])
            for variant in variants:
                s=episode(root,scenario,task,variant,mode,cfg)
                rows.append(s)
                print(mode,task['episode_id'],variant,f"{s['placed_items']}/{s['planned_items']}",
                      'clean',s['clean_completed'],flush=True)
    aggregate=report(root,rows)
    print('Starting full independent replay and historical baseline comparison',flush=True)
    replay_result=replay(root,tasks,variants,modes,cfg,repo)
    write_json(root/'replay_report.json',replay_result)
    changed=[]
    for mode,path in REFERENCES.items():
        if inventory(path)!=original_inventories[mode]:
            changed.append(mode)
    code_changed=[p for p,h in code.items() if sha(SOURCE/p)!=h]
    data_changed=[p for p,h in data.items() if sha(repo.root/p)!=h]
    checks={'planned_episodes_recorded':len(rows)==len(tasks)*len(variants)*len(modes),
            'full_replay':replay_result['status']=='PASS','protected_runs_unchanged':not changed,
            'source_version_unchanged':not code_changed,'physical_violations_zero':all(r['physical_violations']==0 for r in rows),
            'source_split_clean':not audit['cross_split_overlap'],'dataset_unchanged':not data_changed}
    acceptance={'status':'PASS' if all(checks.values()) else 'FAIL','checks':checks,
        'episodes':len(rows),'protected_run_files':{m:len(v) for m,v in original_inventories.items()},
        'changed_protected_runs':changed,'changed_source_files':code_changed,'changed_dataset_files':data_changed,
        'research_status':'EXPLORATORY_DEVELOPMENT_ONLY','vlm_advantage':'NOT_TESTED','remote_calls':0}
    write_json(root/'acceptance_report.json',acceptance)
    return acceptance


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--output',type=Path,required=True)
    ap.add_argument('--split',choices=('train','validation'),default='validation')
    ap.add_argument('--limit-orders',type=int,default=10)
    ap.add_argument('--variants',nargs='+',choices=VARIANTS,default=list(VARIANTS))
    args=ap.parse_args()
    result=run(args.output,args.split,args.limit_orders,tuple(args.variants))
    print(json.dumps(result,ensure_ascii=False,indent=2))
    if result['status']!='PASS':
        raise SystemExit(1)


if __name__=='__main__':
    main()
