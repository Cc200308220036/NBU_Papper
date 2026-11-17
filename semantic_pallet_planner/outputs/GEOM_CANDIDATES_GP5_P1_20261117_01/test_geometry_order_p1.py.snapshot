"""GP5 P1: fixed synthetic loops and explicit monitor TEST_DOUBLE; real calls=0."""
import copy
from contextlib import contextmanager,ExitStack
from dataclasses import asdict
import json
import os
from pathlib import Path
import socket
import tempfile
import unittest
from unittest.mock import patch

from semantic_pallet_planner.jev_select import episode,execution,evaluation
from semantic_pallet_planner.jev_select.contracts import canonical,digest,JevSelectError,validate_schema
from semantic_pallet_planner.jev_select import packaging_geometry_protocol as p
from semantic_pallet_planner.jev_select import geometry_order_execution as o
from semantic_pallet_planner.jev_select.packaging_runtime import LocalPackagingDouble,METHODS
from semantic_pallet_planner.jev_select.stability import monitor
from semantic_pallet_planner.jev_select.stability.exact_contracts import ExactConfig,ExactResult
from semantic_pallet_planner.jev_select.geometry_order_meter import CallBudget
from semantic_pallet_planner.jev_select.stability.monitor import seal_checkpoint

METADATA=Path('semantic_pallet_planner/outputs/GEOM_CANDIDATES_GP3_N3_20261117_01/cases/ems_surface_hybrid_v1_stable/config.json')
SNAP=json.loads(METADATA.read_bytes())['stability_monitor']
BACKENDS=('e2_original_v1','ems_surface_hybrid_v1')

class Cut(BaseException):pass

def adapted(case='K01'):
 raw=canonical(p.synthetic_task(case)).encode();return p.adapt_task(raw,origin='SYNTHETIC_FIXED',expected_sha256=p.sha(raw))

def development(case='K01'):
 t=adapted(case);plan=p.prepare_order_plan([t],data_identity=digest('GP5_SYNTHETIC_ONLY'),scope=p.DEVELOPMENT)
 adm={'version':'geometry_development_binding_v1','scope':p.DEVELOPMENT,'evidence':'TEST_DOUBLE','plan_digest':digest(plan)}
 return t,plan,adm

@contextmanager
def monitor_double(calls,status='STABLE'):
 def interface(algorithm):
  assert algorithm=='pct_exact_pose_network_v3'
  def assess(state,box,cfg):
   calls.append({'state':asdict(state),'box':asdict(box),'evidence':'TEST_DOUBLE'})
   return ExactResult(status=status,reason_code='TEST_DOUBLE_'+status,state_digest=digest(asdict(state)),
    candidate_digest=digest(asdict(box)),candidate_id=box.item_id,config_digest=digest(asdict(cfg)),
    algorithm_identity=copy.deepcopy(SNAP['algorithm_identity']),baseline_status='NOT_ASSESSED',first_bad_prefix=None,
    failed_item_id=None,height_delta_mm=None,evaluated_pose=None,kernel_calls=0,diagnostics={'TEST_DOUBLE':True,'actual_PCT_LP_calls':0})
  assess.geometry_test_double=True
  return assess,lambda:ExactConfig(**SNAP['kernel_config']),ExactResult,'stability_result_v3.schema.json'
 with patch.object(monitor,'kernel_interface',side_effect=interface):yield


class OrderP1(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
  self.evidence=Path(os.environ['GP5_P1_EVIDENCE']) if os.environ.get('GP5_P1_EVIDENCE') else None
  self.calls=[];self.cps=[]
  # Every accidental real call fails before invocation. Freezer functions also forbidden.
  stack=ExitStack();self.addCleanup(stack.close)
  for name in ('exact_adapter.assess_candidate','balance_adapter.assess_candidate','balance_network.solve_network','balance_network.linprog','monitor.exact_freeze','monitor.freeze'):
   stack.enter_context(patch('semantic_pallet_planner.jev_select.stability.'+name,side_effect=AssertionError('REAL_KERNEL_FREEZE_LP_FORBIDDEN')))
  stack.enter_context(patch.object(socket.socket,'connect',side_effect=AssertionError('NETWORK_FORBIDDEN')))
 def tearDown(self):
  if self.evidence:
   import shutil
   dest=self.evidence/self._testMethodName/'durable'
   shutil.copytree(self.tmp.name,dest,dirs_exist_ok=True)
   self.save('test_path_mapping.json',{'original_root':self.tmp.name,'archived_root':str(dest),
    'relocation':'original JSON and hashes preserved; resolve original temporary prefix via this map for inspection only',
    'evidence':'TEST_DOUBLE_OR_COUNTER_UNIT_TEST_NOT_REAL_RECEIPT'})
 def save(self,name,value):
  if self.evidence:
   path=self.evidence/self._testMethodName/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n')
 def setup_job(self,case='K01',index=0):
  t,plan,adm=development(case);job=plan['jobs'][index];cfg=o.load_order_config(plan,job['job_id'],monitor_snapshot=SNAP,admission=adm)
  store=o.OrderStore(Path(self.tmp.name)/str(index)/case,plan=plan,job_id=job['job_id'],adapted=t,monitor_snapshot=SNAP,admission=adm)
  self.save('inputs/'+case+'_'+job['job_id']+'/task.json',t['runtime'])
  self.save('inputs/'+case+'_'+job['job_id']+'/plan.json',plan)
  self.save('inputs/'+case+'_'+job['job_id']+'/config.json',cfg)
  self.save('inputs/'+case+'_'+job['job_id']+'/admission.json',adm)
  self.save('inputs/'+case+'_'+job['job_id']+'/identity.json',t['identity'])
  return t,plan,adm,job,cfg,store
 def runloop(self,case,*,resume=None,hook=None):
  t,plan,adm,job,cfg,store=case
  return episode.run_episode(t['runtime'],LocalPackagingDouble(job['method']),cfg,job_id=job['job_id'],method=job['method'],
      geometry_store=store,on_checkpoint=lambda cp:self.cps.append(copy.deepcopy(cp)),resume=resume,hook=hook)
 def test_two_backends_two_methods_complete_and_k02_exact_target(self):
  evidence=[]
  for index in range(4):
   case=self.setup_job('K02',index);self.cps=[];calls=[]
   with monitor_double(calls):out=self.runloop(case)
   self.save('diagnostic_job'+str(index)+'.json',out)
   self.assertEqual(out['summary']['placed_items'],2);self.assertTrue(out['summary']['completed'])
   self.assertEqual(len(calls),2)
   ev=[e for e in out['events'] if e['event']=='PLACE'];self.assertEqual(len(ev),2)
   for i,e in enumerate(ev):
    pose=e['action']['pose'] if 'pose' in e['action'] else e['proposed_action'].get('pose')
    chosen=next(c for c in e['bundle']['physical_candidates'] if c['candidate_id']==e['selection']['selected_candidate_id'])
    self.assertEqual(chosen['pose'],{'x_mm':0.0,'y_mm':0.0,'z_base_mm':60.0*i,'yaw_deg':0})
    self.assertIn(e['selection']['status'],('singleton','selected'))
    self.assertTrue(all(c['pose']==chosen['pose'] for c in e['bundle']['physical_candidates']),str([(c['pose'],c['oriented_size_mm']) for c in e['bundle']['physical_candidates']]))
   phases=[cp['phase'] for cp in self.cps]
   self.assertLess(phases.index('SELECTED'),phases.index('MONITORED'));self.assertLess(phases.index('MONITORED'),phases.index('COMMITTED'))
   metric=out['summary'];self.assertEqual(metric['fixed_container_utilization'],2/3);self.assertEqual(metric['envelope_utilization'],1)
   self.assertEqual(metric['counts'],{'assessment_entries':0,'solver_calls':0,'test_double_assessments':2})
   self.save('job'+str(index)+'/episode.json',out);self.save('job'+str(index)+'/phases.json',self.cps)
   self.save('job'+str(index)+'/config.json',case[4]);self.save('job'+str(index)+'/task.json',case[0]['runtime'])
   evidence.append({'backend':case[3]['backend'],'method':case[3]['method'],'target':[0,0,60],'pool_sizes':[len(e['bundle']['physical_candidates']) for e in ev],'actual_kernel':0,'monitor_evidence':'TEST_DOUBLE'})
  self.save('K02_reachability.json',evidence)
 def test_resume_selected_monitored_committed_no_duplicate_work(self):
  for i,(phase,hookname) in enumerate([('SELECTED','after_selected_checkpoint'),('MONITORED','after_monitored_checkpoint'),('COMMITTED','after_commit_checkpoint')]):
   case=self.setup_job(index=i);self.cps=[];calls=[]
   def hook(name,cp):
    if name==hookname:raise Cut()
   with monitor_double(calls),patch.object(execution,'commit_physical',wraps=execution.commit_physical) as commits:
    with self.assertRaises(Cut):self.runloop(case,hook=hook)
    cp=self.cps[-1];before=(len(calls),commits.call_count)
    with patch.object(LocalPackagingDouble,'select',side_effect=AssertionError('RESELECT')),patch('semantic_pallet_planner.jev_select.candidates.CandidateProvider.build',side_effect=AssertionError('REGENERATE')):
     out=self.runloop(case,resume=cp)
    self.assertEqual((len(calls)-before[0],commits.call_count-before[1]),(int(phase=='SELECTED'),int(phase!='COMMITTED')))
   self.save(phase+'/interrupted.json',cp);self.save(phase+'/resumed.json',out)
   self.save(phase+'/counts.json',{'before':before,'after':[len(calls),commits.call_count],'real_kernel':0})
 def test_stop_classification_failed_box_not_committed(self):
  rows=[]
  for index,(status,reason) in enumerate([('UNSTABLE','PREDICTED_STATIC_INSTABILITY'),('UNASSESSABLE','STABILITY_UNASSESSABLE'),('ERROR','STABILITY_MONITOR_ERROR')]):
   case=self.setup_job(index=index);calls=[]
   with monitor_double(calls,status):out=self.runloop(case)
   self.assertEqual(out['summary']['termination_reason'],reason);self.assertEqual(out['summary']['placed_items'],0)
   self.assertEqual(out['summary']['fixed_container_utilization'],0);self.assertIsNone(out['summary']['envelope_utilization'])
   self.assertEqual(out['events'][-1]['before'],out['events'][-1]['after'])
   before=len(calls)
   with monitor_double(calls,status),patch.object(LocalPackagingDouble,'select',side_effect=AssertionError('RETRY')):res=self.runloop(case,resume=out['checkpoint'])
   self.assertEqual(len(calls),before);rows.append({'status':status,'summary':out['summary']});self.save(status+'.json',out)
  self.save('classifications.json',rows)
 def test_commit_failure_and_committed_evaluation_recovery(self):
  for index,kind in enumerate(('commit','evaluation')):
   case=self.setup_job(index=index);calls=[];original=evaluation.evaluate_committed_state
   def evaluate(state,*a,**kw):
    if state['placed_count']:raise ValueError('TEST_DOUBLE_EVALUATION_FAILURE')
    return original(state,*a,**kw)
   target='semantic_pallet_planner.jev_select.'+('execution.commit_physical' if kind=='commit' else 'evaluation.evaluate_committed_state')
   failure={'side_effect':ValueError('TEST_DOUBLE_COMMIT_FAILURE')} if kind=='commit' else {'side_effect':evaluate}
   with monitor_double(calls),patch(target,**failure):out=self.runloop(case)
   self.assertEqual(out['checkpoint']['phase'],'TERMINATED' if kind=='commit' else 'COMMITTED')
   self.save(kind+'/failure.json',out)
   with monitor_double(calls),patch.object(execution,'commit_physical',side_effect=AssertionError('RECOMMIT')),patch.object(LocalPackagingDouble,'select',side_effect=AssertionError('RESELECT')):
    res=self.runloop(case,resume=out['checkpoint'])
   self.assertEqual(res['summary']['placed_items'],int(kind=='evaluation'));self.assertEqual(len(calls),1);self.save(kind+'/resumed.json',res)
 def test_drift_scope_and_missing_blob_reject(self):
  case=self.setup_job();t,plan,adm,job,cfg,store=case
  def hook(name,cp):
   if name=='after_selected_checkpoint':raise Cut()
  with monitor_double(self.calls):
   with self.assertRaises(Cut):self.runloop(case,hook=hook)
  cp=self.cps[-1];negative=[]
  for field in ('plan_digest','admission_digest','generator_config_digest'):
   bad=copy.deepcopy(cfg);bad[field]='0'*64
   with self.assertRaises(JevSelectError):o.validate_order_request(t['runtime'],LocalPackagingDouble(),bad,METHODS[0],store,lambda cp:None)
   negative.append(field)
  for field in ('source_identity','data_identity','task_identity','monitor_identity'):
   bad=copy.deepcopy(cfg);bad['runtime_identity'][field]='0'*64
   with self.assertRaises(JevSelectError):o.validate_order_request(t['runtime'],LocalPackagingDouble(),bad,METHODS[0],store,lambda cp:None)
   negative.append(field)
  for key,value in [('candidate_backend',BACKENDS[1]),('execution_scope',p.ORDER)]:
   bad=copy.deepcopy(cfg);bad[key]=value
   with self.assertRaises(JevSelectError):o.validate_order_request(t['runtime'],LocalPackagingDouble(),bad,METHODS[0],store,lambda cp:None)
  badtask=copy.deepcopy(t['runtime']);badtask['items'][0]['mass_kg']=2
  with self.assertRaises(JevSelectError):o.validate_order_request(badtask,LocalPackagingDouble(),cfg,METHODS[0],store,lambda cp:None)
  for mutate in [lambda c:c['execution_binding'].update(scope=p.ORDER),lambda c:c['state']['container'].update(length_mm=100)]:
   bad=copy.deepcopy(cp);mutate(bad);seal_checkpoint(bad)
   with monitor_double([]),self.assertRaises(JevSelectError):self.runloop(case,resume=bad)
  path=store.root/'blobs'/cp['pending_event']['geometry_ref']['sha256'];raw=path.read_bytes()
  for data in (None,b'CORRUPT'):
   if data is None:path.unlink()
   else:path.write_bytes(data)
   with monitor_double([]),self.assertRaises(JevSelectError):self.runloop(case,resume=cp)
   path.write_bytes(raw)
  self.save('negative.json',{'mutations':negative+['backend','scope','task','execution_scope','state','missing_blob','corrupt_blob'],'result':'REJECTED'})
 def test_development_without_marked_monitor_and_event_limit_reject(self):
  case=self.setup_job()
  out=self.runloop(case)
  self.assertEqual(out['summary']['termination_reason'],'geometry_development_requires_test_monitor')
  self.assertEqual(out['summary']['placed_items'],0)
  t,plan,adm,j,c,s=case
  with self.assertRaisesRegex(JevSelectError,'geometry_order_no_event_limit'):
   episode.run_episode(t['runtime'],LocalPackagingDouble(),c,job_id=j['job_id'],method=j['method'],geometry_store=s,on_checkpoint=lambda cp:None,event_limit=4)
 def test_real_tasks_admin_adaptation_and_formal_gates_before_episode(self):
  root=Path('semantic_pallet_planner/outputs/DATA_JEV_PACKAGING_LOAD_20261102_02');manifest=json.loads((root/'delivery_manifest.json').read_bytes());tasks=[]
  for task_id in p.TASK_IDS:
   path=root/'tasks'/(task_id+'.json');tasks.append(p.adapt_task(path.read_bytes(),origin='EXPOSED_TRAIN',expected_sha256=manifest['tasks/'+path.name]))
  self.assertEqual([len(t['runtime']['items']) for t in tasks],[19,19])
  self.assertEqual(tasks[0]['identity']['source_group_id'],tasks[1]['identity']['source_group_id'])
  plan=p.prepare_order_plan(tasks,data_identity=json.loads((root/'manifest.json').read_bytes())['data_identity'])
  run=p.draft_run(plan);self.assertEqual(len(run['rows']),8);self.assertTrue(all(r['status']=='NOT_RUN' for r in run['rows']))
  dev={'version':'geometry_development_binding_v1','scope':p.DEVELOPMENT,'evidence':'TEST_DOUBLE','plan_digest':digest(plan)}
  with patch.object(episode,'run_episode',side_effect=AssertionError('REAL_TASK_EPISODE_FORBIDDEN')) as never:
   for admission in ({},dev):
    with self.assertRaises(JevSelectError):o.run_order_job(plan,'J00',tasks[0],monitor_snapshot=SNAP,admission=admission,root=self.tmp.name)
   frozen=copy.deepcopy(plan);frozen.update(status='FROZEN',call_ledger_path=str(Path(self.tmp.name)/'formal_counter.json'))
   def ref(name,doc):
    path=Path(self.tmp.name)/name;raw=canonical(doc).encode();path.write_bytes(raw);return {'path':str(path),'sha256':p.sha(raw)}
   approval={'scope':p.ORDER,'plan_digest':digest(frozen),'status':'APPROVED'}
   adm={'version':'geometry_order_admission_v1','scope':p.ORDER,'plan_digest':digest(frozen),
      'source_identity':frozen['source_identity'],'environment_digest':frozen['environment_digest'],'monitor_digest':digest(SNAP),
      'status':'APPROVED','authorization':ref('formal_auth.json',dict(approval,version='geometry_scope_authorization_v1')),
      'review':ref('formal_review.json',dict(approval,version='geometry_scope_review_v1'))}
   for kernel in (None,{'version':'geometry_development_binding_v1','evidence':'TEST_DOUBLE'}):
    with self.assertRaises(JevSelectError):o.run_order_job(frozen,'J00',tasks[0],monitor_snapshot=SNAP,admission=adm,kernel_receipt=kernel,root=self.tmp.name)
   self.assertEqual(never.call_count,0)
  self.save('identities.json',[t['identity'] for t in tasks]);self.save('plan_draft.json',plan);self.save('run_denominator.json',run)
 def test_separate_launch_and_real_receipt_no_circular_gate(self):
  t=adapted();plan=p.prepare_order_plan([t],data_identity=digest('ACCEPTANCE'),scope=p.ACCEPTANCE)
  plan.update(status='FROZEN',call_ledger_path=str(Path(self.tmp.name)/'counter.json'))
  def ref(name,value):
   path=Path(self.tmp.name)/name;raw=canonical(value).encode();path.write_bytes(raw);return {'path':str(path),'sha256':p.sha(raw)}
  # External approvals here are TEST fixtures to exercise validation only. No loop/real freeze.
  approved={'status':'APPROVED','scope':p.ACCEPTANCE,'plan_digest':digest(plan)}
  launch={'version':'geometry_kernel_launch_v1','scope':p.ACCEPTANCE,'plan_digest':digest(plan),
    'source_identity':plan['source_identity'],'environment_digest':plan['environment_digest'],'monitor_digest':digest(SNAP),
    'status':'APPROVED','authorization':ref('authorization.json',dict(approved,version='geometry_scope_authorization_v1')),'review':ref('review.json',dict(approved,version='geometry_scope_review_v1'))}
  p.validate_admission(plan,SNAP,launch)
  with self.assertRaises(JevSelectError):p.validate_admission(plan,SNAP,launch,{'TEST_DOUBLE':True})
  order=p.prepare_order_plan([adapted()],data_identity=digest('BAD_ORDER'),scope=p.DEVELOPMENT)
  with self.assertRaises(JevSelectError):p.validate_real_kernel_receipt({'version':'geometry_development_binding_v1'},order,SNAP)
  self.save('launch_validation.json',{'bootstrap_requires_final_receipt':False,'evidence':'TEST_FIXTURE_ONLY_NOT_REAL_PERMISSION','formal_test_double_receipt':'REJECTED'})
 def test_integer_multistep_type_conflict_is_preserved_technical_failure(self):
  case=self.setup_job('K02_INT',2)
  with monitor_double(self.calls):out=self.runloop(case)
  self.assertEqual(out['summary']['termination_reason'],'RUNTIME_INPUT_INVALID')
  self.assertEqual(out['summary']['placed_items'],1)
  self.assertEqual(out['summary']['termination_class'],'TECHNICAL_FAILURE')
  self.assertEqual(out['events'][-1]['before'],out['events'][-1]['after'])
  self.assertEqual(len(self.calls),1)
  self.save('integer_type_conflict.json',out)
  self.save('config.json',case[4]);self.save('task.json',case[0]['runtime'])
 def test_metrics_independent_arithmetic_and_complete_run_denominator(self):
  case=self.setup_job('K02');t,plan,adm,j,c,store=case
  # One 100x80x60 box over a 100x80x180 container, two planned 1kg boxes.
  state={'container':t['runtime']['container'],'arrival_count':2,'end_of_stream':True,'pending_items':[{}],
   'placed_items':[{'mass_kg':1,'oriented_size_mm':[100,80,60],'pose':{'x_mm':0,'y_mm':0,'z_base_mm':0,'yaw_deg':0}}]}
  row=o.order_metrics(t['runtime'],c,j['method'],state,[],'CANCELLED')
  self.assertEqual(row['placed_item_ratio'],.5);self.assertEqual(row['placed_volume_ratio'],.5)
  self.assertEqual(row['placed_mass_ratio'],.5);self.assertEqual(row['fixed_container_utilization'],1/3)
  self.assertEqual(row['envelope_utilization'],1);self.assertEqual(row['termination_class'],'CANCELLED')
  run=p.update_run(p.draft_run(plan),plan,j['job_id'],'CANCELLED',row)
  self.assertEqual(len(run['rows']),4);self.assertEqual(sum(r['status']=='NOT_RUN' for r in run['rows']),3)
  self.save('manual_metrics.json',row);self.save('denominator.json',run)

 def test_unknown_send_and_raw_identity_refuse_silent_retry(self):
  case=self.setup_job();t,plan,adm,j,c,store=case
  from semantic_pallet_planner.jev_select.selector import result
  def unknown(self,ctx,*,decision_id):return result(ctx,status='unknown_send',source='test_double',error='UNKNOWN_SEND')
  with monitor_double(self.calls),patch.object(LocalPackagingDouble,'select',unknown):out=self.runloop(case)
  self.assertEqual(out['summary']['termination_reason'],'UNKNOWN_SEND');self.assertEqual(self.calls,[])
  with monitor_double(self.calls),patch.object(LocalPackagingDouble,'select',side_effect=AssertionError('RETRY_UNKNOWN_SEND')):
   resumed=self.runloop(case,resume=out['checkpoint'])
  self.assertEqual(resumed['summary']['placed_items'],0)
  raw=t['raw']+b' '
  with self.assertRaises(JevSelectError):p.adapt_task(raw,origin='SYNTHETIC_FIXED',expected_sha256=t['identity']['raw_sha256'])
  changed=p.adapt_task(raw,origin='SYNTHETIC_FIXED',expected_sha256=p.sha(raw))
  self.assertNotEqual(changed['identity']['raw_sha256'],t['identity']['raw_sha256'])
  self.assertEqual(changed['identity']['normalized_digest'],t['identity']['normalized_digest'])
  self.assertEqual(changed['identity']['runtime_digest'],t['identity']['runtime_digest'])
  self.save('unknown_send.json',out);self.save('raw_identity.json',{'original':t['identity'],'whitespace_variant':changed['identity']})

 def test_public_driver_persists_full_denominator_and_refuses_duplicate_start(self):
  t,plan,adm=development('K02');root=Path(self.tmp.name)/'driver'
  with monitor_double(self.calls):out=o.run_order_job(plan,'J00',t,monitor_snapshot=SNAP,admission=adm,root=root)
  run=json.loads((root/'run.json').read_bytes())
  self.assertEqual(len(run['rows']),4);self.assertEqual([r['status'] for r in run['rows']],['COMPLETE','NOT_RUN','NOT_RUN','NOT_RUN'])
  self.assertTrue((root/'jobs/J00/record.json').is_file())
  self.assertEqual(out['summary']['placed_items'],2)
  with self.assertRaises(JevSelectError):o.run_order_job(plan,'J00',t,monitor_snapshot=SNAP,admission=adm,root=root)
  self.save('driver_run.json',run);self.save('driver_record.json',json.loads((root/'jobs/J00/record.json').read_bytes()))

 def test_independent_budget_counters_and_unknown_call_no_retry(self):
  plan={'assessment_limit':2,'solver_limit':3};path=Path(self.tmp.name)/'meter.json';b=CallBudget(path,plan)
  def fake_assess():
   for _ in range(3):b.call('solver_calls',lambda:None)
  b.call('assessment_entries',fake_assess)
  self.assertEqual(b.value['counts'],{'assessment_entries':1,'solver_calls':3,'test_double_assessments':0})
  with self.assertRaises(JevSelectError):b.call('solver_calls',lambda:None)
  # This test budget does not represent real kernel evidence.
  value=json.loads(path.read_bytes());value['calls'].append({'kind':'assessment_entries','state':'STARTED','index':4});path.write_text(json.dumps(value))
  with self.assertRaisesRegex(JevSelectError,'geometry_meter_unknown_call'):CallBudget(path,plan)
  self.save('budget_test.json',{'evidence':'COUNTER_UNIT_TEST_FAKE_CALLS','counts':b.value['counts'],'actual_kernel_and_LP':0,'unfinished':'REJECTED_NO_RETRY'})

if __name__=='__main__':unittest.main(verbosity=2)
