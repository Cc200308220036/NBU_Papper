"""O2a protocol pilot: immutable V2 audit and train-derived held-out development pair.

No test split is used. Remote calls require an explicitly configured API key.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import random
import shutil
import statistics
import subprocess
import time
from collections import Counter, defaultdict

from ..config import WORKSPACE, generator_config, load_config
from ..domain import PalletState
from ..protocol import canonical_json, state_hash
from ..repository import DatasetRepository, ALL_SPLITS
from ..planner.generator import ExtremePointGenerator
from ..planner.scoring import geometry_score
from ..evaluation.attribute_metrics_v2 import reconstruct, public_relations
from ..evaluation.policy_v2 import evaluate, optimal_set
from ..selectors.instruction_parser_v2 import instruction_from_policy, parse_instruction
from ..selectors.policy_executor_v2 import public_parser
from ..vlm.client import ModelRequest
from ..vlm.deepseek_client import DeepSeekClient
from ..vlm.pilot_protocol_v2 import (SYSTEM_PROMPT as OLD_PROMPT, parse_choice as parse_old,
                                     scan_public, digest)
from ..vlm.protocol_o2a import (VERSION as CHOICE_VERSION, PROMPT_VERSION, SYSTEM_PROMPT,
                               ChoiceProtocolError, parse_choice as parse_new,
                               model_request as new_model_request)
from .attribute_pilot_v2 import (policy_for, response_row, enumerate_physical,
                                  write_json, read_json, write_csv, sha)

VERSION = 'attribute_o2a_protocol_pilot_2'
DEFAULT_PARENT = WORKSPACE/'semantic_pallet_planner/outputs/EXP_OPT_V2_PILOT_20260929_04'
DEFAULT_V1 = WORKSPACE/'semantic_pallet_planner/outputs/EXP_1C_DEEPSEEK_FLASH_FINAL_V1'
N_SOURCE_ORDERS = 10
SOURCE_ORDER_OFFSET = 10


def source_order(repo, case):
    path = repo.root/'annotations/ground_truth_rules'/f"{case['base_scenario_id']}.json"
    a = json.loads(path.read_text())
    return str(a.get('source_order_key', a.get('source_order_id', case['base_scenario_id'])))


def inventory_digest(folder):
    if not folder.is_dir():
        return {'status': 'MISSING', 'file_count': 0, 'digest': None}
    files = sorted(p for p in folder.rglob('*') if p.is_file())
    h = hashlib.sha256()
    for p in files:
        h.update(str(p.relative_to(folder)).encode()+b'\0'+sha(p).encode()+b'\n')
    return {'status': 'PRESENT', 'file_count': len(files), 'digest': h.hexdigest()}


def frozen_code_paths():
    root = WORKSPACE/'semantic_pallet_planner/src/semantic_pallet_planner'
    names = ['runners/protocol_o2a.py', 'runners/attribute_pilot_v2.py',
             'vlm/protocol_o2a.py', 'vlm/pilot_protocol_v2.py', 'vlm/deepseek_client.py',
             'evaluation/attribute_metrics_v2.py', 'evaluation/policy_v2.py',
             'selectors/instruction_parser_v2.py', 'selectors/policy_executor_v2.py']
    return [root/n for n in names]


def select_heldout_train_cases(repo, parent):
    consumed = {str(s['source_order_key']) for s in read_json(parent/'data/source_manifest.json')}
    tests = set()
    for split in ALL_SPLITS:
        if split.startswith('test'):
            for sid in repo.list_scenarios(split):
                a = read_json(repo.root/'annotations/ground_truth_rules'/f'{sid}.json')
                tests.add(str(a.get('source_order_key', a.get('source_order_id', sid))))
    groups = defaultdict(list)
    for cid in repo.list_cases('train'):
        case = repo.get_decision_case(cid)
        key = source_order(repo, case)
        if key not in consumed and key not in tests:
            groups[key].append(cid)
    selected = [(key, sorted(groups[key])[0]) for key in sorted(groups)[SOURCE_ORDER_OFFSET:SOURCE_ORDER_OFFSET+N_SOURCE_ORDERS]]
    if len(selected) != N_SOURCE_ORDERS:
        raise ValueError('Insufficient disjoint train-derived development source orders')
    return selected, {'source_split': 'train', 'o2a_role': 'heldout_development_validation',
                      'not_original_validation_or_unseen_test': True,
                      'v2_source_order_overlap': sorted({k for k,_ in selected}&consumed),
                      'test_source_order_overlap': sorted({k for k,_ in selected}&tests),
                      'selected_source_order_count': len(selected),
                      'source_order_offset': SOURCE_ORDER_OFFSET,
                      'selected_source_case_ids': [cid for _,cid in selected]}


def build_dataset(root, repo, cfg, parent):
    selected, split_audit = select_heldout_train_cases(repo, parent)
    gen = ExtremePointGenerator(cfg)
    dataset = []
    for group_i, (order, cid) in enumerate(selected, 1):
        case = repo.get_decision_case(cid)
        scenario = repo.get_scenario(case['base_scenario_id'])
        if scenario['buffer_size'] != 1:
            raise ValueError('buffer_size changed')
        state = {k: copy.deepcopy(case[k]) for k in ('placed_items', 'available_items')}
        state.update(container=scenario['container'], request_id=f'O2A_STATE_{group_i:03d}')
        state['placed_items'] = reconstruct(state['placed_items'])
        candidates = gen.generate(PalletState.from_dict(state)).candidate_set.data['candidates']
        random.Random(20261008+group_i).shuffle(candidates)
        true_ids = [c['candidate_id'] for c in candidates]
        visible = []
        for ci, c in enumerate(candidates):
            public = {k: copy.deepcopy(c[k]) for k in ('pick_item_id','pose','oriented_size_mm','support','load','resulting_geometry','geometry_score_components')}
            public.update(display_label=f'C{ci+1:02d}', geometry_score=geometry_score(c),
                          public_relations=public_relations(state,c))
            visible.append(public)
        for variant in (0,1):
            policy = policy_for(group_i-1,variant)
            instruction = instruction_from_policy(policy)
            if parse_instruction(instruction)!=policy:
                raise ValueError('policy grammar mismatch')
            request = {'schema_version':'pallet_request_v2_pilot',
                       'request_id':f'V2_PILOT_{100+SOURCE_ORDER_OFFSET+group_i:03d}_{variant}',
                       'state_hash':state_hash(scenario['container'],state),
                       'policy_digest':digest({'grammar':'attribute_v2_pilot_1','instruction_text':instruction}),
                       'instruction_text':instruction,'container':scenario['container'],
                       'placed_items':state['placed_items'],'available_items':state['available_items'],
                       'candidates':visible,'buffer_size':1}
            scan = scan_public(request,true_ids)
            if scan['status']!='PASS': raise ValueError('public request leakage')
            evaluations = [evaluate(state,c,policy,scenario['container']) for c in candidates]
            optimum = optimal_set(evaluations)
            item = {'public_request':request,
                    'source':{'source_order_key':order,'source_case_id':cid,'source_split':'train',
                              'pilot_role':'heldout_development_validation','physical_group_id':state['request_id'],
                              'source_case_sha256':sha(repo.root/'tasks/decision_cases'/f'{cid}.json')},
                    'hidden_policy':policy,'mapping':dict(zip([c['display_label'] for c in visible],true_ids)),
                    'physical_candidates':candidates,'evaluations':evaluations,'optimum':optimum,
                    'coverage':{'hard_applicable':any(e['business_hard_applicable'] for e in evaluations),
                                'topk_feasible_count':len(optimum['feasible_indices']),
                                'equivalent_labels':[visible[i]['display_label'] for i in optimum['equivalent_indices']]}}
            dataset.append(item)
            write_json(root/'data/public_requests'/f"{request['request_id']}.json",request)
    split_audit.update(paired_case_count=len(dataset), physical_state_count=len(selected),
                       no_test_used_for_tuning=True, all_cases_selected_before_model_calls=True)
    write_json(root/'data/split_audit.json',split_audit)
    write_json(root/'data/pilot_dataset.private.json',dataset)
    write_json(root/'data/source_manifest.json',[d['source'] for d in dataset if d['public_request']['request_id'].endswith('_0')])
    return dataset


def classify_old_case(item,row,folder):
    req=item['public_request']; cov=item['coverage']; tags=[]
    if cov['topk_feasible_count']==0: tags.append('candidate_no_feasible')
    if not cov.get('semantic_opportunity',False): tags.append('no_semantic_opportunity')
    rawfile=folder/'response.raw.json'
    raw=read_json(rawfile) if rawfile.exists() else None
    protocol_error=None; response_keys=None
    if raw:
        try:
            parsed=parse_old(raw['raw_text'],req)
            response_keys=sorted(parsed)
        except Exception as exc:
            protocol_error='malformed_json' if isinstance(exc,json.JSONDecodeError) else str(exc)
            try: response_keys=sorted(json.loads(raw['raw_text']))
            except (ValueError,TypeError): pass
            tags.append('protocol_error')
    if row['status']=='select' and cov['topk_feasible_count'] and row['hard_applicable'] and row['business_hard_satisfied'] is False:
        tags.append('avoidable_hard_wrong_selection')
    if row['status']=='select' and row['oracle_equivalent_hit'] is False and cov['topk_feasible_count']:
        tags.append('soft_priority_nonoptimal' if row['business_hard_satisfied'] is not False else 'hard_failure_precedes_soft')
    if not tags: tags.append('correct_or_not_applicable')
    selected=next((c for c in req['candidates'] if c['display_label']==row['display_label']),None)
    first_feasible=(req['candidates'][item['optimum']['feasible_indices'][0]] if item['optimum']['feasible_indices'] else None)
    return {'request_id':req['request_id'],'source_order_key':item['source']['source_order_key'],
            'instruction_text':req['instruction_text'],'status':row['status'],'selected_label':row['display_label'],
            'tags':tags,'protocol_error':protocol_error,'response_keys':response_keys,
            'raw_response_sha256':sha(rawfile) if raw else None,
            'finish_reason':raw.get('finish_reason') if raw else None,
            'hard_applicable':row['hard_applicable'],'topk_feasible_count':cov['topk_feasible_count'],
            'oracle_equivalent_labels':cov['equivalent_labels'],
            'new_business_violation_count':row['new_business_violation_count'],
            'after_violation_instances':row.get('after_violation_instances'),
            'priority_regret':row['priority_regret'],
            'selected_public_relations':selected['public_relations'] if selected else None,
            'feasible_witness_label':first_feasible['display_label'] if first_feasible else None,
            'feasible_witness_public_relations':first_feasible['public_relations'] if first_feasible else None,
            'reviewer_1':'','reviewer_2':'','review_status':'PENDING_TWO_HUMAN_REVIEWERS'}


def audit_old(root,parent):
    dataset=read_json(parent/'data/pilot_dataset.private.json')
    rows=read_json(parent/'metrics/per_decision.json')
    flash={r['request_id']:r for r in rows if r['method']=='flash_direct_text'}
    if len(dataset)!=60 or len(flash)!=60:
        raise ValueError('Expected complete old pilot evidence')
    records=[classify_old_case(d,flash[d['public_request']['request_id']],
              parent/'selector_inputs/flash_direct_text'/d['public_request']['request_id']) for d in dataset]
    critical=[x for x in records if 'protocol_error' in x['tags'] or 'avoidable_hard_wrong_selection' in x['tags']]
    tag_counts=Counter(t for x in records for t in x['tags'])
    write_json(root/'audit/old_60_classification.json',records)
    write_csv(root/'audit/old_60_classification.csv',records)
    write_csv(root/'audit/human_review_queue.csv',critical)
    report={'source_directory':str(parent),'cases':len(records),'critical_review_rows':len(critical),
            'tag_counts':dict(tag_counts),'protocol_error_count':tag_counts['protocol_error'],
            'avoidable_hard_wrong_selection_count':tag_counts['avoidable_hard_wrong_selection'],
            'human_double_review_status':'PENDING','model_reason_is_not_ground_truth':True}
    write_json(root/'audit/summary.json',report)
    return report


def invoke_one(client, model_request, request, parser, folder, name):
    """Return parsed choice and a non-sensitive attempt record; raw text stays in its own file."""
    attempt={'name':name,'attempted':True,'api_valid':False,'error_category':None,
             'error_code':None,'input_tokens':None,'output_tokens':None,
             'latency_s':None,'estimated_cost':None}
    try:
        result=client.complete(model_request)
        write_json(folder/f'{name}.raw.json',result.as_dict())
        attempt.update(input_tokens=result.input_tokens,output_tokens=result.output_tokens,
                       latency_s=result.latency_s,estimated_cost=result.estimated_cost,
                       finish_reason=result.finish_reason)
        parsed=parser(result.raw_text,request)
        write_json(folder/f'{name}.parsed.json',parsed)
        attempt['api_valid']=True
        return parsed,attempt
    except Exception as exc:
        attempt['error_category']=getattr(exc,'category','invalid_response')
        attempt['error_code']=getattr(exc,'code',type(exc).__name__)
        # Never serialize provider exception strings; they can contain sensitive response data.
        write_json(folder/f'{name}.error.json',{'category':attempt['error_category'],
                                                'code':attempt['error_code'],
                                                'exception_type':type(exc).__name__})
        return None,attempt


def run_one_arm(root,item,arm,client):
    req=item['public_request']
    folder=root/'selector_inputs'/arm/req['request_id']
    folder.mkdir(parents=True,exist_ok=True)
    hidden_ids=item['mapping'].values()
    scan=scan_public(req,hidden_ids)
    write_json(folder/'leakage_report.json',scan)
    if scan['status']!='PASS':
        raise ValueError('public request leakage')
    write_json(folder/'public_request.json',req)
    if arm=='old_prompt':
        from ..protocol import canonical_json
        model_req=ModelRequest(model='deepseek-flash',system_prompt=OLD_PROMPT,
                               user_text=canonical_json(req),max_output_tokens=512,timeout_s=60.)
        parser=parse_old; version='attribute_v2_pilot_1'
    elif arm=='new_prompt':
        model_req=new_model_request(req,private_strings=hidden_ids)
        parser=parse_new; version=PROMPT_VERSION
    else:
        raise ValueError('unknown arm')
    write_json(folder/'prompt.json',{'version':version,'system_prompt':model_req.system_prompt,
                                     'user_text':model_req.user_text,'request_sha256':digest(req)})
    first,first_attempt=invoke_one(client,model_req,req,parser,folder,'initial_response')
    attempts=[first_attempt]; final=first
    if arm=='new_prompt' and first is None and first_attempt['error_category']=='invalid_response':
        code=first_attempt['error_code']
        if code in {'malformed_json','not_object','unexpected_fields','schema_version','binding_request_id',
                    'binding_state_hash','binding_policy_digest','reason','action_or_label'}:
            repair_req=new_model_request(req,repair_error=code,private_strings=hidden_ids)
            # Repair contains only public facts and a fixed error code; it never echoes raw model text.
            write_json(folder/'repair_prompt.json',{'version':PROMPT_VERSION,'system_prompt':SYSTEM_PROMPT,
                                                   'user_text':repair_req.user_text,'error_code':code})
            final,repair_attempt=invoke_one(client,repair_req,req,parse_new,folder,'repair_response')
            attempts.append(repair_attempt)
    if final:
        label=final['display_label'];status=final['action']
    else:
        label=None
        status='invalid_response' if attempts[-1]['error_category']=='invalid_response' else (attempts[-1]['error_category'] or 'provider_error')
    write_json(folder/'attempts.json',{'arm':arm,'initial_valid':first is not None,'final_valid':final is not None,
                                       'attempts':attempts,'status':status})
    trace={'api_valid':final is not None,'attempt_count':len(attempts),
           'input_tokens':sum(a['input_tokens'] or 0 for a in attempts) if any(a['input_tokens'] is not None for a in attempts) else None,
           'output_tokens':sum(a['output_tokens'] or 0 for a in attempts) if any(a['output_tokens'] is not None for a in attempts) else None,
           'latency_s':sum(a['latency_s'] or 0 for a in attempts) if any(a['latency_s'] is not None for a in attempts) else None,
           'estimated_cost':sum(a['estimated_cost'] or 0 for a in attempts) if all(a['estimated_cost'] is not None for a in attempts) else None,
           'error_category':None if final else attempts[-1]['error_category'],
           'reason':final['reason'] if final else None}
    row=response_row(item,arm,label,status,trace)
    row.update(schema_version=VERSION,initial_api_valid=first is not None,
               final_api_valid=final is not None,repair_count=len(attempts)-1,
               actual_cost=None,price_unknown=True)
    return row


def baseline_row(item):
    try:
        label=public_parser(item['public_request'])
        status='select' if label else 'abstain'
    except ValueError:
        label=None;status='parser_error'
    row=response_row(item,'public_parser',label,status)
    row['schema_version']=VERSION
    return row


def run_methods(root,dataset,client=None):
    file=root/'metrics/per_decision.json'
    old=read_json(file) if file.exists() else []
    by={(r['request_id'],r['method']):r for r in old}
    for item in dataset:
        req=item['public_request']
        key=(req['request_id'],'public_parser')
        if key not in by: by[key]=baseline_row(item)
        for arm in ('old_prompt','new_prompt'):
            key=(req['request_id'],arm)
            if key in by and not by[key]['status'].startswith('blocked_'):
                continue
            if client is None:
                row=response_row(item,arm,None,'blocked_missing_api_key')
                row.update(schema_version=VERSION,initial_api_valid=None,final_api_valid=None,price_unknown=True)
            else:
                row=run_one_arm(root,item,arm,client)
                print(f"O2a {req['request_id']} {arm}: {row['status']}",flush=True)
            by[key]=row
            write_json(file,list(by.values()))
    rows=[by[k] for k in sorted(by)]
    write_json(file,rows)
    write_csv(root/'metrics/per_decision.csv',rows)
    return rows


def replay_rows(root,dataset,rows):
    from ..evaluation.replay_values_v2 import replay_values_equal
    expected={(d['public_request']['request_id'],m) for d in dataset for m in ('old_prompt','new_prompt','public_parser')}
    actual={(r['request_id'],r['method']) for r in rows}
    failures=[]
    if actual!=expected or len(rows)!=len(expected):
        failures.append('method_record_cardinality')
    by_item={d['public_request']['request_id']:d for d in dataset}
    for row in rows:
        item=by_item.get(row['request_id'])
        if item is None: failures.append('unknown_request');continue
        req=item['public_request']
        if row['state_hash']!=req['state_hash'] or row['policy_digest']!=req['policy_digest']:
            failures.append(row['request_id']+':binding')
        recomputed=response_row(item,row['method'],row['display_label'],row['status'])
        for key in ('physical_violations','business_hard_satisfied','comparison_success',
                    'post_business_violation_count','new_business_violation_count','priority_regret'):
            if not replay_values_equal(row.get(key),recomputed.get(key)):
                failures.append(row['request_id']+':'+row['method']+':'+key)
        if row['display_label'] is not None and (row['physical_violations'] or 0)!=0:
            failures.append(row['request_id']+':physical_violation')
        if row['method'] in ('old_prompt','new_prompt') and not row['status'].startswith('blocked_'):
            folder=root/'selector_inputs'/row['method']/row['request_id']
            if not (folder/'attempts.json').is_file():
                failures.append(row['request_id']+':missing_attempt_log')
            else:
                log=read_json(folder/'attempts.json')
                if log['status']!=row['status'] or len(log['attempts'])!=row['attempt_count']:
                    failures.append(row['request_id']+':attempt_log_mismatch')
    report={'status':'PASS' if not failures else 'FAIL','schema_cases':len(dataset),
            'rows_replayed':len(rows),'failures':failures,
            'submitted_physical_violations':sum(r['physical_violations'] or 0 for r in rows)}
    write_json(root/'replay_report.json',report)
    return report


def summarize(root,dataset,rows):
    out=[]
    for method in ('old_prompt','new_prompt','public_parser'):
        group=[r for r in rows if r['method']==method]
        ran=[r for r in group if not r['status'].startswith('blocked_')]
        first_valid=sum(r.get('initial_api_valid') is True for r in ran)
        final_valid=sum(r.get('final_api_valid') is True for r in ran)
        applicable=[r for r in ran if r['hard_applicable']]
        target=[r for r in ran if r['all_attempt_success'] is not None]
        entry={'method':method,'planned_tasks':len(group),'completed_tasks':len(ran),
               'status_counts':dict(Counter(r['status'] for r in group)),
               'first_response_valid_n':first_valid if method!='public_parser' else None,
               'final_response_valid_n':final_valid if method!='public_parser' else None,
               'first_response_valid_rate':first_valid/len(ran) if ran and method!='public_parser' else None,
               'final_response_valid_rate':final_valid/len(ran) if ran and method!='public_parser' else None,
               'business_hard_satisfied_n':sum(r['business_hard_satisfied'] is True for r in applicable),
               'business_hard_applicable_n':len(applicable),
               'all_attempt_success_n':sum(r['all_attempt_success'] is True for r in target),
               'all_attempt_applicable_n':len(target),
               'physical_violations':sum(r['physical_violations'] or 0 for r in ran),
               'total_api_attempts':sum(r['attempt_count'] for r in ran),
               'repair_calls':sum(r['repair_count'] for r in ran),
               'input_tokens':sum(r['input_tokens'] or 0 for r in ran) if any(r['input_tokens'] is not None for r in ran) else None,
               'output_tokens':sum(r['output_tokens'] or 0 for r in ran) if any(r['output_tokens'] is not None for r in ran) else None,
               'actual_cost':None,'estimated_cost':None}
        latency=[r['latency_s'] for r in ran if r['latency_s'] is not None]
        entry['latency_p50_s']=statistics.median(latency) if latency else None
        entry['latency_p95_s']=sorted(latency)[min(len(latency)-1,int(.95*len(latency)))] if latency else None
        out.append(entry)
    write_json(root/'metrics/summary.json',out)
    return out


def prepare(root,parent):
    if root.exists(): raise ValueError('Output directory exists; use --resume')
    if not parent.is_dir(): raise ValueError('V2 parent pilot missing')
    root.mkdir(parents=True)
    repo=DatasetRepository(WORKSPACE/'semantic_pallet_dataset_v1')
    cfg=generator_config(load_config(top_k=16,topk_mode='diverse_v1'))
    parent_before=inventory_digest(parent)
    v1_before=inventory_digest(DEFAULT_V1)
    paths=frozen_code_paths()
    source_hashes={str(p.relative_to(WORKSPACE)):sha(p) for p in paths}
    commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=WORKSPACE,text=True).strip()
    write_json(root/'manifest.json',{'schema_version':VERSION,'prompt_version':PROMPT_VERSION,
               'choice_schema_version':CHOICE_VERSION,'git_parent_commit':commit,
               'dirty_source_sha256_is_authoritative':True,'source_sha256':source_hashes,
               'generator_config_sha256':digest(cfg),'generator_config':cfg,
               'parent_v2_directory':str(parent),'parent_v2_before':parent_before,
               'v1_directory':str(DEFAULT_V1),'v1_before':v1_before,
               'data_role':'train-derived held-out development validation, not original validation/test',
               'remote_model':'deepseek-flash','source_order_offset':SOURCE_ORDER_OFFSET,
               'planned_remote_arms':['old_prompt','new_prompt'],
               'created_time_utc':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime())})
    for p in paths:
        q=root/'code_snapshot'/p.relative_to(WORKSPACE)
        q.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(p,q)
    dataset=build_dataset(root,repo,cfg,parent)
    oldaudit=audit_old(root,parent)
    manifest=read_json(root/'manifest.json')
    manifest['data_sha256']={str(p.relative_to(root)):sha(p) for p in sorted((root/'data').rglob('*.json'))}
    manifest['old_audit_sha256']=sha(root/'audit/old_60_classification.json')
    write_json(root/'manifest.json',manifest)
    return dataset,oldaudit


def resume(root,parent):
    m=read_json(root/'manifest.json')
    if Path(m['parent_v2_directory']).resolve()!=parent.resolve():
        raise ValueError('Parent V2 directory differs')
    drift=[p for p,h in m['source_sha256'].items() if sha(WORKSPACE/p)!=h]
    data_drift=[p for p,h in m['data_sha256'].items() if sha(root/p)!=h]
    if drift or data_drift or sha(root/'audit/old_60_classification.json')!=m['old_audit_sha256']:
        raise ValueError('Frozen O2a source/data/audit changed')
    if digest(generator_config(load_config(top_k=16,topk_mode='diverse_v1')))!=m['generator_config_sha256']:
        raise ValueError('Frozen candidate generator changed')
    for folder,before in ((parent,m['parent_v2_before']),(DEFAULT_V1,m['v1_before'])):
        if inventory_digest(folder)!=before:
            raise ValueError('Historical experiment changed')
    return read_json(root/'data/pilot_dataset.private.json'),read_json(root/'audit/summary.json')


def finish(root,parent,dataset,oldaudit,rows):
    replay=replay_rows(root,dataset,rows)
    summary=summarize(root,dataset,rows)
    m=read_json(root/'manifest.json')
    v1_after=inventory_digest(DEFAULT_V1);v2_after=inventory_digest(parent)
    preserved=v1_after==m['v1_before'] and v2_after==m['parent_v2_before']
    write_json(root/'checks/historical_integrity.json',{'status':'PASS' if preserved else 'FAIL',
               'v1_before':m['v1_before'],'v1_after':v1_after,
               'v2_before':m['parent_v2_before'],'v2_after':v2_after})
    remote_complete=all(x['completed_tasks']==len(dataset) for x in summary if x['method']!='public_parser')
    data_audit=read_json(root/'data/split_audit.json')
    status='PASS' if preserved and replay['status']=='PASS' and not data_audit['v2_source_order_overlap'] and not data_audit['test_source_order_overlap'] else 'FAIL'
    acceptance={'offline_engineering_status':status,
                'remote_comparison_status':'COMPLETE' if remote_complete else 'BLOCKED_MISSING_API_KEY',
                'old_60_automatic_classification':'PASS' if oldaudit['cases']==60 else 'FAIL',
                'old_critical_human_double_review':'PENDING',
                'first_response_98_percent_gate':{x['method']:(x['first_response_valid_rate']>=.98 if x['first_response_valid_rate'] is not None else None) for x in summary if x['method']!='public_parser'},
                'new_prompt_repaired_response_98_percent_gate':next((x['final_response_valid_rate']>=.98 if x['final_response_valid_rate'] is not None else None for x in summary if x['method']=='new_prompt'),None),
                'research_advantage_status':'NOT_ASSESSED' if not remote_complete else 'DEVELOPMENT_ONLY',
                'all_o2a_acceptance_complete':bool(remote_complete and oldaudit['human_double_review_status']=='PASS' and status=='PASS')}
    write_json(root/'acceptance_report.json',acceptance)
    report=f'''# O2a 协议 pilot 报告\n\n- 数据来源：原 train 中预留的 {data_audit['selected_source_order_count']} 个独立订单；{len(dataset)} 道双政策固定候选题。标记为 train-derived held-out development validation；不是原 validation 或新 test。\n- V2 `_04` 原始记录及 V1 全目录哈希保护：{'PASS' if preserved else 'FAIL'}。旧60题自动分类：{oldaudit['cases']}；关键错误人工双人签认：PENDING。\n- 严格协议：只接受7字段、绑定一致和给定展示编号；新方法最多一次修复，修复请求只含公开请求及错误代码，不回传模型原文。\n- 离线工程状态：{status}；回放：{replay['status']}；真实同题对照：{'COMPLETE' if remote_complete else 'BLOCKED_MISSING_API_KEY'}。\n- 首答与修复后合法率、全尝试业务成功、token和时延：见 `metrics/summary.json`。实际费用与估价均为null；没有已核实账单或价格，不能记为零。\n- 研究解释：本轮是开发期协议对照；即使新Prompt改善合法率，也不能据此宣称新test上的VLM业务优势。人工双人复核未签字前，O2a整体不算全部完成。\n'''
    (root/'o2a_report.md').write_text(report)
    return acceptance


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',required=True)
    parser.add_argument('--parent-v2',default=str(DEFAULT_PARENT))
    parser.add_argument('--resume',action='store_true')
    parser.add_argument('--remote',action='store_true')
    args=parser.parse_args(argv)
    root=Path(args.output).resolve();parent=Path(args.parent_v2).resolve()
    if any(x.startswith('EXP_1C_') for x in root.parts):
        raise ValueError('Never write V1 experiment directories')
    if args.resume:
        dataset,oldaudit=resume(root,parent)
        if (root/'metrics/per_decision.json').exists():
            prior=replay_rows(root,dataset,read_json(root/'metrics/per_decision.json'))
            if prior['status']!='PASS':
                raise ValueError('Existing records fail replay; refusing paid continuation')
    else:
        dataset,oldaudit=prepare(root,parent)
    client=DeepSeekClient() if args.remote and os.environ.get('DEEPSEEK_API_KEY') else None
    rows=run_methods(root,dataset,client)
    result=finish(root,parent,dataset,oldaudit,rows)
    print(json.dumps({'output':str(root),'offline':result['offline_engineering_status'],
                      'remote':result['remote_comparison_status'],
                      'all_o2a_acceptance_complete':result['all_o2a_acceptance_complete']},ensure_ascii=False))


if __name__=='__main__':
    main()
