"""C2 saved-only audit, metrics and preregistered v2 comparison; no execution."""
import collections,hashlib,json,math,subprocess,time
from pathlib import Path
from semantic_pallet_planner.jev_select import packaging_jev_v13 as v,packaging_reanalysis as evaluation
from semantic_pallet_planner.jev_select.contracts import digest
from semantic_pallet_planner.jev_select.experiment import source_manifest
from semantic_pallet_planner.jev_select.ledger import read,write
OUT=Path(__file__).resolve().parent;ROOT=Path.cwd()
C1=Path('semantic_pallet_planner/outputs/JEV_JM1_C1_REAL_BASELINES_20261112_01')
B2=Path('semantic_pallet_planner/outputs/JEV_JM1_B2_FREEZE_CLOSURE_20261112_01')
def forbid(*a,**kw):raise AssertionError('SAVED_ONLY_FORBIDDEN_DISPATCH')
def guards():
 from semantic_pallet_planner.jev_select import transport,episode,execution
 from semantic_pallet_planner.jev_select.stability import monitor,exact_adapter
 from semantic_pallet_planner.o4.extensions.e2 import planning
 import scipy.optimize
 transport.JevTransport.complete=forbid;episode.run_episode=forbid;execution.commit_physical=forbid
 monitor.monitor_selected_action=forbid;exact_adapter.assess_candidate=forbid;scipy.optimize.linprog=forbid
 planning.pools=forbid;planning.search=forbid;planning.choose=forbid;planning.commit=forbid
def ref(p):return v.ref(p)
def rel(p):return str(Path(p).resolve().relative_to(ROOT))
def numeric(x):return type(x) in (int,float) and math.isfinite(x)
def metric_view(ex,cp,receipt,rows):
 task=ex['task'];state=cp['state'];placed=state['placed_items'];den=evaluation.task_denominators(task)
 volume=sum(math.prod(x['oriented_size_mm']) for x in placed);mass=sum(x['mass_kg'] for x in placed)
 area=state['container']['length_mm']*state['container']['width_mm'];height=max((x['pose']['z_base_mm']+x['oriented_size_mm'][2] for x in placed),default=0)
 events=cp['events']+([cp['pending_event']] if cp['pending_event'] else [])
 monitors=[e for e in events if e.get('monitor')];sels=[e['selection'] for e in events if e.get('selection')]
 statuses=dict(collections.Counter(e['monitor']['status'] for e in monitors))
 usages=[r['selection'].get('usage') for r in rows if r.get('selection') and isinstance(r['selection'].get('usage'),dict)]
 lat=[r['transport']['latency_s'] for r in rows if r.get('transport')]
 cat={'ALL_ITEMS_PLACED':'COMPLETE','STOP_NO_PHYSICAL_CANDIDATE':'EMPTY_POOL','PREDICTED_STATIC_INSTABILITY':'PREDICTED_STATIC_INSTABILITY','STABILITY_UNASSESSABLE':'UNASSESSABLE'}.get(cp['reason'],'ERROR') if receipt['technical_valid'] else 'ERROR'
 first=next((dict(placed_before=e['before']['placed_count'],planned_items=den['items'],progress=e['before']['placed_count']/den['items']) for e in monitors if e['monitor']['status']=='UNSTABLE'),'NA_NO_PREDICTED_INSTABILITY')
 for e in events:
  if e.get('monitor') and e['monitor']['status'] not in ('STABLE','DISABLED'):
   assert e['action'] is None and e['after']==e['before'] and e['event']!='PLACE'
 result=dict(task_digest=digest(task),data_identity=ex['config']['runtime_identity']['data_identity'],denominators=den,category=cat,stable_complete=cat=='COMPLETE' and len(placed)==den['items'],placed_items=len(placed),placed_item_ratio=len(placed)/den['items'],placed_volume_mm3=volume,placed_volume_ratio=volume/den['volume_mm3'],placed_mass_kg=mass,placed_mass_ratio=mass/den['mass_kg'],fixed_container_utilization=volume/(area*state['container']['max_height_mm']),actual_height_mm=height if height else 'NA_EMPTY',envelope_utilization=volume/(area*height) if height else 'NA_EMPTY',first_predicted_instability_progress=first,monitor_statuses=statuses,monitor_unassessable=statuses.get('UNASSESSABLE',0),monitor_errors=statuses.get('ERROR',0),technical_failure=not receipt['technical_valid'],selected_actions=len(sels),forced_actions=sum(s['source']=='FORCED_FROM_FROZEN_POOL' for s in sels),singleton_actions=sum(s['source']=='singleton' for s in sels),commits=sum(e['event']=='PLACE' for e in events),requests=sum(r['send_started'] for r in rows),network_attempted=sum(bool((r.get('transport') or {}).get('network_attempted')) for r in rows),unknown_sends=sum(r['state'] in ('UNKNOWN_SEND','SENDING') for r in rows),failed_requests=sum(r['state']=='FAILED' for r in rows),request_states=dict(collections.Counter(r['state'] for r in rows)),usage_records=len(usages),input_tokens=sum(u.get('input_tokens',0) for u in usages),output_tokens=sum(u.get('output_tokens',0) for u in usages),missing_usage_records=sum(r['send_started'] for r in rows)-len(usages),selection_latency_s_total=sum(lat),selection_latency_s_mean=sum(lat)/len(lat) if lat else 'NA_NO_REQUEST',elapsed_s=receipt['elapsed_s'],monitor_duration_s=sum(e['monitor']['result']['duration_s'] for e in monitors if e['monitor'].get('result')),kernel_calls=sum(e['monitor']['result'].get('kernel_calls',0) for e in monitors if e['monitor'].get('result')),model_cost_usd='UNKNOWN',memory_cost_usd='NA_NO_MEMORY_RETRIEVAL',unassessable_scope='strict interior/conservative hull/degenerate contact boundaries retained')
 stage_keys=('physical_generation_s','facts_context_s','public_parse_s','selection_s','decision_wall_s','decision_segments_s','physical_commit_s','checkpoint_io_s','independent_evaluation_s','public_business_s')
 samples={key:[e['timings'][key] for e in events if numeric(e.get('timings',{}).get(key))] for key in stage_keys}
 for key,values in samples.items():result['saved_event_'+key+'_total']=sum(values) if values else 'NOT_RECORDED'
 assessed=sum(statuses.get(k,0) for k in ('STABLE','UNSTABLE'));attempted=sum(statuses.get(k,0) for k in ('STABLE','UNSTABLE','UNASSESSABLE','ERROR'))
 result.update(completed=len(placed)==den['items'],monitor_assessable_count=assessed,monitor_evaluation_count=attempted,monitor_assessable_coverage=assessed/attempted if attempted else 'NA_NO_MONITOR',monitor_result_reasons=dict(collections.Counter((e['monitor'].get('result') or {}).get('reason_code','UNKNOWN') for e in monitors)),stage_latency_samples_s=samples,transport_latency_samples_s=lat,transport_stage_timing_samples=[r['transport'].get('stage_timings',{}) for r in rows if r.get('transport')],request_origins=dict(collections.Counter(r['origin'] for r in rows)),confirmed_responses=sum(bool(r.get('transport')) and r['transport']['status']=='OK' for r in rows),latency_interpretation='Per-stage raw samples and within-stage sums only; nested stage totals are never added into an order time. Quantiles NOT_ESTIMATED.')
 return result
def main():
 guards();assert source_manifest()==read(B2/'source_manifest.json')
 batch=read(OUT/'batch_receipt.json');order=read(OUT/'execution_order.json')['jobs'];plan=read(C1/'fork_plan.json')
 points={p['point_id']:p for p in plan['points']};by_job={j['job_id']:j for j in plan['jobs']};results=[];validations=[]
 for rec in batch['jobs']:
  j=by_job[rec['job_id']];ex=v.load_ref(j['execution_ref']);root=Path(ex['storage_root'])
  row=dict(j,version='jm_c2_branch_metrics_v1',execution_digest=digest(ex),receipt_ref=ref(OUT/'job_receipts'/(ex['job_id']+'.json')),status=rec['status'],technical_valid=rec['technical_valid'],reason=rec.get('reason',rec.get('error_code')),source_component=points[j['point_id']]['source_component'],source_group=ex['task']['source_group_id'],source_order_key=ex['task']['source_order_key'])
  if rec['status']=='NOT_RUN':
   assert not root.exists();row.update(metrics='NOT_RUN',send_interval=[0,0],cost='UNKNOWN');results.append(row);continue
  try:
   saved=v.validate_saved_execution(root,expected_execution=ex);cp=saved['checkpoint'];rows=read(root/'ledger/requests.json')['requests']
   activation=read(root/'activation.json');initial=activation['initial_checkpoint'];_,_,parent=v.validate_start(ex['start'])
   assert initial['phase']=='SELECTED' and initial['state']==parent['before']
   assert initial['pending_event']['bundle']==parent['bundle']
   assert initial['pending_event']['selection']['source']=='FORCED_FROM_FROZEN_POOL'
   assert initial['pending_event']['selection']['selected_candidate_id']==j['candidate_id']
   assert initial['pending_event']['selection']['model_call_count']==0
   assert digest(ex)==rec['execution_digest']
   assert all(read(p)['request_body']['state']['memories']==[] for p in (root/'ledger/contexts').glob('*.json'))
   sent=sum(r['send_started'] for r in rows);unknown=sum(r['state'] in ('UNKNOWN_SEND','SENDING') for r in rows)
   assert sent<=ex['max_sends']
   if (root/'counts.json').exists():assert read(root/'counts.json')==v.counts(ex,cp,rows)
   metrics=metric_view(ex,cp,rec,rows)
   if rec['technical_valid']:assert cp['phase']=='TERMINATED' and metrics['forced_actions']==1
   row.update(metrics=metrics,send_interval=[sent-unknown,sent],raw_requests_ref=ref(root/'ledger/requests.json'),checkpoint_head_ref=ref(root/'checkpoint_head.json'),saved_validation='PASS',journal_rows=saved['sequence'])
   validations.append(dict(job_id=ex['job_id'],status='PASS',journal_rows=saved['sequence'],memory_empty=True,initial_state_pool_parent_match=True,forced_first_no_model=True,monitor_failure_no_commit=True))
  except Exception as err:
   # Read-only stop: never repair an invalid saved identity or infer performance ranking.
   row.update(technical_valid=False,saved_validation='FAIL',metrics='UNAVAILABLE_INVALID_SAVED_RECORD',send_interval='UNKNOWN',error_class=type(err).__name__,error_code=getattr(err,'code','UNKNOWN'))
   validations.append(dict(job_id=ex['job_id'],status='FAIL',error_class=type(err).__name__))
  results.append(row);write(OUT/'branches'/(ex['job_id']+'.json'),row)
  print(json.dumps(dict(audited=rec['ordinal'],status=row.get('saved_validation'),job=ex['job_id'])),flush=True)
 assert len(results)==18
 lookup={(r['point_id'],r['repeat_slot'],r['branch_kind']=='ORIGINAL_ACTION_REFERENCE'):r for r in results}
 comparisons=[]
 for p in plan['points']:
  for slot in ('r0','r1'):
   key=(p['point_id'],slot,True)
   if key not in lookup:continue
   a=lookup[key];b=lookup[(p['point_id'],slot,False)]
   same=all(a[k]==b[k] for k in ('point_id','task_id','source_component','repeat_slot'))
   assert same
   ea=v.load_ref(a['execution_ref']);eb=v.load_ref(b['execution_ref']);assert ea['start']==eb['start'] and ea['task']==eb['task'] and ea['config']==eb['config']
   available=isinstance(a['metrics'],dict) and isinstance(b['metrics'],dict)
   evaluated=evaluation.evaluate(a['metrics'],b['metrics'],rule_version=evaluation.RULE_VERSION) if available else dict(comparison_valid=False,label_v2='invalid' if a['status']!='NOT_RUN' or b['status']!='NOT_RUN' else 'not_run',invalid_reasons=['PAIR_NOT_RUN_OR_SAVED_FACTS_UNAVAILABLE'],decisive_level='INVALID')
   if not a['technical_valid'] or not b['technical_valid']:evaluated.update(comparison_valid=False,label_v2='invalid' if a['status']!='NOT_RUN' or b['status']!='NOT_RUN' else 'not_run',invalid_reasons=evaluated.get('invalid_reasons',[])+['TECHNICALLY_INVALID_OR_NOT_RUN_NO_RANKING'])
   delta={};changes={}
   if available:
    for k in a['metrics']:
     av=a['metrics'][k];bv=b['metrics'][k]
     delta[k]=bv-av if numeric(av) and numeric(bv) else int(bv)-int(av) if type(av) is bool and type(bv) is bool else 'NA_NONNUMERIC'
     if delta[k]=='NA_NONNUMERIC':changes[k]=dict(reference=av,alternative=bv)
   c=dict(version='jm_c2_pair_comparison_v1',comparison_id=p['point_id']+'_'+slot,point_id=p['point_id'],task_id=p['task_id'],source_component=p['source_component'],repeat_slot=slot,intervention=b['branch_kind'],reference_job=a['job_id'],alternative_job=b['job_id'],reference_branch=ref(OUT/'branches'/(a['job_id']+'.json')) if a['status']!='NOT_RUN' else 'NOT_RUN',alternative_branch=ref(OUT/'branches'/(b['job_id']+'.json')) if b['status']!='NOT_RUN' else 'NOT_RUN',same_prefix_pool_task_follow=True,continuation='jev_no_memory / memories=[]',rule=evaluation.RULE,delta_direction='alternative_minus_reference',evaluation=evaluated,all_numeric_metric_deltas=delta,non_numeric_metric_changes=changes,technical_invalid_ranked=False,baseline_whole_trajectory_used_as_benefit_reference=False)
   comparisons.append(c);write(OUT/'comparisons'/(c['comparison_id']+'.json'),c)
 point_summaries=[];families=[]
 for p in plan['points']:
  pairs=[c for c in comparisons if c['point_id']==p['point_id']];evs=[c['evaluation'] for c in pairs]
  labels=[e['label_v2'] for e in evs if e['comparison_valid']]
  valid_evs=[e for e in evs if e['comparison_valid']];metric_conflicts=[]
  if len(valid_evs)==2:
   for key,tol in [('placed_volume_ratio',1e-9),('placed_items',0),('placed_mass_kg',1e-9),('actual_height_mm',1e-6),('envelope_utilization',1e-9)]:
    x=valid_evs[0]['delta'].get(key);y=valid_evs[1]['delta'].get(key)
    if numeric(x) and numeric(y) and abs(x)>tol and abs(y)>tol and x*y<0:metric_conflicts.append(key)
  conflict=len(set(labels))>1 or bool(metric_conflicts)
  replicated=len(pairs)==2 and len(labels)==2 and not conflict
  grade='REPLICATED_LOCAL_OBSERVATION' if replicated else 'CONFLICTING_LOCAL_OBSERVATIONS' if conflict else 'PROVISIONAL_CASE' if labels else 'INSUFFICIENT_VALID_EVIDENCE'
  public=p['public_projection']['public_state'];conditions=dict(stage=p['stage'],placed_count=p['placed_before'],public_state_digest=digest(public),pool_digest=digest(p['public_projection']['pool']),public_prefix_ref=p['public_evidence_location']['prefix_ref'],pool_ref=p['public_evidence_location']['pool_ref'],intervention=p['branches'][1]['kind'],exact_reference_action=p['branches'][0]['action'],exact_alternative_action=p['branches'][1]['action'])
  row=dict(version='jm_c2_point_evidence_v1',point_id=p['point_id'],task_id=p['task_id'],source_component=p['source_component'],source_group=p['public_projection']['source_group'],public_conditions=conditions,registered_pairs=len(pairs),valid_pairs=len(labels),labels=labels,repeat_registered=len(pairs)==2,repeat_conflict=conflict,opposing_metric_directions=metric_conflicts,label_conflict=len(set(labels))>1,opposite_improvement_degradation='improved' in labels and 'degraded' in labels,evidence_grade=grade,comparisons=[ref(OUT/'comparisons'/(c['comparison_id']+'.json')) for c in pairs],uncertainty='NOT_ESTIMATED; two observations are local clues, not statistical support',cross_start_transfer='NOT_ESTABLISHED')
  point_summaries.append(row);write(OUT/'points'/(p['point_id']+'.json'),row)
  candidate=any(e['comparison_valid'] and e['label_v2']=='improved' and e['decisive_level'] in ('STABLE_COMPLETION','LOADED_VOLUME','COUNT_MASS') for e in evs)
  families.append(dict(family_id='LOCAL_'+p['point_id'],status='LOCAL_CASE_ONLY_NOT_EXECUTABLE_EXPERIENCE',public_conditions=conditions,point_ids=[p['point_id']],covered_starts=1,available_selected_starts=len(plan['points']),covered_source_components=[p['source_component']],available_selected_source_components=len({x['source_component'] for x in plan['points']}),covered_source_orders=[next(r['source_order_key'] for r in results if r['point_id']==p['point_id'])],available_training_source_orders=4,registered_pairs=len(pairs),valid_pairs=len(labels),labels=labels,evidence_grade=grade,repeat_conflict=conflict,cross_start_support=0,cross_source_support=0,positive_loading_proposal_input=candidate and not conflict,positive_input_status='DEFER_CONFLICT' if candidate and conflict else 'LOCAL_CANDIDATE_INPUT_ONLY' if candidate else 'FACTS_AND_COUNTEREVIDENCE_ONLY',factual_evidence_retained=True,executable_admission='NOT_GRANTED',explanation='No merged mechanism or generalized role rule is claimed; Cxx/rank never becomes advice.'))
 metrics=[r['metrics'] for r in results if isinstance(r['metrics'],dict)]
 totals={k:sum(m[k] for m in metrics) for k in ('requests','network_attempted','unknown_sends','failed_requests','input_tokens','output_tokens','usage_records','missing_usage_records','forced_actions','singleton_actions','commits','monitor_unassessable','monitor_errors','kernel_calls')}
 intervals=[r['send_interval'] for r in results];interval=[sum(x[i] for x in intervals) for i in (0,1)] if all(isinstance(x,list) for x in intervals) else 'UNKNOWN'
 strata=[]
 for slot,cap,jobs in [('r0',130,10),('r1',112,8)]:
  subset=[r for r in results if r['repeat_slot']==slot];sent=sum(r['metrics']['requests'] for r in subset if isinstance(r['metrics'],dict));assert sent<=cap
  strata.append(dict(slot=slot,registered_jobs=jobs,send_upper=cap,requests=sent,not_run=sum(r['status']=='NOT_RUN' for r in subset),technical_stops=sum(r['status']=='TECHNICAL_STOP' for r in subset)))
 assert totals['requests']<=242
 summary=dict(version='jm_c2_full_denominators_v1',registered_points=5,registered_jobs=18,initial_jobs=10,repeat_jobs=8,registered_pairs=9,registered_repeat_points=4,baseline_reexecuted=0,completed_jobs=sum(m['stable_complete'] for m in metrics),terminal_jobs=sum(r['status']=='TERMINATED' for r in results),technical_stops=sum(r['status']=='TECHNICAL_STOP' for r in results),not_run=sum(r['status']=='NOT_RUN' for r in results),invalid_saved_jobs=sum(r.get('saved_validation')=='FAIL' for r in results),pair_labels={label:sum(c['evaluation']['label_v2']==label for c in comparisons) for label in ('improved','degraded','neutral','trade_off','invalid','not_run')},valid_pairs=sum(c['evaluation']['comparison_valid'] for c in comparisons),invalid_or_not_run_pairs=sum(not c['evaluation']['comparison_valid'] for c in comparisons),confirmed_send_interval=interval,send_upper=242,strata=strata,totals=totals,model_cost_usd='UNKNOWN',cost_missing_not_zero=True,selected_task_variants=len({p['task_id'] for p in plan['points']}),selected_source_components=len({p['source_component'] for p in plan['points']}),training_source_orders=4,training_conservative_components=3,independent_unseen_sources=0,full_training_tasks=6,opening_covered_tasks=0,nonempty_covered_tasks=5,same_box_points=3,cross_box_points=2,coverage_status='PARTIAL_RETAINED_C1_GAPS',repeat_conflict_points=[p['point_id'] for p in point_summaries if p['repeat_conflict']],unrepeated_points=[p['point_id'] for p in point_summaries if not p['repeat_registered']])
 write(OUT/'branch_ledger.json',dict(version='jm_c2_branch_ledger_v1',jobs=results));write(OUT/'full_denominators.json',summary)
 write(OUT/'evidence_levels_and_conflicts.json',dict(version='jm_c2_evidence_levels_v1',points=point_summaries,families=families,rule='single PROVISIONAL_CASE; registered repeat direction一致 with no contrary valid result permits REPLICATED_LOCAL_OBSERVATION; labels differing retained as conflict; neither grants execution eligibility',same_start_repeats_are_independent_sources=False))
 complete=len(results)==18 and all(r['status']!='NOT_RUN' and r['technical_valid'] and r.get('saved_validation')=='PASS' for r in results)
 ready=dict(version='jm_c2_experience_input_readiness_v1',engineering_status='COMPLETE_IN_DECLARED_SCOPE' if complete else 'PARTIAL_TECHNICAL_STOP',fact_material_status='READY_LOCAL_FACTS_WITH_LIMITATIONS' if summary['valid_pairs'] else 'NOT_READY',positive_local_input_families=[f['family_id'] for f in families if f['positive_loading_proposal_input']],families=families,cross_start_generalized_experience='NOT_READY_NO_CROSS_START_CLAIM_SUPPORT',executable_experience='NOT_GRANTED',JM2_real_generation_authorized=0,JM2_started=False,independent_QA='PENDING',next_stage_admission='INDEPENDENT_QA_ONLY',scope='source-specific local factual inputs, all negatives/neutrals/conflicts retained; no finished T/E, no model generation',limitations=['synthetic packaging limits; feasibility UNKNOWN','exposed source variants and repeats are not independent unseen sources','fixed continuation policy does not fix stochastic choices','predicted static instability only; strict internal-force/hull/degenerate unassessability boundaries retained','no global optimum or causal mechanism claim'])
 write(OUT/'experience_input_readiness.json',ready)
 write(OUT/'saved_validation_receipt.json',dict(version='jm_c2_saved_validation_v1',jobs=validations,source_files=len(source_manifest()),frozen_source_unchanged=True,dispatch_guards=['transport','episode','candidate_pools_search_choose','commit_physical','monitor','exact_kernel','linprog'],verification='v13.validate_saved_execution and saved state/ledger/journal audit; no resend/replay/monitor recomputation',real_calls=0,LP=0))
 write(OUT/'training_fork_dataset_receipt.json',dict(version='jm_c2_training_fork_dataset_v1',plan='JM-plan-v2',authorization=ref(OUT/'authorization_receipt.json'),fork_plan=ref(C1/'fork_plan.json'),presend_identity=ref(OUT/'presend_identity_receipt.json'),source_manifest=ref(B2/'source_manifest.json'),ledger=ref(OUT/'branch_ledger.json'),denominators=ref(OUT/'full_denominators.json'),evidence=ref(OUT/'evidence_levels_and_conflicts.json'),experience_input=ref(OUT/'experience_input_readiness.json'),engineering_status=ready['engineering_status'],evidence_readiness=ready['fact_material_status'],research_result='LOCAL_OBSERVATIONS_ONLY_NO_GENERAL_BENEFIT_ESTABLISHED',next_stage_admission='INDEPENDENT_QA_ONLY',stop=True))
 print(json.dumps(summary,ensure_ascii=False))
if __name__=='__main__':main()
