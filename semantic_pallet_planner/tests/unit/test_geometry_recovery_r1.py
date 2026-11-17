"""GP3_N3_R1_ONLY: hand fixtures and explicit fault/kernel TEST_DOUBLEs."""
import copy
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from test_geometry_execution_n3 import fixture,kernel_double,BACKENDS
from semantic_pallet_planner.jev_select import episode,evaluation,execution
from semantic_pallet_planner.jev_select.geometry_execution import GeometryStore,load_run_config,validate_saved_checkpoint,COMMIT_TECHNICAL_ERROR
from semantic_pallet_planner.jev_select.contracts import digest,JevSelectError
from semantic_pallet_planner.jev_select.packaging_runtime import LocalPackagingDouble
from semantic_pallet_planner.jev_select.stability.monitor import seal_checkpoint


def run(t,c,s,cp=None):
 return episode.run_episode(t,LocalPackagingDouble(),c,job_id='R1',method=c['selector'],geometry_store=s,on_checkpoint=lambda cp:None,resume=cp)

class RecoveryR1(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  cls.tmp=tempfile.TemporaryDirectory();cls.cases={};cls.negative=[]
  for kind,backend in [('evaluation',BACKENDS[0]),('commit',BACKENDS[1])]:
   store=GeometryStore(Path(cls.tmp.name)/kind);t=fixture();c=load_run_config(backend=backend,task=t,data_identity=digest('R1_UNIT_MANUAL'))
   original=evaluation.evaluate_committed_state
   def evaluate(*a,**kw):
    if a[0]['placed_count']:raise ValueError('TEST_DOUBLE_POST_COMMIT_EVALUATION')
    return original(*a,**kw)
   target='semantic_pallet_planner.jev_select.evaluation.evaluate_committed_state' if kind=='evaluation' else 'semantic_pallet_planner.jev_select.execution.commit_physical'
   opts={'side_effect':evaluate} if kind=='evaluation' else {'side_effect':JevSelectError('TEST_DOUBLE_COMMIT_BOUNDARY','before mutation')}
   with patch(target,**opts),kernel_double():result=run(t,c,store)
   cls.cases[kind]=(t,c,store,result)
 @classmethod
 def tearDownClass(cls):
  if os.environ.get('N3_R1_EVIDENCE'):
   p=Path(os.environ['N3_R1_EVIDENCE'])/'negative_checks.json';p.write_text(json.dumps(cls.negative,ensure_ascii=False,indent=2)+'\n')
  cls.tmp.cleanup()
 def check(self,cp,case):
  t,c,s,_=case;return validate_saved_checkpoint(cp,t,c,'R1',c['selector'],s)
 def test_evaluation_recovery_only_evaluates_and_accounts(self):
  t,c,s,r=self.cases['evaluation'];cp=r['checkpoint'];self.assertEqual(cp['phase'],'COMMITTED');self.assertEqual(cp['reason'],'EVALUATION_ERROR');self.assertIsNone(r['summary'])
  with patch('semantic_pallet_planner.jev_select.candidates.CandidateProvider.build',side_effect=AssertionError('regenerate')),patch.object(LocalPackagingDouble,'select',side_effect=AssertionError('reselect')),patch('semantic_pallet_planner.jev_select.stability.monitor.monitor_selected_action',side_effect=AssertionError('reassess')),patch.object(execution,'commit_physical',side_effect=AssertionError('recommit')),patch.object(evaluation,'evaluate_committed_state',wraps=evaluation.evaluate_committed_state) as ev:
   out=run(t,c,s,cp)
   self.assertEqual(ev.call_count,1)
  self.assertEqual(out['final_state'],r['final_state']);self.assertEqual(out['summary']['placed_items'],1)
  self.assertEqual(sum(e['event']=='PLACE' for e in out['events']),1)
 def test_commit_failure_is_terminal_unchanged_and_not_retried(self):
  t,c,s,r=self.cases['commit'];cp=r['checkpoint'];ev=cp['events'][-1]
  self.assertEqual(cp['reason'],COMMIT_TECHNICAL_ERROR);self.assertEqual(cp['phase'],'TERMINATED')
  self.assertEqual(ev['before'],ev['after']);self.assertEqual(ev['monitor']['status'],'STABLE');self.assertIsNone(ev['action'])
  for field in ('placed_items','placed_mass_kg','placed_item_ratio','placed_volume_ratio','placed_mass_ratio'):self.assertEqual(r['summary'][field],0)
  self.assertEqual(len(r['final_state']['pending_items']),1)
  with patch('semantic_pallet_planner.jev_select.candidates.CandidateProvider.build',side_effect=AssertionError('regenerate')),patch.object(LocalPackagingDouble,'select',side_effect=AssertionError('reselect')),patch('semantic_pallet_planner.jev_select.stability.monitor.monitor_selected_action',side_effect=AssertionError('reassess')),patch.object(execution,'commit_physical',side_effect=AssertionError('retry commit')):
   out=run(t,c,s,cp)
  self.assertEqual(out['final_state'],r['final_state']);self.assertEqual(out['summary'],r['summary'])
 def reject(self,kind,label,mutate):
  case=self.cases[kind];cp=copy.deepcopy(case[3]['checkpoint']);mutate(cp);seal_checkpoint(cp)
  with self.assertRaises((JevSelectError,ValueError)) as err:self.check(cp,case)
  self.negative.append({'case':kind,'mutation':label,'result':'REJECTED','error':str(err.exception)})
 def test_reason_error_event_phase_action_state_inconsistencies(self):
  variants=[('reason',lambda p:p.update(reason='ARBITRARY_ERROR')),('phase',lambda p:p.update(phase='TERMINATED')),('error_code',lambda p:p['pending_event']['error'].update(code='ARBITRARY_ERROR')),('missing_error',lambda p:p['pending_event'].update(error=None)),('event',lambda p:p['pending_event'].update(event='COMMIT_FAILURE')),('action',lambda p:p['pending_event'].update(action=None)),('pending_reason',lambda p:p['pending_event'].update(reason='EVALUATION_ERROR')),('business_after',lambda p:p['pending_event'].update(business_after={})),('reference_after',lambda p:p['pending_event'].update(reference_after={})),('state',lambda p:p.update(state=copy.deepcopy(p['pending_event']['before']))) ]
  for label,mutate in variants:self.reject('evaluation',label,mutate)
  variants=[('reason',lambda p:p.update(reason='ARBITRARY_ERROR')),('phase',lambda p:p.update(phase='READY')),('event',lambda p:p['events'][-1].update(event='STOP')),('missing_error',lambda p:p['events'][-1].update(error=None)),('error_code',lambda p:p['events'][-1]['error'].update(code='ARBITRARY_ERROR')),('action',lambda p:p['events'][-1].update(action=copy.deepcopy(p['events'][-1]['proposed_action']))),('state',lambda p:p['state'].update(placed_count=1)),('after',lambda p:p['events'][-1]['after'].update(placed_count=1))]
  for label,mutate in variants:self.reject('commit',label,mutate)
  def arbitrary(cp):
   cp['reason']='ARBITRARY_ERROR';cp['events'][-1]['reason']='ARBITRARY_ERROR';cp['events'][-1]['error']['code']='ARBITRARY_ERROR'
  self.reject('commit','all_error_strings_aligned_but_unknown',arbitrary)
 def test_empty_exception_detail_is_valid_not_an_error_category(self):
  for kind,case in self.cases.items():
   cp=copy.deepcopy(case[3]['checkpoint']);e=cp['pending_event'] if kind=='evaluation' else cp['events'][-1]
   e['error']['detail']='';seal_checkpoint(cp);self.check(cp,case)
 def test_blob_and_frozen_identity_drift_still_rejected(self):
  for kind,case in self.cases.items():
   t,c,s,r=case;cp=r['checkpoint'];ev=cp['pending_event'] if kind=='evaluation' else cp['events'][-1]
   path=s.root/'blobs'/ev['geometry_ref']['sha256'];raw=path.read_bytes()
   for replacement in (None,b'CORRUPT'):
    if replacement is None:path.unlink()
    else:path.write_bytes(replacement)
    with self.assertRaises(JevSelectError):self.check(cp,case)
    path.write_bytes(raw)
   for key in ('source_identity','monitor_identity','physical_identity','data_identity'):
    bad=copy.deepcopy(c);bad['runtime_identity'][key]='0'*64
    with self.assertRaises(JevSelectError):validate_saved_checkpoint(cp,t,bad,'R1',bad['selector'],s)
   self.reject(kind,'environment',lambda p:p['execution_binding'].update(environment_digest='0'*64))
   self.reject(kind,'config',lambda p:p.update(config_digest='0'*64))
   self.reject(kind,'task',lambda p:p.update(task_digest='0'*64))
   bad=copy.deepcopy(c);bad['numerical_profile']='unknown'
   with self.assertRaises(JevSelectError):validate_saved_checkpoint(cp,t,bad,'R1',bad['selector'],s)
 def test_pre_fix_checkpoint_not_resigned_for_new_source(self):
  root=Path('semantic_pallet_planner/outputs/GEOM_CANDIDATES_GP3_N3_R1_20261117_01/before')
  for d in root.iterdir():
   cp=json.loads((d/'failure_checkpoint.json').read_bytes());t=json.loads((d/'task.json').read_bytes());c=json.loads((d/'config.json').read_bytes());s=GeometryStore(d/'durable')
   before=digest(cp)
   with self.assertRaises(JevSelectError):run(t,c,s,cp)
   self.assertEqual(digest(cp),before)

if __name__=='__main__':unittest.main(verbosity=2)
