"""C1 saved-only public sampling and concrete v13 fork plans; never executes suffixes."""
import copy,json,math,time
from collections import Counter
from pathlib import Path
from semantic_pallet_planner.jev_select import packaging_jev_v13 as v, packaging_jev_sampling as s,packaging_jev_training_template as t
from semantic_pallet_planner.jev_select.contracts import digest
from semantic_pallet_planner.jev_select.ledger import read,write
OUT=Path(__file__).resolve().parent;BASE=Path('semantic_pallet_planner/outputs/JEV_JM1_B2_FREEZE_CLOSURE_20261112_01')
f=read(BASE/'formal_freeze.json');p=read(BASE/'materials/training_plan.json');task_order=[j['task_id'] for j in f['jobs']]
assert not (OUT/'fork_plan.json').exists()
public=[];indexes=[];baseline=[];full_saved={};public_locations={}
for i,j in enumerate(f['jobs'],1):
 receipt=read(OUT/f'job_{i}_receipt.json');assert receipt['technical_valid'] is True
 root=Path(j['storage_root']);saved=v.validate_saved_execution(root);cp=saved['checkpoint'];ex=saved['execution'];full_saved[j['task_id']]=(root,saved)
 ep=read(root/'episode.json');assert ep['checkpoint']==cp
 rows=read(root/'ledger/requests.json')['requests']
 events=cp['events']+([cp['pending_event']] if cp['pending_event'] else [])
 contexts=[e for e in events if e.get('context')]
 assert all(e['context']['request_body']['state']['memories']==[] for e in contexts if e['context'].get('request_body') is not None)
 assert all(e.get('selection',{}).get('source')!='FORCED_FROM_FROZEN_POOL' for e in contexts if e.get('selection'))
 assert sum(r['send_started'] for r in rows)<=j['max_sends']
 output=OUT/'public'/f'baseline_{i}';idx=v.export_public(root,output)
 indexes.append(dict(task_id=j['task_id'],index_ref=v.ref(output/'index.json'),**idx))
 for entry in idx['decisions']:
  if entry['status']=='PUBLIC_SAVED':
   record=read(output/entry['public_ref']['path']);s.validate_saved_evidence(record,root=output);public.append(record);public_locations[digest(record)]=dict(export_root=str(output),projection_ref=v.ref(output/entry['public_ref']['path']),prefix_ref=v.ref(output/record['prefix_ref']['path']),pool_ref=v.ref(output/record['pool_ref']['path']))
 state=cp['state'];placed=state['placed_items'];task=ex['task'];container=state['container']
 vol=sum(math.prod(x['oriented_size_mm']) for x in placed);area=container['length_mm']*container['width_mm'];height=max((x['pose']['z_base_mm']+x['oriented_size_mm'][2] for x in placed),default=0)
 statuses=Counter(e['monitor']['status'] for e in events if e.get('monitor'))
 selections=Counter(e['selection']['status'] for e in contexts if e.get('selection'))
 usage=[(r['selection'] or {}).get('usage') for r in rows]
 baseline.append(dict(task_id=j['task_id'],source_group=task['source_group_id'],source_component=p['assignments'][i-1]['component'],feasibility=task['feasibility_status'],status=receipt['status'],reason=cp['reason'],completed=len(placed)==len(task['items']),planned_items=len(task['items']),placed_items=len(placed),placed_item_ratio=len(placed)/len(task['items']),placed_volume_ratio=vol/sum(math.prod(x['dimensions_mm'].values()) for x in task['items']),placed_mass_ratio=sum(x['mass_kg'] for x in placed)/sum(x['mass_kg'] for x in task['items']),placed_mass_kg=sum(x['mass_kg'] for x in placed),fixed_container_utilization=vol/(area*container['max_height_mm']),height_mm=height if height else 'NA',envelope_utilization=vol/(area*height) if height else 'NA',selected_actions=sum(selections.get(k,0) for k in ('selected','singleton')),monitor_statuses=dict(statuses),first_predicted_instability_progress=next((dict(placed_before=e['before']['placed_count'],planned_items=len(task['items'])) for e in events if (e.get('monitor') or {}).get('status')=='UNSTABLE'),'NA_NO_PREDICTED_INSTABILITY'),all_context_decisions=len(contexts),all_saved_events=len(events),empty_pool_events=sum(bool(e.get('bundle')) and not e['bundle']['selectable_candidates'] for e in events),singleton=selections.get('singleton',0),invalid_or_missing_selection=sum(e['context']['route']=='CHOICE_REQUIRED' and (e.get('selection') or {}).get('status')!='selected' for e in contexts),request_states=dict(Counter(r['state'] for r in rows)),requests=sum(r['send_started'] for r in rows),unknown_sends=sum(r['state']=='UNKNOWN_SEND' for r in rows),usage=usage,cost='UNKNOWN',elapsed_s=receipt['elapsed_s'],event_timings=[e.get('timings',{}) for e in events],selection_latency_s=[r['transport']['latency_s'] for r in rows if r.get('transport')],monitor_duration_s=[e['monitor']['result']['duration_s'] for e in events if e.get('monitor') and e['monitor'].get('result')],ledger_ref=v.ref(root/'ledger/requests.json'),checkpoint_ref=v.ref(root/'checkpoint_head.json'),recovery_validation='v13.validate_saved_execution PASS; no replay or resend'))
 print(json.dumps(dict(saved_baseline=i,public_decisions=len(idx['decisions'])),ensure_ascii=False),flush=True)
write(OUT/'baseline_receipt.json',dict(version='jm_c1_real_baselines_receipt_v1',jobs=baseline,planned_jobs=6,actual_requests=sum(j['requests'] for j in baseline),unknown_sends=sum(j['unknown_sends'] for j in baseline),cost='UNKNOWN',suffix_sends=0,research_benefit='NOT_ESTABLISHED_NO_SUFFIX_COMPARISON'))
write(OUT/'public_input_inventory.json',dict(version='jm_c1_public_sampling_input_inventory_v1',indexes=indexes,all_public_records=len(public),boundary='only public.json records passed to sampler; private_audit never supplied'))
# Input has only public projections/native raw bytes; no metrics or terminal facts passed.
diag=s.sample(public,task_order=task_order);assert diag==s.sample(copy.deepcopy(public),task_order=task_order);write(OUT/'sampling_diagnostic.json',diag)
write(OUT/'epsilon_receipt.json',dict(version='jm_c1_frozen_epsilon_receipt_v1',epsilon=diag['diagnostic_epsilon'],basis='frozen B1 policy lower quartile of observed positive relative native gaps capped at 1/10; exact rational',positive_gap_denominator=diag['positive_gap_denominator'],policy_sha256=s.POLICY_SHA256,public_projection_digests=[digest(x) for x in public],native_precision='SAVED_LEXEMES_ONLY_PROVIDER_INTERNAL_UNKNOWN',frozen_before_any_suffix_result=True,suffix_sends=0))
points=[];meta=[]
for no,point in enumerate(diag['selected_points']):
 proj=next(x for x in public if digest(x)==point['projection_digest']);point_id='P'+str(no+1).zfill(2)+'_'+digest(point)[:12]
 row=dict(point,point_id=point_id,public_projection=copy.deepcopy(proj),public_evidence_location=public_locations[digest(proj)],source_component=next(a['component'] for a in p['assignments'] if a['task_id']==point['task_id']),selection_reason='SELECTED_BY_FROZEN_B1_POLICY',placed_before=len(proj['public_state']['placed_objects']))
 points.append(row);meta.append(dict(point_id=point_id,task_id=point['task_id'],stage=point['stage'],source_component=row['source_component'],decision_digest=point['projection_digest']))
repeat_ids=t.repeat_priority(meta,task_order=task_order);jobs=[]
for point in points:
 print(json.dumps(dict(materializing_point=point['point_id'])),flush=True)
 root,saved=full_saved[point['task_id']];parent=saved['execution'];start=v.capture_start(root,point['decision_id'])
 for n,b in enumerate(point['branches']):
  pool=point['public_projection']['pool'];chosen=next(x for x in pool if x['candidate_id']==b['candidate_id']);assert chosen['candidate_digest']==b['candidate_digest']
  for repeat in (['r0','r1'] if point['point_id'] in repeat_ids else ['r0']):
   branch_root=OUT/'future_suffix_runs'/point['point_id']/('B'+str(n))/repeat
   ex=v.freeze_execution(parent['task'],parent['config'],job_id='JM1_C2_'+point['point_id']+'_B'+str(n)+'_'+repeat,root=branch_root,repeat_slot=repeat,start=start,forced_label=b['label'])
   path=OUT/'concrete_executions'/(ex['job_id']+'.json');write(path,ex)
   jobs.append(dict(point_id=point['point_id'],task_id=point['task_id'],branch_kind=b['kind'],repeat_slot=repeat,forced_label=b['label'],candidate_id=b['candidate_id'],candidate_digest=b['candidate_digest'],exact_action_digest=b['exact_action_digest'],exact_action=b['action'],frozen_candidate=chosen['frozen_candidate'],job_id=ex['job_id'],allocation_id=ex['allocation_id'],max_sends=ex['max_sends'],execution_ref=v.ref(path),storage_root=str(branch_root),status='NOT_RUN_NOT_AUTHORIZED'))
initial=[j for j in jobs if j['repeat_slot']=='r0'];repeated=[j for j in jobs if j['repeat_slot']=='r1']
assert len(points)<=12 and len(initial)<=36 and len(repeated)<=12 and len(jobs)<=48
assert sum(j['max_sends'] for j in initial)<=564 and sum(j['max_sends'] for j in repeated)<=210
budget=dict(version='jm_c1_concrete_suffix_budget_v1',baseline_upper=103,baseline_actual_requests=sum(j['requests'] for j in baseline),points=len(points),initial_jobs=len(initial),repeat_jobs=len(repeated),total_suffix_jobs=len(jobs),initial_send_upper=sum(j['max_sends'] for j in initial),repeat_send_upper=sum(j['max_sends'] for j in repeated),suffix_send_upper=sum(j['max_sends'] for j in jobs),global_plan_send_upper=103+sum(j['max_sends'] for j in jobs),frozen_global_reservation=877,unused='NONTRANSFERABLE_NO_REFILL',suffix_authorized=0,suffix_actual_sends=0)
write(OUT/'concrete_budget_receipt.json',budget)
write(OUT/'repeat_plan.json',dict(version='jm_c1_concrete_repeat_plan_v1',metadata=meta,selected_point_ids=repeat_ids,rule='packaging_jev_training_template.repeat_priority',repeat_count_per_branch=1,frozen_before_any_suffix_result=True))
coverage=dict(version='jm_c1_sampling_coverage_receipt_v1',counts=diag['counts'],tasks=diag['per_task_coverage'],gaps=diag['coverage_gaps'],all_decision_inventory=indexes,baseline_decisions=[dict(task_id=b['task_id'],all_context_decisions=b['all_context_decisions'],all_saved_events=b['all_saved_events'],empty_pool_events=b['empty_pool_events'],singleton=b['singleton'],invalid_or_missing_selection=b['invalid_or_missing_selection']) for b in baseline],claim_scope=diag['claim_scope'],outcome_based_sampling=False,source_caution='four exposed source orders/three conservative components; not six independent unseen sources; synthetic packaging loads, feasibility UNKNOWN')
write(OUT/'sampling_coverage_receipt.json',coverage)
fork=dict(version='jm_c1_concrete_fork_plan_artifact_v1',scope='C1_MATERIALIZED_SAVED_PLAN_NOT_SEND_PERMIT',formal_freeze_receipt=f['receipt_digest'],preparation_digest=f['preparation_digest'],policy_sha256=s.POLICY_SHA256,task_order=task_order,epsilon_ref=v.ref(OUT/'epsilon_receipt.json'),points=points,repeat_ref=v.ref(OUT/'repeat_plan.json'),jobs=jobs,budget_ref=v.ref(OUT/'concrete_budget_receipt.json'),suffix_execution_authorized=False,suffix_sends=0,stop=True)
fork['artifact_digest']=digest(fork);write(OUT/'fork_plan.json',fork)
print(json.dumps(dict(points=len(points),jobs=len(jobs),requests=sum(j['requests'] for j in baseline),epsilon=diag['diagnostic_epsilon'],budget=budget),ensure_ascii=False),flush=True)
