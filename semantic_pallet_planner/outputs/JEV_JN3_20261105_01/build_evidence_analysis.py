"""Read saved pilot records; write descriptive evidence to a separate destination.

Run under readonly_guard.py after experiments. No actions, retrieval, API or PCT.
"""
import argparse,json,hashlib
from pathlib import Path
from semantic_pallet_planner.jev_select.packaging_pilot_analysis import recommendation
p=argparse.ArgumentParser();p.add_argument('--output',required=True);p.add_argument('--destination',required=True);a=p.parse_args()
root=Path(a.output);run=root/'run';plan=json.loads((root/'plan/plan.json').read_text());dest=Path(a.destination);dest.mkdir(parents=True,exist_ok=True)
read=lambda f:json.loads(f.read_text())
def save(n,v):(dest/n).write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n')
summary=read(run/'summary.json');pairs=read(run/'paired_differences.json') if (run/'paired_differences.json').exists() else []
behavior=read(run/'behavior_analysis.json') if (run/'behavior_analysis.json').exists() else {'matched_state_comparisons':[]}
jobs=read(run/'job_ledger.json');rows=[];exposure=[]
for job in plan['jobs']:
 path=run/'jobs'/job['job_id'];status=read(path/'status.json');metric=read(path/'metrics.json') if (path/'metrics.json').exists() else None
 cp=read(path/'checkpoint.json') if (path/'checkpoint.json').exists() else None
 rows.append({'job_id':job['job_id'],'task_id':job['task_id'],'source_group':job['source_group_id'],'method':job['method_id'],'mode':job['config']['memory_mode'],
              'status':status,'metrics':metric if metric is not None else 'NOT_RUN' if status['category']=='NOT_RUN' else 'UNKNOWN_TECHNICAL_FAILURE',
              'budget':plan['request_budget']['per_job'][job['job_id']],
              'placed_set':sorted(o['item_id'] for o in cp['state']['placed_items']) if cp else 'NOT_RUN',
              'layout':cp['state']['placed_items'] if cp else 'NOT_RUN'})
 if cp:
  for e in cp['events']+([cp['pending_event']] if cp['pending_event'] else []):
   if not e.get('decision_id'):continue
   ctx=e['context'];view=ctx['memory_view'];r=ctx['retrieval_receipt'];selected=e['selection'] or {};before=e['before']
   exposure.append({'job_id':job['job_id'],'method':job['method_id'],'mode':view['mode'],'decision_id':e['decision_id'],
     'current_placed_count':len(before['placed_items']),'query':r['query'],'query_digest':r['query_digest'],'snapshot_digest':r['snapshot_digest'],
     'retrieval_status':r['status'],'source_exclusion':job['config']['excluded_source_groups'],
     'scores_and_length_handling':r['raw_retrieval'] if r['raw_retrieval'] else 'NO_LOOKUP',
     'view_entries':len(view['entries']),'view_chars':view['injected_chars'],'view_utf8_bytes':view['injected_utf8_bytes'],
     'body_has_memory':bool(ctx['request_body'] and ctx['request_body']['state']['memories']),
     'native_request_origin':selected.get('source','NOT_SENT'),'network_attempted':selected.get('network_attempted',False),
     'usage':selected.get('usage') if selected.get('network_attempted') else 'NOT_SENT',
     'historical_empty_pallet_fragments':all((x.get('condition') or x.get('observable_conditions'))['placed_count']==0 for x in view['entries']) if view['entries'] else 'NO_ENTRY',
     'route':ctx['route'],'monitor':(e.get('monitor') or {}).get('status','NOT_RUN'),'event':e['event']})
axes=[]
for row in pairs:
 if row['reference_method']!='jev_no_memory':continue
 matched=[m for m in behavior['matched_state_comparisons'] if m['task_id']==row['task_id'] and {m['reference']['method'],m['alternative']['method']}=={row['reference_method'],row['alternative_method']}]
 actual=[e for e in exposure if e['method']==row['alternative_method'] and next(j['task_id'] for j in plan['jobs'] if j['job_id']==e['job_id'])==row['task_id'] and e['body_has_memory'] and e['network_attempted']]
 axes.append({'task_id':row['task_id'],'method':row['alternative_method'],'actual_nonempty_network_attempts':len(actual),
   'exposure_axis':'NOT_INJECTED' if not actual else 'NONEMPTY_BODY_NETWORK_ATTEMPT_OBSERVED',
   'same_state_pairs':len(matched),'different_action_pairs':sum(not m['same_exact_action'] for m in matched),
   'behavior_axis':'NO_MATCHED_STATE_EVIDENCE' if not matched else 'CHANGED_ON_MATCHED_STATES' if any(not m['same_exact_action'] for m in matched) else 'SAME_ON_OBSERVED_MATCHED_STATES',
   'outcome_axis':row['evaluation']['label_v2'] if row['evaluation']['comparison_valid'] else 'INVALID_RANGE_TECHNICAL_OR_NOT_RUN',
   'complete_pair':row,'interpretation':'axes are separate; nonempty body does not prove use, and changed choice does not establish causal benefit'})
save('job_outcomes.json',rows);save('memory_exposure_diagnostics.json',exposure);save('behavior_outcome_axes.json',axes)
save('negative_and_uncertain_results.json',{'all_memory_vs_none_axes':axes,'non_improved_or_invalid':[x for x in axes if x['outcome_axis']!='improved'],
 'limitations':['two exposed development sources only','history material contains only empty-pallet fragments even when current query is nonempty; no new projection or cards added',
 'T has normalized location detail; E has bounded hypotheses and counts; shared caps/result fields do not establish complete information fairness','no extra same-state paired requests; compare only exact saved state/pool matches','fixed v2 analysis and all height/cost regressions retained','fees UNKNOWN if no bill; no significance, causal-use or unseen-generalization claim']})
rec=recommendation(run,plan);save('memory_pilot_receipt.json',rec)
save('cost_and_information_budget.json',{'request_statistics':summary.get('request_statistics','UNKNOWN_TECHNICAL_FAILURE'),
 'registered_request_budget':plan['request_budget'],'retrieval_rule':plan['retrieval_rule'],'information_budget':plan['information_budget'],
 'current_DeepSeek_calls':0,'current_reviewer_model_calls':0,'historical_T_single_decision_calls':1,'historical_E_single_decision_calls':1,'historical_DeepSeek_extractions':2,
 'cost_accounting':'current native request ledger only; historical calls not counted as C jobs; billed USD UNKNOWN; no inferred bill'})
print(json.dumps({'status':'PASS','jobs':len(rows),'decisions':len(exposure),'recommendation':rec['recommendation']}))
