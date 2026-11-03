"""Build an offline O1b language/policy development release from untouched train orders.

All source and template selection is deterministic and completed before model calls.
No source test labels, future items, hidden policies, or physical IDs enter public requests.
"""
from __future__ import annotations

import argparse
import copy
import json
import random
import shutil
from collections import Counter, defaultdict
from pathlib import Path

from ..config import WORKSPACE, generator_config, load_config
from ..domain import PalletState
from ..evaluation.attribute_metrics_v2 import public_relations, reconstruct
from ..evaluation.policy_v2 import evaluate, optimal_set
from ..evaluation.policy_o1b import resolve
from ..planner.generator import ExtremePointGenerator
from ..planner.scoring import geometry_score
from ..protocol import state_hash
from ..repository import ALL_SPLITS, DatasetRepository
from ..selectors.instruction_parser_o1b import (policy, canonical_text, paraphrase_text,
    conditional_envelope, conditional_text, parse_o1b_instruction, resolved_public_policy)
from ..vlm.pilot_protocol_v2 import digest, scan_public
from .attribute_pilot_v2 import enumerate_physical, read_json, sha, write_csv, write_json
from .protocol_o2a import source_order, inventory_digest

VERSION = 'attribute_o1b_development_1'
DEFAULT_OUTPUT = WORKSPACE/'semantic_pallet_planner/outputs/EXP_OPT_O1B_LANGUAGE_PILOT_20261009_03'
V2 = WORKSPACE/'semantic_pallet_planner/outputs/EXP_OPT_V2_PILOT_20260929_04'
O2A = [WORKSPACE/f'semantic_pallet_planner/outputs/EXP_OPT_V3_PROTOCOL_PILOT_20261008_{n}' for n in ('01','02')]
V1 = WORKSPACE/'semantic_pallet_planner/outputs/EXP_1C_DEEPSEEK_FLASH_FINAL_V1'
SOFT0 = ('heavy_low', 'heavy_center')
SOFT1 = ('heavy_center', 'heavy_low')


def all_source_orders(repo):
    grouped = defaultdict(list)
    for split in ALL_SPLITS:
        for sid in repo.list_scenarios(split):
            a = read_json(repo.root/'annotations/ground_truth_rules'/f'{sid}.json')
            key = str(a.get('source_order_key', a.get('source_order_id', sid)))
            grouped[split].append(key)
    return {k:set(v) for k,v in grouped.items()}


def source_selection(repo):
    groups = defaultdict(list)
    for cid in repo.list_cases('train'):
        case = repo.get_decision_case(cid)
        groups[source_order(repo, case)].append(cid)
    sorted_orders = sorted(groups)
    if len(sorted_orders) != 50:
        raise ValueError(f'Expected 50 train source orders, got {len(sorted_orders)}')
    selected = sorted_orders[20:]
    original = all_source_orders(repo)
    test = set().union(*(v for k,v in original.items() if k.startswith('test')))
    old_v2 = {str(x['source_order_key']) for x in read_json(V2/'data/source_manifest.json')}
    old_o2a = set()
    for folder in O2A:
        old_o2a.update(str(x['source_order_key']) for x in read_json(folder/'data/source_manifest.json'))
    audit = {'original_split':'train', 'derived_role':'development_validation',
             'original_validation_source_count':len(original['validation']),
             'selected_independent_source_orders':len(selected),
             'selection_rule':'sorted train source_order_key positions 20..49; first two tens used by O2a',
             'source_keys':selected, 'overlap_original_validation':sorted(set(selected)&original['validation']),
             'overlap_v2_pilot':sorted(set(selected)&old_v2),
             'overlap_o2a':sorted(set(selected)&old_o2a),
             'overlap_all_test_splits':sorted(set(selected)&test),
             'test_labels_used_for_selection':False,
             'language_template_boundary':{'A':'V2 canonical grammar control',
                'B':'new-to-V2 paraphrase, disclosed in O1b development parser; not unseen to O2b parser',
                'C':'published conditional heavy-item policy envelope and priority switch',
                'future_test':'must use separate source orders and newly frozen template families'},
             'policy_combination_boundary':'A/B choose two V2 primitive policies from a frozen threshold/contact/priority catalog; C branches over the same pair'}
    if any(audit[k] for k in ('overlap_original_validation','overlap_v2_pilot','overlap_o2a','overlap_all_test_splits')):
        raise ValueError('source leakage')
    return [(key, sorted(groups[key])) for key in selected], audit


POLICY_CATALOG = [policy(float(threshold), order, contact)
                  for threshold in (0, 1, 3, 5, 10)
                  for contact in (False, True)
                  for order in (SOFT0, SOFT1)]
DEFAULT_PAIR = (policy(1., SOFT0, True), policy(3., SOFT1, True))


def chosen_policy_pair(p):
    """Select a differentiating pair by frozen semantic opportunity, never model output."""
    if not p['physical_candidates']:
        return DEFAULT_PAIR, (-1, 0, 0)
    state=p['state']; container=p['scenario']['container']
    options=[]
    for pol in POLICY_CATALOG:
        result=optimal_set([evaluate(state,c,pol,container) for c in p['physical_candidates']])
        options.append(set(result['equivalent_indices']))
    best=None
    for i,a in enumerate(options):
        for j in range(i+1,len(options)):
            b=options[j]
            disjoint=bool(a and b and a.isdisjoint(b))
            different=bool(a and b and a!=b)
            # Prefer a true policy-induced choice switch, then stable catalog order.
            rank=(int(disjoint),int(different),int(bool(a and b)))
            if best is None or rank>best[0]: best=(rank,i,j)
    if best and best[0][0]:
        return (POLICY_CATALOG[best[1]],POLICY_CATALOG[best[2]]),best[0]
    return DEFAULT_PAIR,(0,0,0)


def policy_views(state, pair):
    p0,p1=pair
    base={'available_items':state['available_items'],'buffer_size':1}
    envelopes=[conditional_envelope(p0,p1,False),conditional_envelope(p0,p1,True)]
    return {'A':[p0,p1],'B':[p0,p1],
            'C':[resolve(e,base) for e in envelopes]},envelopes


def build_physical(case_id, group_id, repo, gen):
    case = repo.get_decision_case(case_id)
    scenario = repo.get_scenario(case['base_scenario_id'])
    if scenario['buffer_size'] != 1 or len(case['available_items']) != 1:
        raise ValueError('buffer_size=1 is required')
    state = {k:copy.deepcopy(case[k]) for k in ('placed_items','available_items')}
    state.update(container=scenario['container'], request_id=group_id)
    state['placed_items'] = reconstruct(state['placed_items'])
    candidates = gen.generate(PalletState.from_dict(state)).candidate_set.data['candidates']
    random.Random(20261009+int(group_id.split('_')[-1])).shuffle(candidates)
    visible = []
    for i,c in enumerate(candidates):
        v = {k:copy.deepcopy(c[k]) for k in ('pick_item_id','pose','oriented_size_mm','support','load',
                                              'resulting_geometry','geometry_score_components')}
        v.update(display_label=f'C{i+1:02d}', geometry_score=geometry_score(c),
                 public_relations=public_relations(state,c))
        visible.append(v)
    return {'case':case, 'scenario':scenario, 'state':state, 'physical_candidates':candidates,
            'public_candidates':visible,
            'mapping':{v['display_label']:c['candidate_id'] for v,c in zip(visible,candidates)}}


def pair_status(evaluations0, evaluations1):
    opt0, opt1 = optimal_set(evaluations0), optimal_set(evaluations1)
    s0, s1 = set(opt0['equivalent_indices']), set(opt1['equivalent_indices'])
    return {'different_optimal_equivalence_sets':bool(s0 and s1 and s0!=s1),
            'disjoint_optimal_equivalence_sets':bool(s0 and s1 and s0.isdisjoint(s1)),
            'both_feasible':bool(opt0['feasible_indices'] and opt1['feasible_indices'])}


def score_physical(p):
    _,rank=chosen_policy_pair(p)
    return (*rank,len(p['physical_candidates']))


def public_request(p, track, variant, instruction):
    state = p['state']
    req = {'schema_version':'pallet_request_v2_pilot',
           'request_id':f"O1B_{state['request_id']}_{track}{variant}",
           'state_hash':state_hash(state['container'],state),
           'policy_digest':digest({'grammar':'o1b_instruction_1','instruction_text':instruction}),
           'instruction_text':instruction, 'container':state['container'],
           'placed_items':state['placed_items'], 'available_items':state['available_items'],
           'candidates':p['public_candidates'], 'buffer_size':1}
    scan = scan_public(req,p['mapping'].values())
    if scan['status']!='PASS':
        raise ValueError('public request leakage: '+str(scan['hits']))
    return req


def previous_no_feasible():
    """Read-only regression summary from the old V2 pilot; no new model calls."""
    data = read_json(V2/'data/pilot_dataset.private.json')
    ids = sorted(d['public_request']['request_id'] for d in data
                 if d['coverage']['topk_feasible_count']==0)
    old_rows = read_json(V2/'metrics/per_decision.json')
    methods = sorted({r['method'] for r in old_rows})
    outcomes = {m:dict(Counter(r['status'] for r in old_rows
                         if r['request_id'] in ids and r['method']==m)) for m in methods}
    return {'source':'V2 regression only', 'count':len(ids), 'request_ids':ids,
            'observed_old_v2_status_by_method':outcomes,
            'flash_old_v2_abstain':outcomes['flash_direct_text'].get('abstain',0),
            'flash_old_v2_wrong_submission':outcomes['flash_direct_text'].get('select',0),
            'flash_old_v2_invalid':outcomes['flash_direct_text'].get('invalid_response',0),
            'abstain_expected':True, 'new_model_results':None,
            'explanation':'Old no-feasible cases are regression only, not new validation or model successes.'}


def build(output):
    if output.exists():
        raise FileExistsError(f'Refusing to overwrite {output}')
    cfg = load_config(top_k=16)
    repo = DatasetRepository(cfg['dataset'])
    selected, split_audit = source_selection(repo)
    before = {k:inventory_digest(v) for k,v in {'v1':V1,'v2':V2,'o2a_01':O2A[0],'o2a_02':O2A[1]}.items()}
    gen = ExtremePointGenerator(generator_config(cfg))
    output.mkdir(parents=True)
    tasks, groups, generation, coverage, pairs, manifests = [], [], [], [], [], []
    for gi,(source,cids) in enumerate(selected,1):
        gid = f'GROUP_{gi:03d}'
        options = []
        for cid in cids:
            p = build_physical(cid,gid,repo,gen)
            score = score_physical(p)
            generation.append({'source_order_key':source,'source_case_id':cid,'score':list(score),
                               'retained':False,'reason':'candidate_or_policy_opportunity_screen'})
            options.append((score,cid,p))
        # Fixed policy-opportunity screen, never uses model behavior; keep every order.
        score,cid,p = max(options,key=lambda x:(x[0],-int(x[1].split('_')[-1])))
        if not p['physical_candidates']:
            raise ValueError(f'No candidate in source order {source}')
        for row in generation[-len(cids):]:
            if row['source_case_id']==cid:
                row.update(retained=True,reason='selected_one_state_per_source_order')
        chosen_pair, pair_rank = chosen_policy_pair(p)
        views,envelopes = policy_views(p['state'],chosen_pair)
        full = enumerate_physical(p['state'],generator_config(cfg))
        if len(full)<len(p['physical_candidates']):
            raise ValueError('full physical enumeration smaller than Top-K')
        physical = {'group_id':gid,'source_order_key':source,'source_case_id':cid,
                    'state':p['state'],'public_candidates':p['public_candidates'],
                    'physical_candidates':p['physical_candidates'],'mapping':p['mapping'],
                    'state_hash':state_hash(p['state']['container'],p['state'])}
        write_json(output/'data/physical_groups'/f'{gid}.private.json',physical)
        manifests.append({'physical_group_id':gid,'source_order_key':source,'source_case_id':cid,
                          'original_split':'train','derived_role':'development_validation',
                          'source_case_sha256':sha(repo.root/'tasks/decision_cases'/f'{cid}.json'),
                          'source_scenario_id':p['case']['base_scenario_id'],
                          'candidate_count':len(p['physical_candidates']),
                          'full_enumerated_candidate_count':len(full), 'selection_score':list(score),
                          'policy_pair':list(chosen_pair)})
        group_tasks = {}
        for track in ('A','B','C'):
            for variant in (0,1):
                pol = views[track][variant]
                if track=='A': instruction=canonical_text(chosen_pair[variant])
                elif track=='B': instruction=paraphrase_text(chosen_pair[variant])
                else: instruction=conditional_text(*chosen_pair,reverse=bool(variant))
                req = public_request(p,track,variant,instruction)
                parsed = parse_o1b_instruction(instruction)
                if resolved_public_policy(instruction,req)!=pol:
                    raise ValueError('public parser / truth disagreement')
                evals = [evaluate(p['state'],c,pol,p['scenario']['container']) for c in p['physical_candidates']]
                optimum = optimal_set(evals)
                full_evals = [evaluate(p['state'],c,pol,p['scenario']['container']) for c in full]
                full_feasible = sum(not e['after_violation_instances'] for e in full_evals)
                topk_feasible = len(optimum['feasible_indices'])
                if full_feasible<topk_feasible:
                    raise ValueError('candidate coverage inconsistency')
                geometry_i = min(range(len(p['physical_candidates'])),
                                 key=lambda i:(-p['public_candidates'][i]['geometry_score'],p['public_candidates'][i]['display_label']))
                cov = {'physical_group_id':gid,'request_id':req['request_id'],'track':track,'variant':variant,
                       'source_order_key':source,'hard_applicable':any(e['business_hard_applicable'] for e in evals),
                       'topk_feasible_count':topk_feasible,'full_feasible_count':full_feasible,
                       'coverage_category':'topk_covered' if topk_feasible else ('topk_lost' if full_feasible else 'enumeration_no_feasible'),
                       'equivalent_labels':[p['public_candidates'][i]['display_label'] for i in optimum['equivalent_indices']],
                       'geometry_label':p['public_candidates'][geometry_i]['display_label'],
                       'geometry_in_optimal_set':geometry_i in optimum['equivalent_indices'],
                       'attribute_provenance':'synthetic'}
                task={'request_id':req['request_id'],'physical_group_id':gid,'source_order_key':source,
                      'track':track,'variant':variant,'template_family':{'A':'canonical_v2','B':'paraphrase_o1b','C':'conditional_o1b'}[track],
                      'original_split':'train','derived_role':'development_validation',
                      'public_request_path':f"data/public_requests/{req['request_id']}.json",
                      'hidden_policy_ast':envelopes[variant] if track=='C' else pol,
                      'resolved_policy':pol,'evaluations':evals,'optimum':optimum,'coverage':cov,
                      'policy_truth_origin':'deterministic_template_plus_public_current_item',
                      'human_ast_reviewer_1':None,'human_ast_reviewer_2':None,'human_ast_review_status':'PENDING'}
                write_json(output/task['public_request_path'],req)
                tasks.append(task); coverage.append(cov); group_tasks[(track,variant)] = task
        for track in ('A','B','C'):
            x,y = group_tasks[(track,0)],group_tasks[(track,1)]
            status = pair_status(x['evaluations'],y['evaluations'])
            row={'physical_group_id':gid,'source_order_key':source,'track':track,
                 'request_0':x['request_id'],'request_1':y['request_id'],**status,
                 'classification':'opportunity' if status['different_optimal_equivalence_sets'] else 'control'}
            pairs.append(row)
        groups.append(gid)
    # Cross-reference, counterfactual and paraphrase invariants.
    byid={t['request_id']:t for t in tasks}
    for gid in groups:
        local=[t for t in tasks if t['physical_group_id']==gid]
        requests=[read_json(output/t['public_request_path']) for t in local]
        if len({r['state_hash'] for r in requests})!=1 or len({digest(r['candidates']) for r in requests})!=1:
            raise ValueError('paired physical state/candidate mismatch')
        for variant in (0,1):
            a=byid[f'O1B_{gid}_A{variant}']; b=byid[f'O1B_{gid}_B{variant}']
            if a['resolved_policy']!=b['resolved_policy'] or a['optimum']!=b['optimum']:
                raise ValueError('paraphrase changed policy or optimum')
    if len(groups)!=30 or len(tasks)!=180 or len(set(m['source_order_key'] for m in manifests))!=30:
        raise ValueError('O1b scale mismatch')
    split_audit.update(status='PASS', physical_group_count=len(groups), task_count=len(tasks),
                       paired_variants_share_state_candidates_mapping=True,
                       candidate_generator='frozen V2 extreme-point Top-K 16',buffer_size=1,
                       all_selection_before_model_calls=True)
    write_json(output/'data/split_audit.json',split_audit)
    write_json(output/'data/source_manifest.json',manifests)
    write_json(output/'data/tasks.private.json',tasks)
    write_json(output/'data/generation_audit.json',generation)
    write_json(output/'data/coverage_report.json',coverage)
    write_csv(output/'metrics/coverage.csv',coverage)
    write_csv(output/'metrics/policy_pairs.csv',pairs)
    write_json(output/'audit/old_no_feasible_regression.json',previous_no_feasible())
    review=[{'request_id':t['request_id'],'source_order_key':t['source_order_key'],'track':t['track'],
             'instruction_text':read_json(output/t['public_request_path'])['instruction_text'],
             'condition_or_exception':t['hidden_policy_ast'].get('condition') if t['track']=='C' else None,
             'expected_ast':t['hidden_policy_ast'],'resolved_policy':t['resolved_policy'],
             'object_and_threshold_check':'','hard_soft_priority_check':'','reviewer_1':'','reviewer_2':'',
             'final_disposition':'PENDING'} for t in tasks]
    write_csv(output/'audit/ast_human_review_queue.csv',review)
    (output/'audit/review_instructions.md').write_text(
        '# O1b AST人工复核说明\n\n两名独立复核者分别从公开指令和当前公开物料属性推导对象、限载阈值、'
        '接触禁止、硬软类型、条件分支和优先级；先独立填写，不查看对方判断。'
        '随后与机器生成AST对照，冲突保留原始意见并仲裁。'
        '本发布时无人签认，不得将程序一致率当作人工真值。\n',encoding='utf-8')
    write_csv(output/'audit/maintenance_cost_template.csv',[
        {'component':'public_parser_o1b','change_request':'A/B/C published grammar',
         'reading_person_hours':None,'implementation_person_hours':None,
         'test_person_hours':None,'review_person_hours':None,'rule_changes':3,
         'remaining_known_errors':'unknown until independent review'},
        {'component':'llm_prompt_ast_schema','change_request':'O2b future control',
         'reading_person_hours':None,'implementation_person_hours':None,
         'test_person_hours':None,'review_person_hours':None,'rule_changes':0,
         'remaining_known_errors':'not implemented in O1b'}])
    after={k:inventory_digest(v) for k,v in {'v1':V1,'v2':V2,'o2a_01':O2A[0],'o2a_02':O2A[1]}.items()}
    integrity={'status':'PASS' if before==after else 'FAIL','before':before,'after':after}
    write_json(output/'checks/historical_integrity.json',integrity)
    if integrity['status']!='PASS': raise ValueError('historical artifacts changed')
    counts=Counter(x['coverage_category'] for x in coverage)
    pair_counts=Counter(x['classification'] for x in pairs)
    report={'status':'PASS_AUTOMATED_HUMAN_PENDING','source_orders':len(groups),'tasks':len(tasks),
            'generated_state_attempts':len(generation),'selected_states':sum(x['retained'] for x in generation),
            'rejected_states':sum(not x['retained'] for x in generation),
            'candidate_coverage':dict(counts),'policy_pair_classification':dict(pair_counts),
            'semantic_opportunity_rate':pair_counts['opportunity']/len(pairs),
            'old_v2_no_feasible_regression_cases':previous_no_feasible()['count'],
            'opportunity_source_orders':len({r['source_order_key'] for r in pairs if r['classification']=='opportunity'}),
            'human_ast_double_review':'PENDING','model_calls':0,
            'attribute_provenance':'synthetic','original_validation_source_count':10,
            'derived_validation_source_count':30,
            'research_claim':'No model advantage assessed in O1b.'}
    write_json(output/'acceptance_report.json',report)
    sources=['evaluation/policy_o1b.py','selectors/instruction_parser_o1b.py','runners/attribute_o1b.py',
             'evaluation/policy_v2.py','evaluation/attribute_metrics_v2.py','planner/generator.py']
    code_root=WORKSPACE/'semantic_pallet_planner/src/semantic_pallet_planner'
    for name in sources:
        path=code_root/name; target=output/'code_snapshot'/name
        target.parent.mkdir(parents=True,exist_ok=True); shutil.copyfile(path,target)
    for schema_name in ('policy_o1b.schema.json','o1b_request.schema.json'):
        shutil.copyfile(code_root/'schemas'/schema_name,output/'code_snapshot'/schema_name)
    write_json(output/'manifest.json',{'version':VERSION,'config':cfg,
        'code_sha256':{name:sha(code_root/name) for name in sources},
        'schema_sha256':{name:sha(code_root/'schemas'/name) for name in ('policy_o1b.schema.json','o1b_request.schema.json')},
        'dataset_source_root':str(repo.root), 'source_manifest_sha256':sha(output/'data/source_manifest.json'),
        'tasks_private_sha256':sha(output/'data/tasks.private.json'),
        'public_request_count':len(tasks), 'source_selection_frozen_before_remote_calls':True,
        'remote_calls_performed':0})
    (output/'o1b_report.md').write_text(
        f"# O1b 数据与语言政策开发记录\n\n原始train来源重新划出{len(groups)}个互不重叠订单作开发验证，"
        f"每组1个状态、A/B/C三轨各2条政策，共{len(tasks)}题。不是原validation或未见test。"
        f"筛查{len(generation)}个状态，保留{len(groups)}、未选{len(generation)-len(groups)}。\n\n"
        f"Top-K覆盖：{dict(counts)}；政策配对：{dict(pair_counts)}，独立机会来源"
        f"{len({r['source_order_key'] for r in pairs if r['classification']=='opportunity'})}/30。旧V2无可行题"
        f"{previous_no_feasible()['count']}道保留为回归，未运行新模型。"
        f"A/B为相同AST的语言改写；C仅用已知V2规则原语与公开当前箱条件。"
        f"所有真值AST由确定性模板生成并经公开解析器机器核对；双人独立人工复核待完成。\n",
        encoding='utf-8')
    return report


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,default=DEFAULT_OUTPUT)
    args=parser.parse_args()
    print(json.dumps(build(args.output.resolve()),ensure_ascii=False))


if __name__=='__main__':
    main()
