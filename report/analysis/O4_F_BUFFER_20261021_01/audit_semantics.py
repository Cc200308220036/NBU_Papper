"""Posthoc chapter-8 compiler/allow-set audit; never feeds a planner."""
import sys
sys.path.insert(0,'semantic_pallet_planner/src')
from pathlib import Path
from collections import defaultdict
from semantic_pallet_planner.o4.common import read,write,digest
from semantic_pallet_planner.o4.evaluator import compare_policies,reference_state
from semantic_pallet_planner.runners.o4_buffer import path_for,read_jsonl
ROOT=Path('semantic_pallet_planner/outputs/EXP_O4_F_BUFFER_20261021_01')
OUT=Path('report/analysis/O4_F_BUFFER_20261021_01')

def main():
    inputs=read(ROOT/'private/input_snapshot.json');tasks={t['task_id']:t for t in inputs['tasks']};rows=read(ROOT/'metrics/per_episode.json')
    signatures={};witnesses=defaultdict(dict);events_by_method=defaultdict(list)
    for row in rows:
        ref=tasks[row['task_id']]['reference_policy']
        for e in read_jsonl(path_for(ROOT,row['method'],row['backend'],row['task_id'])):
            if not e.get('response'):continue
            ast=e['response']['policy_ast'];key=digest([ast,ref]);signatures[key]=(ast,ref)
            obs=e['public_state']['observation']
            for o in obs['placed_objects']+obs['available_objects']:witnesses[key][digest(o)]=o
            method_allowed={c['candidate_id'] for g in e['root_pools'] for c in g['joint'] if c['local_label'] in g['evaluation']['allowed_ids']}
            reference_allowed=set(e['reference_root']['allowed_ids'])
            matched=reference_state(obs['placed_objects'],ast);expected=reference_state(obs['placed_objects'],ref)
            object_equal=matched['applicable_objects']==expected['applicable_objects']
            candidate_objects_equal=True
            for g in e['root_pools']:
                by_local={v['candidate_id']:v for v in g['evaluation']['evaluations']}
                by_joint={v['candidate_id']:v for v in e['reference_root']['evaluations']}
                for c in g['joint']:
                    if by_local[c['local_label']]['after']['applicable_objects']!=by_joint[c['candidate_id']]['after']['applicable_objects']:candidate_objects_equal=False
            chosen=e.get('action',{});selected=chosen.get('candidate_label') if chosen else None
            events_by_method[(row['method'],row['backend'])].append({'task_id':row['task_id'],'event_index':e['event_index'],
                'semantic_case_digest':key,'valid_first_response':True,'object_sets_equal':object_equal and candidate_objects_equal,
                'current_placed_target_sets':matched['applicable_objects'],'empty_target_rules':[k for k,v in matched['applicable_objects'].items() if not v],
                'allow_sets_equal':method_allowed==reference_allowed,'false_allow':sorted(method_allowed-reference_allowed),
                'false_reject':sorted(reference_allowed-method_allowed),'method_allowed_count':len(method_allowed),'reference_allowed_count':len(reference_allowed),
                'proposed_reference_violation':selected is not None and selected not in reference_allowed})
    semantics={key:compare_policies(ast,ref,list(witnesses[key].values())) for key,(ast,ref) in signatures.items()}
    per_method=[];all_records=[]
    for (m,b),records in sorted(events_by_method.items()):
        for rec in records:
            result=semantics[rec['semantic_case_digest']];rec['full_semantic_correct']=result['semantic_equal'] and result['finite_domain_equal'];rec['raw_ast_equal']=result['raw_ast_equal']
        conditions=[r for r in records if any('and' in str(v) for v in signatures[r['semantic_case_digest']][1]['rules'])]
        exceptions=[r for r in records if any(v['overrides'] for v in signatures[r['semantic_case_digest']][1]['rules'])]
        per_method.append({'method':m,'backend':b,'planned_order_denominator':72,'actual_compile_requests':len(records),
            'first_valid_ast':sum(r['valid_first_response'] for r in records),'final_valid_ast':sum(r['valid_first_response'] for r in records),
            'full_semantic_correct':sum(r['full_semantic_correct'] for r in records),'object_sets_correct':sum(r['object_sets_equal'] for r in records),
            'allow_sets_equal':sum(r['allow_sets_equal'] for r in records),'false_allow':sum(len(r['false_allow']) for r in records),
            'false_reject':sum(len(r['false_reject']) for r in records),'raw_ast_equal':sum(r['raw_ast_equal'] for r in records),
            'condition_request_denominator':len(conditions),'condition_correct':sum(r['full_semantic_correct'] for r in conditions),
            'override_request_denominator':len(exceptions),'override_correct':sum(r['full_semantic_correct'] for r in exceptions),
            'proposed_reference_violations':sum(r['proposed_reference_violation'] for r in records),
            'real_api_attempts':0,'real_model_accuracy':None,'input_tokens':None,'output_tokens':None,'cost':None})
        all_records.append({'method':m,'backend':b,'records':records})
    failed=[r for g in all_records for r in g['records'] if not all(r[k] for k in ('full_semantic_correct','object_sets_equal','allow_sets_equal'))]
    result={'status':'PASS' if not failed else 'FAIL','scope':'strong public parser and privileged AST only; not real model accuracy',
            'semantic_comparisons':semantics,'methods':per_method,'records':all_records,'failed_records':failed,
            'finite_probe_cache':'one comparison per exact actual/reference AST pair; witnesses union all observed public facts, plus declared finite probes; never fed back to selection'}
    write(OUT/'semantic_metrics.json',result)
    print(result['status'],[(r['method'],r['backend'],r['actual_compile_requests']) for r in per_method],flush=True)
    if failed:raise SystemExit(1)

if __name__=='__main__':main()
