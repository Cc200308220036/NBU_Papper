"""Offline v17 gates; temporary synthetic approvals never exported or dispatched."""
import copy,json,tempfile,unittest,socket
from pathlib import Path
from contextlib import ExitStack
from unittest.mock import patch
from semantic_pallet_planner.jev_select import packaging_geometry_protocol as p,geometry_order_execution as order,geometry_order_meter as meter,geometry_kernel_completion as completion
from semantic_pallet_planner.jev_select.geometry_native_protocol import identity_fields,wire
from semantic_pallet_planner.jev_select.contracts import digest,canonical,JevSelectError
O=Path(__file__).resolve().parent
OBS=[];GAPS=[]
read=lambda f:json.loads(Path(f).read_bytes())
class Gates(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory(prefix='gp5_p2_offline_');self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
  self.plan=read(O/'acceptance_plan_DRAFT.json');self.snap=read(O/'monitor_metadata_READONLY_NOT_FROZEN.json')['snapshot']
  self.stack=ExitStack();self.addCleanup(self.stack.close)
  for target in ('stability.exact_adapter.assess_candidate','stability.balance_adapter.assess_candidate','stability.balance_network.solve_network','stability.balance_network.linprog','stability.monitor.freeze','stability.monitor.exact_freeze','episode.run_episode','candidates.CandidateProvider.build'):
   self.stack.enter_context(patch('semantic_pallet_planner.jev_select.'+target,side_effect=AssertionError('FORBIDDEN_REAL_OR_ORDER_CALL:'+target)))
  self.stack.enter_context(patch.object(socket.socket,'connect',side_effect=AssertionError('NETWORK_FORBIDDEN')))
 def ref(self,name,value):
  f=self.root/name;raw=canonical(value).encode();f.write_bytes(raw);return {'path':str(f),'sha256':p.sha(raw)}
 def fixture(self):
  # Structurally approved temporary fixture only, never exported or sent to a runner.
  plan=copy.deepcopy(self.plan);plan.update(status='FROZEN',call_ledger_path=str(self.root/'counter.json'))
  doc={**identity_fields(plan),'scope':p.ACCEPTANCE,'plan_digest':digest(plan),'status':'APPROVED'}
  auth={**doc,'version':wire(plan,'geometry_scope_authorization_v1')};review={**doc,'version':wire(plan,'geometry_scope_review_v1')}
  launch={**identity_fields(plan),'version':wire(plan,'geometry_kernel_launch_v1'),'scope':p.ACCEPTANCE,'plan_digest':digest(plan),'source_identity':plan['source_identity'],'environment_digest':plan['environment_digest'],'monitor_digest':digest(self.snap),'status':'APPROVED','authorization':self.ref('TEST_ONLY_authorization.json',auth),'review':self.ref('TEST_ONLY_review.json',review)}
  return plan,launch,auth,review
 def reject(self,label,fn,expected):
  try:fn()
  except JevSelectError as e:
   self.assertEqual(e.code,expected);OBS.append({'case':label,'type':type(e).__name__,'code':e.code,'status':'EXPECTED_REJECTION'})
  else:self.fail('EXPECTED_REJECTION_MISSING:'+label)
 def test_draft_public_entry_rejects_before_io(self):
  raw=(O/'K01_task.json').read_bytes();task=p.adapt_task(raw,origin='SYNTHETIC_FIXED',expected_sha256=p.sha(raw));dest=self.root/'MUST_NOT_EXIST'
  self.reject('DRAFT run_order_job',lambda:order.run_order_job(self.plan,'J00',task,monitor_snapshot=self.snap,admission={},root=dest),'geometry_order_draft_not_executable')
  self.assertFalse(dest.exists())
 def test_missing_and_mismatched_external_approvals(self):
  plan,launch,auth,review=self.fixture();p.validate_admission(plan,self.snap,launch)
  for key,doc in [('authorization',auth),('review',review)]:
   bad=copy.deepcopy(launch);bad[key]={'path':str(self.root/'ABSENT'),'sha256':'0'*64}
   self.reject('missing '+key,lambda:p.validate_admission(plan,self.snap,bad),'geometry_missing_receipt')
   changed=copy.deepcopy(doc);changed['plan_digest']='0'*64;bad=copy.deepcopy(launch);bad[key]=self.ref('wrong_'+key+'.json',changed)
   self.reject('mismatched '+key,lambda:p.validate_admission(plan,self.snap,bad),'geometry_external_approval')
  bad=copy.deepcopy(launch);del bad['review']
  self.reject('absent review field',lambda:p.validate_admission(plan,self.snap,bad),'invalid_geometry_kernel_launch_v2')
  bad=copy.deepcopy(launch);del bad['authorization']
  self.reject('absent authorization field',lambda:p.validate_admission(plan,self.snap,bad),'invalid_geometry_kernel_launch_v2')
 def test_identity_drift_and_launch_not_completion(self):
  plan,launch,_,_=self.fixture()
  for key in ('source_identity','environment_digest','monitor_digest','publication_policy_digest'):
   bad=copy.deepcopy(launch);bad[key]='0'*64
   self.reject('launch '+key,lambda:p.validate_admission(plan,self.snap,bad),'geometry_admission_binding')
  for key in ('source_identity','environment_digest'):
   bad=copy.deepcopy(plan);bad[key]='0'*64
   self.reject('plan '+key,lambda:p.validate_order_plan(bad),'geometry_order_plan_identity')
  self.reject('launch cannot consume own completion',lambda:p.validate_admission(plan,self.snap,launch,{'TEST_DOUBLE':True}),'geometry_launch_not_completion')
 def test_substitute_evidence_cannot_satisfy_real_completion(self):
  plan,launch,_,_=self.fixture();ref={'path':str(self.root/'NEVER_READ'),'sha256':'0'*64}
  receipt={**identity_fields(plan),'version':wire(plan,'geometry_real_kernel_receipt_v2'),'scope':p.ACCEPTANCE,'status':'ACCEPTED','source_identity':plan['source_identity'],'environment_digest':plan['environment_digest'],'monitor_digest':digest(self.snap),'launch':self.ref('TEST_ONLY_launch.json',launch),'acceptance_plan':self.ref('TEST_ONLY_plan.json',plan),'records':[ref],'counts':{'assessment_entries':1,'solver_calls':1,'test_double_assessments':1},'counter_log':ref,'review':ref,'recovery':[{**r,'before':ref,'after':ref,'accounting':ref} for r in completion.required_coverage(plan)['recovery']]}
  self.reject('marked substitute counts',lambda:p.validate_real_kernel_receipt(receipt,plan,self.snap),'geometry_real_counts')
  receipt['counts']['test_double_assessments']=0;receipt['counter_log']=self.ref('COUNTER_TEST.json',{'evidence':'COUNTER_TEST','plan_digest':digest(plan),'counts':receipt['counts']})
  self.reject('counter fixture not real evidence',lambda:p.validate_real_kernel_receipt(receipt,plan,self.snap),'geometry_real_counter_log')
  archived=read(Path('semantic_pallet_planner/outputs/GEOM_CANDIDATES_GP5_NUM_N1_R8_R1_RUN_20261119_01/E/jobs/J01/record.json'))
  self.reject('historical substitute record not completion receipt',lambda:p.validate_real_kernel_receipt(archived,plan,self.snap),'invalid_geometry_real_kernel_receipt_v3')
 def test_counter_reservations_caps_unknown_and_forwarding(self):
  plan={'assessment_limit':1,'solver_limit':2};path=self.root/'COUNTER_TEST.json';b=meter.CallBudget(path,plan)
  called=[]
  def fake(kind,*args,**kw):
   persisted=read(path);self.assertEqual(persisted['calls'][-1]['state'],'STARTED');self.assertEqual(persisted['calls'][-1]['kind'],kind);called.append(kind);return args,kw
  self.assertEqual(b.call('assessment_entries',fake,'assessment_entries',7,x=8),((7,),{'x':8}))
  self.assertEqual(b.value['counts'],{'assessment_entries':1,'solver_calls':0,'test_double_assessments':0})
  b.call('solver_calls',fake,'solver_calls');b.call('solver_calls',fake,'solver_calls')
  for kind in ('assessment_entries','solver_calls'):
   before=len(called);self.reject('cap '+kind,lambda:b.call(kind,fake,kind),'geometry_'+kind+'_budget_exhausted');self.assertEqual(before,len(called))
  doc=read(path);doc['calls'][-1]['state']='STARTED';path.write_text(json.dumps(doc))
  self.reject('STARTED no retry',lambda:meter.CallBudget(path,plan),'geometry_meter_unknown_call')
  doc['calls'][-1]['state']='DONE';doc['counts']['solver_calls']=1;path.write_text(json.dumps(doc))
  self.reject('counter drift',lambda:meter.CallBudget(path,plan),'geometry_meter_count_drift')
 def test_meter_wrapper_only_fake_targets(self):
  from semantic_pallet_planner.jev_select.stability import exact_adapter,balance_network
  plan,launch,_,_=self.fixture();original=object()
  def fake_solver(*a,**kw):return original
  def fake_assess(*a,**kw):
   self.assertIs(balance_network.linprog('OFFLINE_ONLY',x=3),original);return original
  with patch.object(exact_adapter,'assess_candidate',side_effect=fake_assess),patch.object(balance_network,'linprog',side_effect=fake_solver):
   with meter.metered_run(plan,job_id='J00',monitor_snapshot=self.snap,admission=launch) as b:
    self.assertIs(exact_adapter.assess_candidate('OFFLINE_ONLY'),original)
    self.assertEqual(meter.current_increment(digest(plan)),{'assessment_entries':1,'solver_calls':1,'test_double_assessments':0})
    self.assertEqual([r['kind'] for r in b.value['calls']],['assessment_entries','solver_calls'])
  # REAL_KERNEL label in the temporary wrapper ledger is a fixture; it is deleted.
  OBS.append({'case':'metered_run forwarding','status':'PASS_FAKE_TARGETS_ONLY','actual_assessment':0,'actual_LP':0,'temporary_ledger_exported':False})
 def test_external_policy_identity_probe(self):
  plan,launch,auth,review=self.fixture()
  for key,doc in [('authorization',auth),('review',review)]:
   bad=copy.deepcopy(doc);bad['publication_policy_digest']='0'*64;trial=copy.deepcopy(launch);trial[key]=self.ref('policy_'+key+'.json',bad)
   try:p.validate_admission(plan,self.snap,trial)
   except JevSelectError as e:OBS.append({'case':'external policy '+key,'code':e.code,'status':'REJECTED'})
   else:GAPS.append({'id':'P2-PREP-EXTERNAL-POLICY-01','document':key,'observed':'wrong publication_policy_digest accepted when schema valid and plan_digest matches','scope':'plan and launch current source/policy are still checked; external document redundant policy field not cross-checked','suggestion':'QA decide whether require identity_fields(plan) equality for both external docs; no production change in this task'})
 def test_required_coverage_and_existing_completion_pure_contract(self):
  coverage=completion.required_coverage(self.plan);self.assertEqual(len(coverage['primary']),4);self.assertEqual(len(coverage['recovery']),6)
  from test_geometry_order_r1 import Remediation
  case=Remediation('test_completion_contract_missing_duplicate_error_only_no_commit_recovery');case.tmp=type('T',(),{'name':str(self.root)})();case.evidence=None;captured={};case.save=lambda n,v:captured.update({n:v})
  case.test_completion_contract_missing_duplicate_error_only_no_commit_recovery()
  self.assertEqual(len(captured['completion_contract_results.json']['negative']),9)
  OBS.append({'case':'existing completion pure contract','coverage_version':'v16 original regression; current v17 coverage independently checked','negative_cases':captured['completion_contract_results.json']['negative'],'genuine_record_callback':'NOOP_COVERAGE_TEST_ONLY_NOT_REAL_EVIDENCE'})
if __name__=='__main__':
 suite=unittest.defaultTestLoader.loadTestsFromTestCase(Gates);result=unittest.TextTestRunner(verbosity=2,failfast=True).run(suite)
 (O/'pure_results.json').write_text(json.dumps({'status':'PASS' if result.wasSuccessful() else 'FAIL','methods_run':result.testsRun,'failures':[(str(t),s) for t,s in result.failures],'errors':[(str(t),s) for t,s in result.errors],'observations':OBS,'contract_gaps':GAPS,'all_fixture_files':'TEMPORARY_DELETED','valid_approvals_issued':0,'actual_real_assessment':0,'actual_LP':0,'actual_freeze':0,'actual_order_or_resume_dispatch':0},ensure_ascii=False,indent=2)+'\n')
 raise SystemExit(not result.wasSuccessful())
