"""R1 fixed synthetic/contract tests only; all real dispatches forbidden."""
import copy,json
from pathlib import Path
from unittest.mock import patch
from test_geometry_order_p1 import OrderP1,monitor_double,Cut,development,SNAP
from semantic_pallet_planner.jev_select import geometry_order_execution as o
from semantic_pallet_planner.jev_select import geometry_kernel_completion as c
from semantic_pallet_planner.jev_select.contracts import validate_schema,JevSelectError,digest
from semantic_pallet_planner.jev_select.packaging_geometry_protocol import sha

# Inherit guards and evidence archival, not the P1 test methods.
class R1(OrderP1):
 pass
for name in list(dir(OrderP1)):
 if name.startswith('test_'):setattr(R1,name,None)

class Remediation(R1):
 def test_accounted_driver_and_recovery(self):
  for index,phase in enumerate(('SELECTED','MONITORED','COMMITTED')):
   t,plan,adm=development();job=plan['jobs'][1];root=Path(self.tmp.name)/phase;cps=[];calls=[]
   def cut(name,cp):
    if name=={'SELECTED':'after_selected_checkpoint','MONITORED':'after_monitored_checkpoint','COMMITTED':'after_commit_checkpoint'}[phase]:raise Cut()
   with monitor_double(calls):
    with self.assertRaises(Cut):o.run_order_job(plan,job['job_id'],t,monitor_snapshot=SNAP,admission=adm,root=root,on_checkpoint=lambda cp:cps.append(cp),hook=cut)
    out=o.run_order_job(plan,job['job_id'],t,monitor_snapshot=SNAP,admission=adm,root=root,resume=cps[-1])
   a=out['summary']['accounting'];expected={'selector_calls':0,'singleton_executions':0,'monitor_entries':int(phase=='SELECTED'),'monitor_reuses':int(phase=='MONITORED'),'commit_attempts':int(phase!='COMMITTED'),'commit_successes':int(phase!='COMMITTED')}
   self.assertEqual(a['invocation_delta'],expected);self.assertEqual(a['cumulative']['commit_successes'],1)
   self.assertTrue(out['summary']['completed']);self.save(phase+'/accounted_result.json',out)
 def test_k01_local_first_targets_and_k02_singleton_counts(self):
  for index in (1,3):
   case=self.setup_job(index=index)
   with monitor_double([]):out=self.runloop(case)
   event=next(e for e in out['events'] if e.get('selection'));chosen=next(x for x in event['bundle']['physical_candidates'] if x['candidate_id']==event['selection']['selected_candidate_id'])
   self.save('K01_target_'+case[3]['backend']+'.json',chosen)
  t,plan,adm=development('K02');root=Path(self.tmp.name)/'accounted'
  with monitor_double([]):out=o.run_order_job(plan,plan['jobs'][1]['job_id'],t,monitor_snapshot=SNAP,admission=adm,root=root)
  a=out['summary']['accounting'];self.assertEqual(a['cumulative'],{'selector_calls':1,'singleton_executions':1,'monitor_entries':2,'monitor_reuses':0,'commit_attempts':2,'commit_successes':2})
  self.assertEqual(a['cumulative'],a['invocation_delta']);self.save('K02_accounted.json',out)
 def test_nested_unknown_and_saved_legal_contracts(self):
  source=Path('semantic_pallet_planner/outputs/GEOM_CANDIDATES_GP5_P1_20261117_01/final_evidence/test_two_backends_two_methods_complete_and_k02_exact_target/job0/phases.json')
  cps=json.loads(source.read_bytes())
  for cp in cps:validate_schema('checkpoint_v16',cp)
  terminal=cps[-1]
  mutations=[['state','container'],['state','attributes','synth_1'],['state','placed_items',0],['events',0,'after','pending_items',0,'item']]
  placed=next(i for i,e in enumerate(terminal['events']) if e.get('selection'))
  mutations += [['events',placed,k] for k in ('observation','bundle','context','selection','proposed_action')]
  mutations += [['events',placed,'monitor','result'],['events',placed,'monitor','result','diagnostics'],['events',placed,'monitor','binding','runtime_identity'],['events',placed,'business_after','raw'],['events',placed,'business_after','runtime_facts','synth_1']]
  for path in mutations:
   cp=copy.deepcopy(terminal);node=cp
   for k in path:node=node[k]
   node['UNRECOGNIZED_R1']=True
   with self.assertRaises(JevSelectError,msg=str(path)):validate_schema('checkpoint_v16',cp)
  diagnostic=copy.deepcopy(terminal)
  diagnostic['events'][placed]['monitor']['result']['diagnostics']['raw_solver_vector']=['nan','inf','-inf']
  validate_schema('checkpoint_v16',diagnostic)  # structure-only, not a valid signed monitor
  diagnostic['events'][placed]['monitor']['result']['diagnostics']['raw_solver_vector']=['UNRECOGNIZED']
  with self.assertRaises(JevSelectError):validate_schema('checkpoint_v16',diagnostic)
  for phase in ('SELECTED','MONITORED','COMMITTED'):
   cp=copy.deepcopy(next(c for c in cps if c['phase']==phase));cp['pending_event']['context']['UNRECOGNIZED_R1']=1
   with self.assertRaises(JevSelectError):validate_schema('checkpoint_v16',cp)
  self.save('nested_schema_results.json',{'legal_checkpoints':len(cps),'rejected_paths':mutations})
 def test_completion_contract_missing_duplicate_error_only_no_commit_recovery(self):
  # Contract-only fabricated small summaries, no genuine receipt or kernel execution.
  from semantic_pallet_planner.jev_select.packaging_geometry_protocol import prepare_order_plan,ACCEPTANCE
  from test_geometry_order_p1 import adapted
  plan=prepare_order_plan([adapted('K01'),adapted('K02')],data_identity=digest('CONTRACT_ONLY'),scope=ACCEPTANCE)
  coverage=c.required_coverage(plan)
  def check_record(row):
   es=[];state={'placed_items':[],'end_of_stream':True,'pending_items':[]}
   for i,pose in enumerate(row['poses']):
    before=copy.deepcopy(state);state['placed_items'].append({'item_id':str(i)})
    es.append({'event':'PLACE','bundle':{'physical_candidates':[{'candidate_id':str(i),'pose':pose,'oriented_size_mm':([100,80,60] if pose['yaw_deg']==0 else [80,100,60])}]},'selection':{'selected_candidate_id':str(i)},'action':{'id':str(i)},'proposed_action':{'id':str(i)},'monitor':{'status':'STABLE','result':{'status':'STABLE'},'result_digest':digest('CONTRACT_ONLY')},'before':before,'after':copy.deepcopy(state)})
   return {'checkpoint':{'job_id':row['job_id'],'method':'local_first_test_double','phase':'TERMINATED','reason':'ALL_ITEMS_PLACED','state':state,'events':es},'config':{'order_task_identity':{'task_id':row['task_id']},'candidate_backend':row['backend'],'selector':'local_first_test_double'}}
  records=[check_record(r) for r in coverage['primary']];docs={};serial=0
  def ref(v):
   nonlocal serial
   serial+=1;path=Path(self.tmp.name)/('contract_'+str(serial)+'.json');raw=json.dumps(v).encode();path.write_bytes(raw);return {'path':str(path),'sha256':sha(raw)}
  receipt={'records':[ref(r) for r in records],'recovery':[],'counter_log':ref({'TEST_CONTRACT':True})}
  for r in coverage['recovery']:
   record=records[next(i for i,x in enumerate(coverage['primary']) if x['job_id']==r['job_id'])];before=copy.deepcopy(record['checkpoint']);before.update(phase=r['phase'],pending_event=copy.deepcopy(before['events'][-1]))
   delta={'selector_calls':0,'singleton_executions':0,'monitor_entries':int(r['phase']=='SELECTED'),'monitor_reuses':int(r['phase']=='MONITORED'),'commit_attempts':int(r['phase']!='COMMITTED'),'commit_successes':int(r['phase']!='COMMITTED')}
   account={'version':'geometry_order_accounting_v1','plan_digest':digest(plan),'job_id':r['job_id'],'config_digest':digest(record['config']),'invocations':[{'index':0,'resume_phase':r['phase'],'status':'RETURNED','delta':delta,'resume_checkpoint_digest':digest(before),'result_checkpoint_digest':digest(record['checkpoint'])}],'cumulative':delta}
   receipt['recovery'].append({**r,'before':ref(before),'after':ref(record),'accounting':ref(account)})
  calls=[]
  for row in coverage['primary']:
   for kind,n in [('assessment_entries',len(row['poses'])+int(row['task_id'].endswith('K01'))),('solver_calls',1)]:
    for _ in range(n):calls.append({'kind':kind,'state':'DONE','job_id':row['job_id'],'index':len(calls)})
  log={'calls':calls}
  def review(v):
   v['review']=ref({'version':'geometry_kernel_completion_review_v1','scope':ACCEPTANCE,'status':'APPROVED','acceptance_plan_digest':digest(plan),'records_digest':digest(v['records']),'recovery_digest':digest(v['recovery']),'counter_log':v['counter_log'],'coverage_digest':digest(coverage)})
  review(receipt)
  # Callback deliberately does no genuine validation: this tests coverage only.
  c.validate_completion(receipt,plan,log,lambda r:None)
  outcomes=[]
  for name in ('missing','duplicate','missing_recovery','technical_stop','only_error','no_commit','wrong_pose','no_recovery_commit','wrong_review'):
   v=copy.deepcopy(receipt);l=copy.deepcopy(log)
   if name=='missing':v['records'].pop()
   if name=='duplicate':v['records'][1]=v['records'][0]
   if name=='missing_recovery':v['recovery'].pop()
   if name in ('technical_stop','only_error','no_commit','wrong_pose'):
    r=copy.deepcopy(records[0]);cp=r['checkpoint']
    if name=='technical_stop':cp['reason']='GEOMETRY_COMMIT_TECHNICAL_ERROR'
    if name=='only_error':cp['events'][0]['monitor']['status']='ERROR';l['calls'][0]['state']='ERROR'
    if name=='no_commit':cp['events'][0]['event']='STOP'
    if name=='wrong_pose':cp['events'][0]['bundle']['physical_candidates'][0]['pose']['z_base_mm']=1
    v['records'][0]=ref(r)
   if name=='no_recovery_commit':
    a=json.loads(Path(v['recovery'][0]['accounting']['path']).read_bytes());a['invocations'][0]['delta']['commit_successes']=0;v['recovery'][0]['accounting']=ref(a)
   if name!='wrong_review':review(v)
   else:v['records'].reverse()
   with self.assertRaises((JevSelectError,KeyError),msg=name):c.validate_completion(v,plan,l,lambda r:None)
   outcomes.append({'case':name,'result':'REJECTED','evidence':'PURE_CONTRACT_NOT_REAL_RECEIPT'})
  # Old completion and test doubles never satisfy production v2 gate.
  with self.assertRaises(JevSelectError):validate_schema('geometry_real_kernel_receipt_v2',{'version':'geometry_real_kernel_receipt_v1'})
  self.save('completion_contract_results.json',{'positive':'PURE_COVERAGE_ONLY','negative':outcomes,'coverage':coverage,'business_dispatch':0})
 def test_accounting_failure_unknown_and_kernel_increment(self):
  from semantic_pallet_planner.jev_select.geometry_order_accounting import invocation,tick,completed,snapshot
  from semantic_pallet_planner.jev_select import geometry_order_meter as meter
  case=self.setup_job();cfg=case[4];path=Path(self.tmp.name)/'pure_account.json'
  self.assertIsNone(snapshot(cfg)['cumulative'])
  with self.assertRaises(RuntimeError):
   with invocation(path,cfg,'J00',None):tick(cfg,'selector_calls');raise RuntimeError('TEST_CONTRACT')
  doc=json.loads(path.read_bytes());self.assertEqual(doc['cumulative']['selector_calls'],1);self.assertEqual(doc['invocations'][-1]['status'],'ERROR')
  doc['invocations'][-1]['status']='STARTED';path.write_text(json.dumps(doc))
  with self.assertRaisesRegex(JevSelectError,'unknown_dispatch'):
   with invocation(path,cfg,'J00',{'phase':'SELECTED'}):pass
  with self.assertRaisesRegex(JevSelectError,'missing_history'):
   with invocation(path.with_name('absent.json'),cfg,'J00',{'phase':'SELECTED'}):pass
  plan={'assessment_limit':4,'solver_limit':5};ledger=Path(self.tmp.name)/'COUNTER_TEST.json'
  budget=meter.CallBudget(ledger,plan,job_id='J00');budget.call('assessment_entries',lambda:None)
  budget=meter.CallBudget(ledger,plan,job_id='J00');token=meter._ACTIVE.set(budget)
  try:
   self.assertEqual(meter.current_counts(digest(plan))['assessment_entries'],1);self.assertEqual(meter.current_increment(digest(plan))['assessment_entries'],0)
   budget.call('assessment_entries',lambda:None);self.assertEqual(meter.current_increment(digest(plan))['assessment_entries'],1)
  finally:meter._ACTIVE.reset(token)
  self.save('accounting_failure_results.json',{'unknown':'REJECTED','missing':'REJECTED','failed_selector_calls':1,'meter':'COUNTER_TEST_FAKE_FUNCTION_ONLY','actual_kernel_calls':0})
 def test_error_monitor_and_commit_failure_accounting(self):
  from semantic_pallet_planner.jev_select import execution
  for kind in ('ERROR','COMMIT_FAILURE'):
   t,plan,adm=development();root=Path(self.tmp.name)/kind;job=plan['jobs'][1]
   with monitor_double([],status='ERROR' if kind=='ERROR' else 'STABLE'):
    if kind=='COMMIT_FAILURE':
     with patch.object(execution,'commit_physical',side_effect=ValueError('TEST_COMMIT_ERROR')):out=o.run_order_job(plan,job['job_id'],t,monitor_snapshot=SNAP,admission=adm,root=root)
    else:out=o.run_order_job(plan,job['job_id'],t,monitor_snapshot=SNAP,admission=adm,root=root)
   a=out['summary']['accounting']['cumulative'];self.assertEqual(a['monitor_entries'],1);self.assertEqual(a['commit_successes'],0);self.assertEqual(a['commit_attempts'],int(kind=='COMMIT_FAILURE'));self.assertEqual(out['summary']['placed_items'],0)
   self.save(kind+'/accounted_failure.json',out)
