"""O2b offline baselines and resumable DeepSeek text comparison on O1b tasks."""
from __future__ import annotations

import argparse
import os
import random
import shutil
import statistics
import subprocess
from collections import Counter, defaultdict
from pathlib import Path

from jsonschema import Draft202012Validator

from ..config import WORKSPACE
from ..evaluation.geometry_oracle import check_candidate
from ..evaluation.policy_o1b import resolve
from ..evaluation.policy_v2 import evaluate, optimal_set, priority_regret
from ..evaluation.replay_values_v2 import replay_values_equal
from ..selectors.instruction_parser_o1b import parse_o1b_instruction, resolved_public_policy
from ..selectors.policy_executor_v2 import execute_policy, fixed_attribute, geometry
from ..vlm.deepseek_client import DeepSeekClient
from ..vlm.pilot_protocol_v2 import digest, scan_public
from ..vlm.policy_protocol_o2b import PROMPT_VERSION, model_request as ast_request, parse_policy_response
from ..vlm.protocol_o2a import model_request as direct_request, parse_choice
from .attribute_pilot_v2 import read_json, sha, write_csv, write_json

VERSION = 'attribute_o2b_development_1'
METHODS = ('geometry_greedy', 'fixed_attribute', 'public_parser', 'flash_direct_text',
           'flash_policy_parser', 'truth_ast_executor')
REMOTE = ('flash_direct_text', 'flash_policy_parser')
PARENT = WORKSPACE/'semantic_pallet_planner/outputs/EXP_OPT_O1B_LANGUAGE_PILOT_20261009_03'
OUTPUT = WORKSPACE/'semantic_pallet_planner/outputs/EXP_OPT_O2B_AST_PILOT_20261009_05'
SOURCE = WORKSPACE/'semantic_pallet_planner/src/semantic_pallet_planner'
FROZEN = ('runners/attribute_o2b.py','runners/attribute_pilot_v2.py',
          'vlm/policy_protocol_o2b.py','vlm/protocol_o2a.py','vlm/pilot_protocol_v2.py',
          'vlm/deepseek_client.py','vlm/client.py',
          'evaluation/policy_v2.py','evaluation/policy_o1b.py',
          'evaluation/attribute_metrics_v2.py','evaluation/geometry_oracle.py',
          'selectors/instruction_parser_o1b.py','selectors/policy_executor_v2.py',
          'schemas/policy_v2.schema.json','schemas/policy_o1b.schema.json',
          'schemas/o1b_request.schema.json')


def dataset(parent):
    tasks = read_json(parent/'data/tasks.private.json')
    if len(tasks) != 180 or len({t['source_order_key'] for t in tasks}) != 30:
        raise ValueError('O1b scale/source mismatch')
    validator = Draft202012Validator(read_json(SOURCE/'schemas/o1b_request.schema.json'))
    groups, result = {}, []
    for task in tasks:
        gid = task['physical_group_id']
        if gid not in groups:
            groups[gid] = read_json(parent/'data/physical_groups'/f'{gid}.private.json')
        req = read_json(parent/task['public_request_path'])
        validator.validate(req)
        if req['request_id'] != task['request_id'] or scan_public(req,groups[gid]['mapping'].values())['status'] != 'PASS':
            raise ValueError('O1b request binding/leakage')
        if req['policy_digest'] != digest({'grammar':'o1b_instruction_1','instruction_text':req['instruction_text']}):
            raise ValueError('O1b policy digest drift')
        if len(req['candidates']) != len(groups[gid]['physical_candidates']):
            raise ValueError('O1b candidates drift')
        result.append((task,req,groups[gid]))
    for gid in groups:
        local = [r for t,r,g in result if g['group_id']==gid]
        if len(local)!=6 or len({r['state_hash'] for r in local})!=1 or len({digest(r['candidates']) for r in local})!=1:
            raise ValueError('O1b paired state/candidates drift')
    return result


def frozen_data(parent, items):
    names = {'manifest.json','data/tasks.private.json','data/source_manifest.json','data/split_audit.json',
             *(t['public_request_path'] for t,_,_ in items),
             *(f"data/physical_groups/{t['physical_group_id']}.private.json" for t,_,_ in items)}
    return {n:sha(parent/n) for n in sorted(names)}


def prepare(root,parent):
    if root.exists(): raise FileExistsError('New O2b directory required; use --resume')
    items=dataset(parent)
    root.mkdir(parents=True)
    sources={n:sha(SOURCE/n) for n in FROZEN}
    for n in FROZEN:
        target=root/'code_snapshot'/n
        target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(SOURCE/n,target)
    write_json(root/'manifest.json',{'version':VERSION,
        'git_parent_commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=WORKSPACE,text=True).strip(),
        'dirty_source_sha256_is_authoritative':True,'source_sha256':sources,
        'o1b_parent':str(parent),'o1b_data_sha256':frozen_data(parent,items),
        'data_role':'train-derived development validation; not unseen test',
        'planned_tasks':180,'independent_source_orders':30,'methods':METHODS,
        'remote_methods':REMOTE,'model':'deepseek-flash','prompt_version':PROMPT_VERSION,
        'top_k':16,'buffer_size':1,'max_repair_calls':1,
        'cache_policy':'completed requests only; no cross-policy response reuse'})
    return items


def resume(root,parent):
    manifest=read_json(root/'manifest.json')
    if manifest['version']!=VERSION or Path(manifest['o1b_parent']).resolve()!=parent:
        raise ValueError('O2b manifest mismatch')
    for n,h in manifest['source_sha256'].items():
        if sha(SOURCE/n)!=h or sha(root/'code_snapshot'/n)!=h:
            raise ValueError('O2b source drift: '+n)
    for n,h in manifest['o1b_data_sha256'].items():
        if sha(parent/n)!=h: raise ValueError('O1b data drift: '+n)
    items=dataset(parent)
    records=read_json(root/'metrics/per_decision.json') if (root/'metrics/per_decision.json').exists() else []
    if records and replay(root,items,records,complete=False)['status']!='PASS':
        raise ValueError('Existing O2b records fail replay; refusing paid continuation')
    return items


def fields(ast):
    if ast['schema_version']=='pallet_policy_o1b_conditional_1':
        return {'condition':ast['condition'],'then':fields(ast['then_policy']),'else':fields(ast['else_policy'])}
    load=next(r for r in ast['hard_constraints'] if r['type']=='fragile_load_limit')
    return {'object':load['selector'],'threshold':load['threshold_kg'],
            'hard':ast['hard_constraints'],'priority':[r['metric'] for r in ast['soft_priorities']]}


def ast_accuracy(ast,truth):
    if ast is None: return None
    a,b=fields(ast),fields(truth)
    if 'condition' in b:
        keys=('then','else')
        result={'condition':a.get('condition')==b['condition']}
        for out,key in (('object','object'),('threshold','threshold'),('hard_soft','hard'),('priority','priority')):
            result[out]=all(a.get(k,{}).get(key)==b[k][key] for k in keys)
    else:
        result={'condition':'condition' not in a,'object':a.get('object')==b['object'],
                'threshold':a.get('threshold')==b['threshold'],
                'hard_soft':a.get('hard')==b['hard'],'priority':a.get('priority')==b['priority']}
    result['whole_policy']=ast==truth
    return result


def score(task,req,method,proposal,outcome,ast=None,trace=None):
    trace=trace or {}
    labels={c['display_label']:i for i,c in enumerate(req['candidates'])}
    if proposal is not None and proposal not in labels: raise ValueError('unknown label')
    # The shared public parser is the submit-time business barrier for every
    # nonprivileged method. It can only abstain, never replace the model choice.
    public=resolved_public_policy(req['instruction_text'],req)
    public_evals=[evaluate(req,c,public,req['container']) for c in req['candidates']]
    truth_evals=[evaluate(req,c,task['resolved_policy'],req['container']) for c in req['candidates']]
    optimum=optimal_set(truth_evals)
    if optimum!=task['optimum']: raise ValueError('O1b optimum replay mismatch')
    i=labels.get(proposal)
    blocked=i is not None and public_evals[i]['after_violation_instances'] and method!='truth_ast_executor'
    committed=proposal if i is not None and not blocked and outcome=='select' else None
    j=labels.get(committed)
    physical=check_candidate(req,{'container':req['container']},req['candidates'][j]) if j is not None else []
    if physical: raise ValueError('physical violation: '+str(physical))
    raw=truth_evals[i] if i is not None else None
    final=truth_evals[j] if j is not None else None
    covered=bool(optimum['feasible_indices'])
    applicable=task['coverage']['hard_applicable']
    avoidable=bool(applicable and covered)
    raw_wrong=bool(raw['after_violation_instances']) if raw else None
    status='screen_abstain' if blocked else ('select' if committed else outcome)
    accuracy=(ast_accuracy(ast,task['hidden_policy_ast']) if ast is not None else
              {k:False for k in ('condition','object','threshold','hard_soft','priority','whole_policy')}
              if method=='flash_policy_parser' and outcome!='blocked_no_api_key' else None)
    return {'version':VERSION,'request_id':req['request_id'],'state_hash':req['state_hash'],
      'policy_digest':req['policy_digest'],'source_order_key':task['source_order_key'],
      'physical_group_id':task['physical_group_id'],'track':task['track'],'variant':task['variant'],
      'method':method,'status':status,'raw_outcome':outcome,'proposed_label':proposal,
      'committed_label':committed,'screen_intervened':bool(blocked),'screen_source':'shared_public_parser',
      'topk_feasible_count':len(optimum['feasible_indices']),
      'coverage_category':task['coverage']['coverage_category'],
      'hard_applicable':applicable,'avoidable_hard_opportunity':avoidable,
      'raw_avoidable_hard_wrong':raw_wrong if avoidable else None,
      'raw_post_business_violations':raw['post_business_violation_count'] if raw else None,
      'raw_new_business_violations':raw['new_business_violation_count'] if raw else None,
      'committed_post_business_violations':final['post_business_violation_count'] if final else None,
      'committed_hard_satisfied':not final['after_violation_instances'] if final and applicable else None,
      'raw_soft_quality':raw['soft_quality'] if raw else None,
      'raw_priority_regret':priority_regret(raw,optimum) if raw and covered else None,
      'raw_optimal_hit':i in optimum['equivalent_indices'] if i is not None and covered else None,
      'all_attempt_success':bool(final and not final['after_violation_instances']) if applicable else None,
      'geometry_score':req['candidates'][j]['geometry_score'] if j is not None else None,
      'physical_violations':len(physical),
      'ast_accuracy':accuracy,
      'initial_api_valid':trace.get('initial_api_valid'),'final_api_valid':trace.get('final_api_valid'),
      'attempt_count':trace.get('attempt_count',0),'repair_count':trace.get('repair_count',0),
      'input_tokens':trace.get('input_tokens'),'output_tokens':trace.get('output_tokens'),
      'latency_s':trace.get('latency_s'),'estimated_cost':trace.get('estimated_cost'),
      'actual_cost':None,'error_category':trace.get('error_category'),
      'direct_error_diagnostic':('hard_relation_or_policy_mismatch' if avoidable and raw_wrong else
          'soft_rank_gap' if raw and covered and i not in optimum['equivalent_indices'] else None)}


def offline(task,req,method):
    if method=='geometry_greedy': label=geometry(req);ast=None
    elif method=='fixed_attribute': label=fixed_attribute(req);ast=None
    elif method=='public_parser':
        ast=parse_o1b_instruction(req['instruction_text'])
        label=execute_policy(req,resolved_public_policy(req['instruction_text'],req))
    elif method=='truth_ast_executor':
        ast=task['hidden_policy_ast'];label=execute_policy(req,task['resolved_policy'])
    else:
        return score(task,req,method,None,'blocked_no_api_key')
    return score(task,req,method,label,'select' if label else 'abstain',ast)


def invoke(client,model_req,parser,req,folder,name):
    info={'name':name,'api_valid':False,'error_category':None,'error_code':None,
          'input_tokens':None,'output_tokens':None,'latency_s':None,'estimated_cost':None}
    try:
        response=client.complete(model_req)
        write_json(folder/(name+'.raw.json'),response.as_dict())
        info.update(input_tokens=response.input_tokens,output_tokens=response.output_tokens,
                    latency_s=response.latency_s,estimated_cost=response.estimated_cost,
                    finish_reason=response.finish_reason)
        parsed=parser(response.raw_text,req)
        write_json(folder/(name+'.parsed.json'),parsed)
        info['api_valid']=True
        return parsed,info
    except Exception as exc:
        info['error_category']=getattr(exc,'category','invalid_response')
        info['error_code']=getattr(exc,'code',type(exc).__name__)
        # Provider exception strings may contain secrets or raw payloads.
        write_json(folder/(name+'.error.json'),{'category':info['error_category'],
          'code':info['error_code'],'exception_type':type(exc).__name__})
        return None,info


def remote(root,task,req,group,method,client):
    folder=root/'selector_inputs'/method/req['request_id']
    folder.mkdir(parents=True,exist_ok=True)
    ids=group['mapping'].values()
    scan=scan_public(req,ids)
    if scan['status']!='PASS':raise ValueError('public request leakage')
    write_json(folder/'public_request.json',req)
    write_json(folder/'leakage_report.json',scan)
    make,parser=(direct_request,parse_choice) if method=='flash_direct_text' else (ast_request,parse_policy_response)
    first_request=make(req,private_strings=ids)
    write_json(folder/'prompt.json',{'system_prompt':first_request.system_prompt,
        'user_text':first_request.user_text,'request_sha256':digest(req)})
    first,a=invoke(client,first_request,parser,req,folder,'initial_response')
    attempts=[a];final=first
    if first is None and a['error_category']=='invalid_response':
        try: repair=make(req,repair_error=a['error_code'],private_strings=ids)
        except ValueError: repair=None
        if repair is not None:
            write_json(folder/'repair_prompt.json',{'system_prompt':repair.system_prompt,
                'user_text':repair.user_text,'error_code':a['error_code'],
                'request_sha256':digest(req)})
            final,b=invoke(client,repair,parser,req,folder,'repair_response')
            attempts.append(b)
    ast=final['policy_ast'] if final and method=='flash_policy_parser' else None
    if final is None:
        label=None;outcome='invalid_response' if attempts[-1]['error_category']=='invalid_response' else attempts[-1]['error_category'] or 'provider_error'
    elif method=='flash_direct_text':
        label=final['display_label'];outcome=final['action']
    else:
        resolved=resolve(ast,req) if ast['schema_version']=='pallet_policy_o1b_conditional_1' else ast
        label=execute_policy(req,resolved);outcome='select' if label else 'abstain'
    trace={'initial_api_valid':first is not None,'final_api_valid':final is not None,
      'attempt_count':len(attempts),'repair_count':len(attempts)-1,
      'input_tokens':sum(x['input_tokens'] or 0 for x in attempts) if any(x['input_tokens'] is not None for x in attempts) else None,
      'output_tokens':sum(x['output_tokens'] or 0 for x in attempts) if any(x['output_tokens'] is not None for x in attempts) else None,
      'latency_s':sum(x['latency_s'] or 0 for x in attempts) if any(x['latency_s'] is not None for x in attempts) else None,
      'estimated_cost':sum(x['estimated_cost'] for x in attempts) if all(x['estimated_cost'] is not None for x in attempts) else None,
      'error_category':None if final else attempts[-1]['error_category']}
    write_json(folder/'attempts.json',{'attempts':attempts,'parsed_ast':ast,
      'proposed_label':label,'outcome':outcome,'trace':trace})
    return score(task,req,method,label,outcome,ast,trace)


def replay(root,items,rows,complete=True):
    expected={(t['request_id'],m):(t,r,g) for t,r,g in items for m in METHODS}
    failures=[];seen=set()
    for row in rows:
        key=(row.get('request_id'),row.get('method'))
        if key in seen or key not in expected:
            failures.append(str(key)+':duplicate_or_unknown');continue
        seen.add(key)
        task,req,_=expected[key]
        if row['state_hash']!=req['state_hash'] or row['policy_digest']!=req['policy_digest']:
            failures.append(str(key)+':binding')
        folder=root/'selector_inputs'/row['method']/row['request_id']
        if row['method'] in REMOTE and row['status']!='blocked_no_api_key':
            if not (folder/'attempts.json').is_file():
                failures.append(str(key)+':missing_attempts');continue
            log=read_json(folder/'attempts.json')
            if len(log['attempts'])!=row['attempt_count'] or log['proposed_label']!=row['proposed_label']:
                failures.append(str(key)+':attempt_mismatch')
            ast=log['parsed_ast'];trace=log['trace']
            if trace['final_api_valid']:
                raw=read_json(folder/('repair_response.raw.json' if row['repair_count'] else 'initial_response.raw.json'))['raw_text']
                parser=parse_choice if row['method']=='flash_direct_text' else parse_policy_response
                try:
                    parsed=parser(raw,req)
                    if row['method']=='flash_direct_text':
                        if parsed['display_label']!=row['proposed_label'] or parsed['action']!=row['raw_outcome']:
                            failures.append(str(key)+':raw_choice_mismatch')
                    elif parsed['policy_ast']!=ast:
                        failures.append(str(key)+':raw_ast_mismatch')
                except Exception: failures.append(str(key)+':raw_parse')
        else:
            ast=parse_o1b_instruction(req['instruction_text']) if row['method']=='public_parser' else task['hidden_policy_ast'] if row['method']=='truth_ast_executor' else None
            trace=None
        recomputed=score(task,req,row['method'],row['proposed_label'],row['raw_outcome'],ast,trace)
        for field in ('status','committed_label','screen_intervened','raw_avoidable_hard_wrong',
                      'raw_post_business_violations','raw_new_business_violations',
                      'committed_post_business_violations','committed_hard_satisfied',
                      'raw_priority_regret','raw_optimal_hit','all_attempt_success',
                      'geometry_score','ast_accuracy','physical_violations'):
            if not replay_values_equal(row.get(field),recomputed.get(field)):
                failures.append(str(key)+':'+field)
    if complete and seen!=set(expected): failures.append('method_record_cardinality')
    result={'status':'PASS' if not failures else 'FAIL','rows':len(rows),'expected_rows':len(expected),
            'committed_physical_violations':sum(r['physical_violations'] for r in rows),
            'failures':failures}
    if complete:write_json(root/'replay_report.json',result)
    return result


def cluster_comparison(items, rows, pairs, draws=2000):
    """Paired source-order bootstrap; repeated views never count as independent orders."""
    by={(r['request_id'],r['method']):r for r in rows}
    outcome={}
    for method in METHODS:
        if method=='public_parser':continue
        for track in ('B','C'):
            for metric in ('raw_avoidable_hard_wrong','raw_optimal_hit'):
                grouped=defaultdict(list)
                for task,_,_ in items:
                    if task['track']!=track:continue
                    a=by[(task['request_id'],method)][metric]
                    b=by[(task['request_id'],'public_parser')][metric]
                    if a is not None and b is not None:
                        grouped[task['source_order_key']].append(float(a)-float(b))
                values=[statistics.mean(v) for v in grouped.values()]
                if values:
                    rng=random.Random(20261009)
                    boot=sorted(statistics.mean(rng.choice(values) for _ in values) for _ in range(draws))
                    ci=[boot[int(.025*draws)],boot[int(.975*draws)-1]]
                else:ci=None
                outcome[f'{method}:{track}:{metric}']={'source_orders':len(values),
                    'paired_task_count':sum(map(len,grouped.values())),
                    'mean_difference':statistics.mean(values) if values else None,
                    'cluster_bootstrap_ci95':ci,'bootstrap_draws':draws if values else 0}
            arm_pairs=[r for r in pairs if r['method']==method and r['track']==track and r['opportunity']]
            valid=[r for r in arm_pairs if r['available']]
            outcome[f'{method}:{track}:policy_pair']={'opportunity_source_orders':len(arm_pairs),
                'completed_source_orders':len(valid),
                'pair_success_rate':sum(r['pair_success'] for r in valid)/len(valid) if valid else None}
    return outcome


def summarize(root,items,rows):
    summary=[];by={(r['request_id'],r['method']):r for r in rows}
    for method in METHODS:
        part=[r for r in rows if r['method']==method]
        done=[r for r in part if r['status']!='blocked_no_api_key']
        avoid=[r for r in done if r['avoidable_hard_opportunity']]
        hard=[r for r in done if r['hard_applicable']]
        soft=[r['raw_priority_regret'][0] for r in done if r['raw_priority_regret'] and r['raw_priority_regret'][0] is not None]
        ast=[r['ast_accuracy'] for r in done if r['ast_accuracy']]
        lat=sorted(r['latency_s'] for r in done if r['latency_s'] is not None)
        summary.append({'method':method,'planned':len(part),'done':len(done),
          'status_counts':dict(Counter(r['status'] for r in part)),
          'initial_valid_rate':sum(r['initial_api_valid'] is True for r in done)/len(done) if method in REMOTE and done else None,
          'final_valid_rate':sum(r['final_api_valid'] is True for r in done)/len(done) if method in REMOTE and done else None,
          'avoidable_raw_hard_violation_rate':sum(r['raw_avoidable_hard_wrong'] is True for r in avoid)/len(avoid) if avoid else None,
          'avoidable_denominator':len(avoid),
          'all_attempt_success_rate':sum(r['all_attempt_success'] is True for r in hard)/len(hard) if hard else None,
          'all_attempt_success_denominator':len(hard),
          'raw_post_business_satisfaction_rate':sum(r['raw_post_business_violations']==0 for r in done if r['raw_post_business_violations'] is not None and r['hard_applicable'])/sum(r['raw_post_business_violations'] is not None and r['hard_applicable'] for r in done) if any(r['raw_post_business_violations'] is not None and r['hard_applicable'] for r in done) else None,
          'screen_interventions':sum(r['screen_intervened'] for r in done),
          'committed_hard_satisfaction_rate':sum(r['committed_hard_satisfied'] is True for r in hard)/len(hard) if hard else None,
          'geometry_score_mean':statistics.mean(r['geometry_score'] for r in done if r['geometry_score'] is not None) if any(r['geometry_score'] is not None for r in done) else None,
          'first_priority_regret_mean':statistics.mean(soft) if soft else None,
          'soft_denominator':len(soft),
          'raw_optimal_rate':sum(r['raw_optimal_hit'] is True for r in done if r['raw_optimal_hit'] is not None)/sum(r['raw_optimal_hit'] is not None for r in done) if any(r['raw_optimal_hit'] is not None for r in done) else None,
          'ast_accuracy':{k:sum(a[k] for a in ast)/len(ast) for k in ('condition','object','threshold','hard_soft','priority','whole_policy')} if ast else None,
          'ast_denominator':len(ast),'physical_violations':sum(r['physical_violations'] for r in done),
          'api_attempts':sum(r['attempt_count'] for r in done),'repairs':sum(r['repair_count'] for r in done),
          'input_tokens':sum(r['input_tokens'] or 0 for r in done) if any(r['input_tokens'] is not None for r in done) else None,
          'output_tokens':sum(r['output_tokens'] or 0 for r in done) if any(r['output_tokens'] is not None for r in done) else None,
          'latency_p50_s':statistics.median(lat) if lat else None,
          'latency_p95_s':lat[min(len(lat)-1,int(.95*len(lat)))] if lat else None,
          'estimated_cost':sum(r['estimated_cost'] for r in done) if done and all(r['estimated_cost'] is not None for r in done) else None,
          'actual_cost':None})
    pairs=[]
    for method in METHODS:
        for track in ('A','B','C'):
            for gid in sorted({t['physical_group_id'] for t,_,_ in items}):
                tasks=sorted((t for t,_,_ in items if t['physical_group_id']==gid and t['track']==track),key=lambda t:t['variant'])
                a,b=(by[(t['request_id'],method)] for t in tasks)
                opportunity=tasks[0]['coverage']['equivalent_labels']!=tasks[1]['coverage']['equivalent_labels']
                available=a['status']!='blocked_no_api_key' and b['status']!='blocked_no_api_key'
                pairs.append({'method':method,'track':track,'physical_group_id':gid,
                  'source_order_key':tasks[0]['source_order_key'],'opportunity':opportunity,
                  'available':available,'pair_success':bool(a['raw_optimal_hit'] and b['raw_optimal_hit']) if opportunity and available else None})
    per_track=[]
    for method in METHODS:
        for track in ('A','B','C'):
            part=[r for r in rows if r['method']==method and r['track']==track and r['status']!='blocked_no_api_key']
            avoid=[r for r in part if r['avoidable_hard_opportunity']]
            opt=[r for r in part if r['raw_optimal_hit'] is not None]
            regrets=[r['raw_priority_regret'][0] for r in part if r['raw_priority_regret'] and r['raw_priority_regret'][0] is not None]
            local_pairs=[p for p in pairs if p['method']==method and p['track']==track and p['opportunity'] and p['available']]
            per_track.append({'method':method,'track':track,'completed_tasks':len(part),'independent_source_orders':len({r['source_order_key'] for r in part}),
                'avoidable_raw_hard_violation_rate':sum(r['raw_avoidable_hard_wrong'] is True for r in avoid)/len(avoid) if avoid else None,
                'avoidable_denominator':len(avoid),'first_priority_regret_mean':statistics.mean(regrets) if regrets else None,
                'soft_denominator':len(regrets),'raw_optimal_rate':sum(r['raw_optimal_hit'] is True for r in opt)/len(opt) if opt else None,
                'optimal_denominator':len(opt),'opportunity_pair_success_rate':sum(p['pair_success'] for p in local_pairs)/len(local_pairs) if local_pairs else None,
                'opportunity_pair_denominator':len(local_pairs)})
    write_csv(root/'metrics/per_track.csv',per_track)
    write_json(root/'metrics/paired_cluster_ci.json',cluster_comparison(items,rows,pairs))
    write_json(root/'metrics/summary.json',summary)
    write_csv(root/'metrics/policy_pairs.csv',pairs)
    write_json(root/'metrics/coverage_report.json',{'coverage_categories':dict(Counter(t['coverage']['coverage_category'] for t,_,_ in items)),
      'independent_source_orders':30,'tasks':len(items)})
    write_json(root/'metrics/cost_summary.json',{'methods':[{k:s[k] for k in ('method','api_attempts','repairs','input_tokens','output_tokens','latency_p50_s','latency_p95_s','estimated_cost','actual_cost')} for s in summary],
      'unknown_actual_cost_is_not_zero':True})
    audits=[{'request_id':r['request_id'],'method':r['method'],'track':r['track'],
      'source_order_key':r['source_order_key'],'status':r['status'],'proposed_label':r['proposed_label'],
      'screen_intervened':r['screen_intervened'],'raw_hard_wrong':r['raw_avoidable_hard_wrong'],
      'ast_accuracy':r['ast_accuracy'],'raw_priority_regret':r['raw_priority_regret'],
      'evidence_dir':f"selector_inputs/{r['method']}/{r['request_id']}" if r['method'] in REMOTE else None}
      for r in rows if r['screen_intervened'] or r['raw_avoidable_hard_wrong'] or
      (r['ast_accuracy'] and not r['ast_accuracy']['whole_policy']) or
      (r['method'] in REMOTE and r['raw_optimal_hit'] is True)]
    write_csv(root/'audit/cases.csv',audits)
    return summary,pairs


def finish(root,items,rows):
    replay_result=replay(root,items,rows)
    summary,pairs=summarize(root,items,rows)
    complete=all(next(s for s in summary if s['method']==m)['done']==len(items) for m in REMOTE)
    offline=replay_result['status']=='PASS' and replay_result['committed_physical_violations']==0
    acceptance={'offline_engineering_status':'PASS' if offline else 'FAIL',
      'remote_matrix_status':'COMPLETE' if complete else 'PENDING_REAL_DEEPSEEK_CALLS',
      'remote_matrix_engineering_status':'PASS' if complete and offline else 'PENDING' if offline else 'FAIL',
      'statistical_design_status':'PENDING_INDEPENDENT_REPEATS_AND_POWER_SIMULATION' if complete else 'NOT_STARTED',
      'o2b_full_acceptance':'PENDING_STATISTICAL_DESIGN' if complete and offline else 'PENDING' if offline else 'FAIL',
      'research_status':'DEVELOPMENT_EVIDENCE_ONLY' if complete else 'NOT_TESTED',
      'old_human_signoffs_not_inferred':True,'source_orders':30,'planned_rows':len(items)*len(METHODS),
      'actual_rows':len(rows),'model_advantage_is_not_engineering_gate':True}
    write_json(root/'acceptance_report.json',acceptance)
    (root/'o2b_report.md').write_text(
      '# O2b 受限AST开发与验收记录\n\n'
      '数据：O1b `_03` 原train派生30独立订单、180道A/B/C开发题，不是未见test。'
      '真值状态、buffer_size=1、旧物理候选器、Top-K=16不变。\n\n'
      f"离线工程/回放：{acceptance['offline_engineering_status']}；真实Flash矩阵：{acceptance['remote_matrix_status']}；"
      f"全项验收：{acceptance['o2b_full_acceptance']}。研究状态：{acceptance['research_status']}。\n\n"
      '六方法逐题结果在 metrics/per_decision.csv，分轨在 metrics/per_track.csv；字段准确率、业务表现与开销在 metrics/summary.json；'
      '政策配对在 metrics/policy_pairs.csv；覆盖、费用及成功/失败审计分别见 metrics/coverage_report.json、'
      'metrics/cost_summary.json、metrics/paired_cluster_ci.json、audit/cases.csv。真值AST仅为特权参考。所有非特权方法共享公开解析业务提交屏障，'
      '原始提议与最终动作分别统计。屏障只能拦截并abstain，不会替模型改选候选。\n\n'
      'Direct错误只能独立核实所选候选的关系/优先级差距，不能由此断言模型内部具体算错哪一步。'
      '未知账单记null。正式测试组数、重复次数及预算须在远程开发结果和账单齐备后再冻结。'
      'O1b/O2a的人工双人签认状态沿用原产物，不在此自动标为完成。\n',encoding='utf-8')
    return acceptance


def run(root,items,client,limit):
    file=root/'metrics/per_decision.json'
    records=read_json(file) if file.exists() else []
    by={(r['request_id'],r['method']):r for r in records}
    budget=limit
    for task,req,group in items:
        for method in METHODS:
            key=(req['request_id'],method)
            prior=by.get(key)
            if prior and (method not in REMOTE or prior['status']!='blocked_no_api_key'):continue
            if method in REMOTE and client and (budget is None or budget>0):
                row=remote(root,task,req,group,method,client)
                if budget is not None:budget-=1
                print('O2b',req['request_id'],method,row['status'],flush=True)
            else: row=offline(task,req,method)
            by[key]=row
            write_json(file,[by[k] for k in sorted(by)])
    rows=[by[k] for k in sorted(by)]
    write_csv(root/'metrics/per_decision.csv',rows)
    return rows


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output',type=Path,default=OUTPUT)
    p.add_argument('--parent-o1b',type=Path,default=PARENT)
    p.add_argument('--resume',action='store_true')
    p.add_argument('--remote',action='store_true')
    p.add_argument('--limit-remote',type=int,default=None)
    args=p.parse_args(argv)
    root=args.output.resolve();parent=args.parent_o1b.resolve()
    if any(x.startswith('EXP_1C_') for x in root.parts) or root==parent or parent in root.parents:
        raise ValueError('Use a new O2b output directory, never historical outputs')
    if args.limit_remote is not None and args.limit_remote<0:raise ValueError('limit must be >=0')
    if args.remote and not os.environ.get('DEEPSEEK_API_KEY'):
        raise ValueError('DEEPSEEK_API_KEY must be set in the process environment')
    items=resume(root,parent) if args.resume else prepare(root,parent)
    rows=run(root,items,DeepSeekClient() if args.remote else None,args.limit_remote)
    result=finish(root,items,rows)
    print({'output':str(root),'offline':result['offline_engineering_status'],
           'remote':result['remote_matrix_status'],'all':result['o2b_full_acceptance']})


if __name__=='__main__':main()
