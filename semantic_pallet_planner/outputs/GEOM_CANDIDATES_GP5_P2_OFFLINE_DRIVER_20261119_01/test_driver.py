"""OFFLINE TEST DOUBLE evidence only; no real runner/kernel/freezer calls."""
import copy,json,socket,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import driver as d
class DriverTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
  self.plan=d.read(d.R/'acceptance_plan_FROZEN.json');self.plan['call_ledger_path']=str(self.root/'ledger.json')
  self.jobs=self.plan['jobs'];self.calls=[];self.saved={}
  self.addCleanup(patch.stopall)
  patch.object(d,'check_success').start()
 def fixture(self):return self.plan,{}, {},{j['task_id']:{} for j in self.jobs},[{}]*4
 def fake(self,plan,jid,task,*,root,resume,on_checkpoint,hook,**kw):
  self.calls.append((jid,resume['phase'] if resume else 'FRESH',str(root)))
  root=Path(root);root.mkdir(parents=True,exist_ok=True)
  if hook:
   phase=d.PHASES[0] if resume is None else d.PHASES[d.PHASES.index(resume['phase'])+1]
   cp={'phase':phase,'job_id':jid,'pending_event':{'selection':'OFFLINE_SELECTION','proposed_action':'ARCHIVED_TEST_ONLY','monitor':{'result_digest':'SAVED_RESULT'} if phase!='SELECTED' else None}}
   d.write(root/'durable.json',cp);on_checkpoint(cp)
   hook({'SELECTED':'after_selected_checkpoint','MONITORED':'after_monitored_checkpoint','COMMITTED':'after_commit_checkpoint'}[phase],cp)
  ph=resume['phase'] if resume else None
  delta={'selector_calls':0,'singleton_executions':0,'monitor_entries':int(ph=='SELECTED'),'monitor_reuses':int(ph=='MONITORED'),'commit_successes':int(ph!='COMMITTED'),'commit_attempts':int(ph!='COMMITTED')}
  if ph=='MONITORED':self.assertEqual(resume['pending_event']['monitor']['result_digest'],'SAVED_RESULT')
  d.write(root/'jobs'/jid/'record.json',{})
  return {'checkpoint':{'events':[{'selection':'OFFLINE_SELECTION','proposed_action':'ARCHIVED_TEST_ONLY','monitor':{'result_digest':'SAVED_RESULT'}}]},'summary':{'completed':True,'accounting':{'invocation_delta':delta}}}
 def test_full_4_plus_6_and_phases(self):
  counts={'assessment_entries':0,'solver_calls':0,'test_double_assessments':0}
  def counter(plan):
   if self.calls and self.calls[-1][1]=='SELECTED' and '/recovery/' in self.calls[-1][2] and self.calls[-1] not in self.saved:
    counts['assessment_entries']+=1;self.saved[self.calls[-1]]=True
   return copy.deepcopy(counts)
  with patch.object(d,'prepare',side_effect=lambda *a:self.fixture()),patch.object(d.order,'run_order_job',side_effect=self.fake),patch.object(d,'check_counts',side_effect=counter),patch.object(socket.socket,'connect',side_effect=AssertionError('NETWORK')):
   d.execute(d.R,'TEST_ONLY','TEST_ONLY',self.root/'run')
  receipt=d.read(self.root/'run/driver_receipt.json')
  self.assertEqual(len(receipt['rows']),10);self.assertTrue(all(r['status']=='COMPLETE' for r in receipt['rows']))
  self.assertEqual([(j,ph) for j,ph,r in self.calls if '/recovery/' in r],[(j,ph) for j in ('J00','J01') for ph in d.PHASES])
  for j in ('J00','J01'):
   for ph in d.PHASES:self.assertTrue((self.root/'run/saved'/j/ph/'durable.json').exists())
 def test_missing_records_stops_before_dispatch(self):
  with patch.object(d.order,'run_order_job',side_effect=AssertionError('DISPATCH_FORBIDDEN')) as run:
   with self.assertRaises(FileNotFoundError):d.execute(d.R,self.root/'missing_review',self.root/'missing_launch',self.root/'run')
  run.assert_not_called();self.assertTrue(all(r['status']=='NOT_RUN' for r in d.read(self.root/'run/driver_receipt.json')['rows']))
 def test_missing_launch_after_review_stops(self):
  review=self.root/'review';d.write(review,{})
  with patch.object(d.order,'run_order_job') as run:
   with self.assertRaises(FileNotFoundError):d.execute(d.R,review,self.root/'missing_launch',self.root/'run')
  run.assert_not_called()
 def test_bad_launch_version_and_review_digest(self):
  from semantic_pallet_planner.jev_select.geometry_native_protocol import identity_fields,wire
  from semantic_pallet_planner.jev_select.contracts import canonical,JevSelectError
  plan=d.read(d.R/'acceptance_plan_FROZEN.json');snap=d.read(d.R/'monitor_snapshot.json')
  doc={**identity_fields(plan),'scope':plan['scope'],'plan_digest':d.digest(plan),'status':'APPROVED'}
  review={**doc,'version':wire(plan,'geometry_scope_review_v1')}
  auth={**doc,'version':wire(plan,'geometry_scope_authorization_v1')}
  def ref(name,value):
   path=self.root/name;path.write_text(canonical(value));return {'path':str(path),'sha256':d.p.sha(path.read_bytes())}
  launch={**identity_fields(plan),'version':wire(plan,'geometry_kernel_launch_v1'),'scope':plan['scope'],'plan_digest':d.digest(plan),'source_identity':plan['source_identity'],'environment_digest':plan['environment_digest'],'monitor_digest':d.digest(snap),'status':'APPROVED','authorization':ref('auth',auth),'review':ref('review',review)}
  with patch.object(d.p,'validate_order_plan'):
   d.p.validate_admission(plan,snap,launch)
   bad=copy.deepcopy(launch);bad['version']='INVALID'
   with self.assertRaises(JevSelectError):d.p.validate_admission(plan,snap,bad)
   bad=copy.deepcopy(launch);bad['review']['sha256']='0'*64
   with self.assertRaises(JevSelectError):d.p.validate_admission(plan,snap,bad)
 def test_identity_drift_stops_before_dispatch(self):
  runtime=self.root/'runtime';runtime.mkdir()
  for name in ('acceptance_plan_FROZEN.json','monitor_snapshot.json','startup_review_request.json'):(runtime/name).write_bytes((d.R/name).read_bytes())
  req=d.read(runtime/'startup_review_request.json');req['plan_digest']='0'*64;d.write(runtime/'startup_review_request.json',req)
  with patch.object(d.order,'run_order_job') as run:
   with self.assertRaises(AssertionError):d.execute(runtime,'unused','unused',self.root/'run')
  run.assert_not_called()
 def test_first_failure_keeps_remaining_not_run(self):
  with patch.object(d,'prepare',side_effect=lambda *a:self.fixture()),patch.object(d,'check_counts',return_value={}),patch.object(d.order,'run_order_job',side_effect=RuntimeError('OFFLINE_FAILURE')) as run:
   with self.assertRaises(RuntimeError):d.execute(d.R,'fixture','fixture',self.root/'run')
  self.assertEqual(run.call_count,1);rows=d.read(self.root/'run/driver_receipt.json')['rows'];self.assertEqual(rows[0]['status'],'FAILED');self.assertEqual(sum(r['status']=='NOT_RUN' for r in rows),9)
 def test_joint_preflight_failure_prevents_dispatch(self):
  # Isolate only external/native validation; exercise the driver's four-config barrier.
  review=self.root/'review';launch=self.root/'launch';d.write(review,{});d.write(launch,{'review':{'path':str(review),'sha256':'fixture'}})
  with patch.object(d.p,'read_reference',return_value={}),patch.object(d.p,'validate_admission'),patch.object(d.order,'load_order_config',side_effect=[{}, {}, RuntimeError('J02_PREFLIGHT_FAIL')]) as cfg,patch.object(d.order,'run_order_job') as run:
   with self.assertRaisesRegex(RuntimeError,'J02'):d.execute(d.R,review,launch,self.root/'run')
  self.assertEqual(cfg.call_count,3);run.assert_not_called()
 def test_unknown_overlimit_and_counter_drift(self):
  plan=self.plan;path=Path(plan['call_ledger_path'])
  value={'evidence':'REAL_KERNEL','plan_digest':d.digest(plan),'limits':{'assessment_entries':8,'solver_calls':128},'counts':{'assessment_entries':0,'solver_calls':0,'test_double_assessments':0},'calls':[]}
  for change in ('unknown','overlimit','drift'):
   v=copy.deepcopy(value)
   if change=='unknown':v['calls']=[{'state':'STARTED','kind':'solver_calls'}]
   elif change=='overlimit':v['counts']['assessment_entries']=9
   else:v['plan_digest']='bad'
   d.write(path,v)
   with self.assertRaises(AssertionError):d.check_counts(plan)
if __name__=='__main__':unittest.main(verbosity=2)
