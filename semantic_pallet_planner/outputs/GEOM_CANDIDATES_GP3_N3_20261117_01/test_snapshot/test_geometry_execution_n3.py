"""Manual one-box public-loop phases; kernel TEST_DOUBLE, actual PCT/LP=0."""
import copy
from contextlib import contextmanager
from dataclasses import asdict
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from semantic_pallet_planner.jev_select import episode
from semantic_pallet_planner.jev_select.geometry_execution import GeometryStore,load_run_config
from semantic_pallet_planner.jev_select.contracts import digest,canonical,JevSelectError
from semantic_pallet_planner.jev_select.packaging_runtime import LocalPackagingDouble,METHODS
from semantic_pallet_planner.jev_select.tests.unit.test_packaging_runtime import mechanism_task,item
from semantic_pallet_planner.jev_select.stability import monitor
from semantic_pallet_planner.jev_select.stability.exact_contracts import ExactResult,load_config
from semantic_pallet_planner.jev_select.stability.exact_adapter import algorithm_identity

BACKENDS=('e2_original_v1','ems_surface_hybrid_v1')

def fixture(singleton=False):
 t=mechanism_task([item('manual_box',size=(100,100,100))])
 t={k:v for k,v in t.items() if k in {'container','items','attributes','instruction_text','regions','reference_policy','task_id','mode','layer','feasibility_status'}}
 t.update(version='jev_geometry_fixture_task_v1',fixture_only=True)
 if singleton:
  t['items'][0]['dimensions_mm']['width']=80
  t['container'].update(length_mm=100,width_mm=80,max_height_mm=100)
 return t

class Cut(RuntimeError):pass

@contextmanager
def kernel_double(status='STABLE',calls=None):
 original=monitor.kernel_interface
 def interface(algorithm):
  assert algorithm=='pct_exact_pose_network_v3'
  def assess(state,box,cfg):
   if calls is not None:calls.append({'selected_box':asdict(box),'state':asdict(state),'TEST_DOUBLE':True})
   return ExactResult(status=status,reason_code='TEST_DOUBLE_'+status,state_digest=digest(asdict(state)),
    candidate_digest=digest(asdict(box)),candidate_id=box.item_id,config_digest=digest(asdict(cfg)),
    algorithm_identity=algorithm_identity(),baseline_status='NOT_ASSESSED',first_bad_prefix=None,failed_item_id=None,
    height_delta_mm=None,evaluated_pose=None,kernel_calls=0,diagnostics={'TEST_DOUBLE':True,'actual_PCT_LP_calls':0})
  _,loader,result,schema=original(algorithm)
  return assess,loader,result,schema
 with patch.object(monitor,'kernel_interface',side_effect=interface):yield

class ExecutionN3(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
  self.store=GeometryStore(self.tmp.name);self.cps=[]
  # Forbidden real kernels are assertion sentinels, never substitutes for success.
  for target in ('semantic_pallet_planner.jev_select.stability.exact_adapter.assess_candidate',
                 'semantic_pallet_planner.jev_select.stability.balance_adapter.assess_candidate',
                 'semantic_pallet_planner.jev_select.stability.balance_network.solve_network'):
   guard=patch(target,side_effect=AssertionError('REAL_PCT_LP_FORBIDDEN'));guard.start();self.addCleanup(guard.stop)
 def cfg(self,backend=BACKENDS[0],**kw):
  t=kw.pop('task',fixture());return t,load_run_config(backend=backend,task=t,data_identity=digest('N3_MANUAL_ONLY'),**kw)
 def runloop(self,t,c,**kw):
  return episode.run_episode(t,LocalPackagingDouble(c['selector']),c,job_id='MANUAL',method=c['selector'],geometry_store=self.store,on_checkpoint=lambda cp:self.cps.append(copy.deepcopy(cp)),**kw)
 def save(self,name,value):
  if os.environ.get('N3_EVIDENCE'):
   p=Path(os.environ['N3_EVIDENCE'])/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n')
 def archive(self,name,out,t,c):
  if os.environ.get('N3_EVIDENCE'):
   import shutil
   p=Path(os.environ['N3_EVIDENCE'])/'cases'/name
   shutil.copytree(self.store.root,p/'durable',dirs_exist_ok=True)
   for n,v in [('result',out),('task',t),('config',c),('phases',self.cps)]:self.save('cases/'+name+'/'+n+'.json',v)
 def test_two_backends_two_local_methods_stable_and_atomic_order(self):
  for backend,method in zip(BACKENDS,METHODS):
   with self.subTest(backend=backend):
    self.cps=[];t,c=self.cfg(backend,method=method);calls=[]
    with kernel_double(calls=calls):out=self.runloop(t,c)
    self.assertEqual(out['summary']['placed_items'],1)
    self.assertEqual(out['summary']['monitor_evidence'],'TEST_DOUBLE')
    self.assertEqual(len(calls),1)
    phases=[cp['phase'] for cp in self.cps]
    self.assertLess(phases.index('SELECTED'),phases.index('MONITORED'));self.assertLess(phases.index('MONITORED'),phases.index('COMMITTED'))
    ev=next(e for e in out['events'] if e['event']=='PLACE')
    self.store.load_event(ev,c)
    self.archive(backend+'_stable',out,t,c)
 def test_monitor_stops_and_singleton_share_exact_action_path(self):
  for status,reason in [('UNSTABLE','PREDICTED_STATIC_INSTABILITY'),('UNASSESSABLE','STABILITY_UNASSESSABLE'),('ERROR','STABILITY_MONITOR_ERROR'),('DISABLED','GEOMETRY_MONITOR_DISABLED')]:
   self.cps=[];t,c=self.cfg(task=fixture(True),enabled=status!='DISABLED');calls=[]
   with kernel_double(status,calls):out=self.runloop(t,c)
   self.assertEqual(out['summary']['termination_reason'],reason)
   self.assertEqual(out['summary']['placed_items'],0);self.assertEqual(out['summary']['placed_mass_kg'],0)
   ev=out['events'][-1];self.assertEqual(ev['before'],ev['after']);self.assertEqual(len(out['final_state']['pending_items']),1)
   self.assertEqual(ev['selection']['status'],'singleton');self.assertIsNone(ev['action'])
   self.assertEqual(len(calls),int(status!='DISABLED'));self.archive(status,out,t,c)
   with kernel_double(status,calls),patch.object(LocalPackagingDouble,'select',side_effect=AssertionError('terminal reselected')):
    resumed=self.runloop(t,c,resume=out['checkpoint'])
   self.assertEqual(resumed['final_state'],out['final_state']);self.assertEqual(len(calls),int(status!='DISABLED'))
 def test_phase_resume_no_reselect_no_reassess_no_recommit(self):
  from semantic_pallet_planner.jev_select.execution import commit_physical
  for backend,phase,hook_name in [(BACKENDS[0],'SELECTED','after_selected_checkpoint'),(BACKENDS[1],'MONITORED','after_monitored_checkpoint'),(BACKENDS[1],'COMMITTED','after_commit_checkpoint')]:
   self.cps=[];t,c=self.cfg(backend);calls=[]
   def hook(name,cp):
    if name==hook_name:raise Cut(phase)
   with kernel_double(calls=calls),patch('semantic_pallet_planner.jev_select.execution.commit_physical',wraps=commit_physical) as commits:
    with self.assertRaises(Cut):self.runloop(t,c,hook=hook)
    cp=copy.deepcopy(self.cps[-1]);self.assertEqual(cp['phase'],phase)
    self.save('resume/'+phase+'_interrupted.json',cp)
    before_calls=len(calls);before_commits=commits.call_count
    with patch.object(LocalPackagingDouble,'select',side_effect=AssertionError('reselected')),patch('semantic_pallet_planner.jev_select.candidates.CandidateProvider.build',side_effect=AssertionError('regenerated')):
     out=self.runloop(t,c,resume=cp)
    self.assertEqual(len(calls)-before_calls,int(phase=='SELECTED'))
    self.assertEqual(commits.call_count-before_commits,int(phase!='COMMITTED'))
   self.assertEqual(out['summary']['placed_items'],1);self.archive('resume_'+phase,out,t,c)
 def test_missing_and_corrupted_blob_and_identity_drift_reject(self):
  t,c=self.cfg();
  def hook(name,cp):
   if name=='after_selected_checkpoint':raise Cut()
  with kernel_double():
   with self.assertRaises(Cut):self.runloop(t,c,hook=hook)
  cp=self.cps[-1];ev=cp['pending_event'];path=self.store.root/'blobs'/ev['geometry_ref']['sha256'];raw=path.read_bytes()
  for data in (None,b'corrupt'):
   if data is None:path.unlink()
   else:path.write_bytes(data)
   with self.assertRaises(JevSelectError):self.runloop(t,c,resume=cp)
   path.write_bytes(raw)
  # Delete each inner raw-byte blob, not only the sidecar manifest.
  decision_blob=self.store.get_json(ev['geometry_ref']);input_blob=self.store.get_json(decision_blob['input'])
  for key in ('native','geometry'):
   p=self.store.root/'blobs'/input_blob[key]['sha256'];data=p.read_bytes();p.unlink()
   with self.assertRaises(JevSelectError):self.runloop(t,c,resume=cp)
   p.write_bytes(data)
  for field in ('config_digest','task_digest'):
   bad=copy.deepcopy(cp);bad[field]='0'*64;monitor.seal_checkpoint(bad)
   with self.assertRaises(JevSelectError):self.runloop(t,c,resume=bad)
  bad=copy.deepcopy(cp);bad['execution_binding']['environment_digest']='0'*64;monitor.seal_checkpoint(bad)
  with self.assertRaises(JevSelectError):self.runloop(t,c,resume=bad)
  other=load_run_config(backend=BACKENDS[0],task=t,data_identity=digest('N3_OTHER_DATA'))
  with self.assertRaises(JevSelectError):self.runloop(t,other,resume=cp)
  for identity in ('source_identity','physical_identity','monitor_identity'):
   bad=copy.deepcopy(c);bad['runtime_identity'][identity]='0'*64
   with self.assertRaises(JevSelectError):self.runloop(t,bad,resume=cp)
  bad=copy.deepcopy(cp);bad['state']['container']['length_mm']+=1;monitor.seal_checkpoint(bad)
  with self.assertRaises(JevSelectError):self.runloop(t,c,resume=bad)
  bad=copy.deepcopy(c);bad['numerical_profile']='unknown'
  with self.assertRaises(JevSelectError):self.runloop(t,bad,resume=cp)
  self.save('drift_checks.json',{'missing_blob':'REJECTED','corrupt_bytes':'REJECTED','config_task_environment_profile':'REJECTED','TEST_DOUBLE':True})
 def test_persistence_failure_precedes_generation_selection_monitor(self):
  t,c=self.cfg()
  with patch.object(self.store,'put',side_effect=OSError('TEST_DOUBLE_STORAGE_FAILURE')),patch('semantic_pallet_planner.jev_select.candidates.CandidateProvider.build',side_effect=AssertionError('generation before durable input')):
   with self.assertRaises(OSError):self.runloop(t,c)
  self.assertFalse(any(cp['phase'] in ('SELECTED','MONITORED','COMMITTED') for cp in self.cps))
 def test_unknown_send_stops_without_retry(self):
  from semantic_pallet_planner.jev_select.selector import result
  t,c=self.cfg()
  def unknown(self,ctx,*,decision_id):return result(ctx,status='unknown_send',source='test_double',error='UNKNOWN_SEND')
  with patch.object(LocalPackagingDouble,'select',unknown),kernel_double(calls=[]) as unused:
   out=self.runloop(t,c)
  self.assertEqual(out['summary']['placed_items'],0);self.assertEqual(out['summary']['termination_reason'],'UNKNOWN_SEND')
  self.archive('UNKNOWN_SEND',out,t,c)
  with patch.object(LocalPackagingDouble,'select',side_effect=AssertionError('implicit retry')):
   resumed=self.runloop(t,c,resume=out['checkpoint'])
  self.assertEqual(resumed['summary']['termination_reason'],'UNKNOWN_SEND')

 def test_real_normal_empty_and_common_input_error_are_distinct(self):
  for invalid in (False,True):
   t=fixture();t['items'][0]['dimensions_mm']['length']=2000
   if invalid:t['items'][0]['mass_kg']=2**53+1
   t,c=self.cfg(task=t)
   with kernel_double(calls=[]):out=self.runloop(t,c)
   expected='RUNTIME_NUMBER_UNREPRESENTABLE' if invalid else 'STOP_NO_PHYSICAL_CANDIDATE'
   self.assertEqual(out['summary']['termination_reason'],expected)
   self.assertEqual(out['summary']['placed_items'],0)
   self.archive('numeric_error' if invalid else 'normal_empty',out,t,c)
   self.runloop(t,c,resume=out['checkpoint'])

 def test_v15_cross_backend_still_rejects_and_missing_execution_binding(self):
  from semantic_pallet_planner.jev_select.candidates import PublicBusinessGuard
  from semantic_pallet_planner.jev_select.packaging_runtime import no_policy
  from semantic_pallet_planner.jev_select.execution import commit_physical
  from semantic_pallet_planner.jev_select.candidate_backends import GeometryCandidateBundle
  from semantic_pallet_planner.jev_select.contracts import DecisionContext
  from semantic_pallet_planner.jev_select.selector import SelectionResult
  t,c=self.cfg()
  def hook(name,cp):
   if name=='after_monitored_checkpoint':raise Cut()
  with kernel_double():
   with self.assertRaises(Cut):self.runloop(t,c,hook=hook)
  cp=self.cps[-1];ev=cp['pending_event'];b=self.store.load_event(ev,c)
  other=load_run_config(backend=BACKENDS[1],task=t,data_identity=digest('N3_MANUAL_ONLY'))
  with self.assertRaises(JevSelectError) as error:PublicBusinessGuard().filter(ev['observation'],no_policy(ev['observation']),b,other)
  self.assertEqual(error.exception.code,'geometry_config_bundle_mismatch')
  with self.assertRaises(JevSelectError):commit_physical(cp['state'],[],ev['observation'],b,DecisionContext.from_dict(ev['context']),SelectionResult.from_dict(ev['selection']),c,monitor=ev['monitor'],monitor_event=ev)

 def test_backend_error_is_persisted_without_empty_pool_or_fallback(self):
  from semantic_pallet_planner.jev_select.candidate_backends import GeometryConstructionError
  t,c=self.cfg(BACKENDS[1]);error=GeometryConstructionError('BACKEND_INTERNAL_ERROR','PHYSICAL_CHECK_DISAGREEMENT','TEST_DOUBLE_GENERATION_ERROR',{'TEST_DOUBLE':True})
  with patch('semantic_pallet_planner.jev_select.candidates.CandidateProvider.build',side_effect=error) as generator,kernel_double(calls=[]):
   out=self.runloop(t,c)
  self.assertEqual(generator.call_count,1)
  self.assertEqual(out['summary']['termination_reason'],'PHYSICAL_CHECK_DISAGREEMENT')
  ev=out['events'][-1];self.assertIsNone(ev['bundle']);self.assertEqual(ev['before'],ev['after'])
  self.assertTrue(ev['geometry_ref']);self.store.get_json(ev['geometry_ref'])
  self.archive('generation_ERROR_TEST_DOUBLE',out,t,c)
  self.runloop(t,c,resume=out['checkpoint'])

 def test_selected_checkpoint_save_failure_prevents_monitor_and_commit(self):
  from semantic_pallet_planner.jev_select.execution import commit_physical
  t,c=self.cfg();calls=[];original=self.store.save_checkpoint
  def save(cp):
   if cp['phase']=='SELECTED':raise OSError('TEST_DOUBLE_SELECTED_SAVE_FAILURE')
   return original(cp)
  with patch.object(self.store,'save_checkpoint',side_effect=save),kernel_double(calls=calls),patch('semantic_pallet_planner.jev_select.execution.commit_physical',wraps=commit_physical) as commits:
   with self.assertRaises(OSError):self.runloop(t,c)
   self.assertEqual(calls,[]);self.assertEqual(commits.call_count,0)

if __name__=='__main__':unittest.main(verbosity=2)
