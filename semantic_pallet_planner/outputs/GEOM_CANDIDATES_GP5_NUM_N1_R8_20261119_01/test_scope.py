"""Pure scope/dispatch checks: callbacks are counters, no order/monitor execution."""
import copy,json,unittest
from pathlib import Path
from scope_guard import Guard,ALLOWED,LIMITS,SOURCE,UNIT,validate_authorization,sha
I=Path(__file__).resolve().parent
class ScopeTests(unittest.TestCase):
 def setUp(self):self.plan=json.loads((I/'plan.json').read_bytes());self.dispatched=[]
 def dispatch(self,g,job,group='E'):
  g.validate_job(job);g.reserve(group,job['job_id']);self.dispatched.append(job['job_id'])
 def test_exact_two_jobs(self):
  g=Guard(self.plan)
  for job in g.jobs():self.dispatch(g,job)
  self.assertEqual(self.dispatched,['J01','J03']);self.assertEqual(len(self.plan['jobs']),8)
 def test_other_six_rejected_before_dispatch(self):
  g=Guard(self.plan)
  for job in self.plan['jobs']:
   if job not in ALLOWED:
    with self.assertRaisesRegex(ValueError,'OUT_OF_SCOPE_JOB'):self.dispatch(g,job)
  self.assertEqual(self.dispatched,[]);self.assertEqual(g.used['E'],0)
 def test_wrong_and_missing_identity(self):
  for key in ('task_id','backend','method','job_id'):
   for missing in (False,True):
    p=copy.deepcopy(self.plan);job=p['jobs'][1]
    if missing:del job[key]
    else:job[key]='WRONG'
    with self.assertRaises((ValueError,KeyError)):Guard(p)
  p=copy.deepcopy(self.plan);p['source_identity']='0'*64
  with self.assertRaisesRegex(ValueError,'SOURCE_IDENTITY_MISMATCH'):Guard(p)
  self.assertEqual(self.dispatched,[])
 def test_quotas_pre_dispatch(self):
  for group,cap in [('E',2),('R',1),('R_COMMIT',2),('X_H',1)]:
   g=Guard(self.plan);job='H_v16' if group=='X_H' else 'J01'
   calls=[]
   def invoke():g.reserve(group,job);calls.append(True)
   for _ in range(cap):invoke()
   before=copy.deepcopy(g.used)
   with self.assertRaises(ValueError):invoke()
   self.assertEqual(len(calls),cap);self.assertEqual(g.used,before)
  g=Guard(self.plan)
  for group in ('E','R','R_COMMIT'):
   for job in ('J01','J03'):
    for _ in range({'E':2,'R':1,'R_COMMIT':2}[group]):g.reserve(group,job)
  g.reserve('X_H','H_v16');self.assertEqual(g.used,LIMITS)
  with self.assertRaises(ValueError):g.reserve('X_H','H_v16')
 def test_authorization_and_root_binding(self):
  freeze=json.loads((I/'frozen_identity.json').read_bytes());root=Path(freeze['run_root']).resolve()
  auth={'unit':UNIT,'explicit_user_assignment':True,'independent_allowance_confirmed':True,'limits':LIMITS,'allowed_jobs':ALLOWED,'source_identity':SOURCE,'input_freeze_sha256':sha(I/'frozen_identity.json'),'run_root':freeze['run_root']}
  # In-memory positive fixture is not an issued authorization receipt.
  validate_authorization(auth,I,root)
  for key,value in [('explicit_user_assignment',False),('independent_allowance_confirmed',False),('limits',{**LIMITS,'E':5}),('allowed_jobs',ALLOWED[:1]),('source_identity','0'*64),('input_freeze_sha256','0'*64),('run_root','/tmp/wrong')]:
   bad=copy.deepcopy(auth);bad[key]=value
   with self.assertRaises(ValueError):validate_authorization(bad,I,root)
  self.assertFalse(root.exists())
 def test_full_denominator_and_original_guards(self):
  from run_state import case_rows
  scope=json.loads((I/'validation_scope.json').read_bytes());rows=case_rows(scope)
  self.assertEqual(len(rows),35);self.assertEqual(len(scope['X_H_names']),15)
  from validation_entrypoint import check_frozen
  check_frozen(I)
if __name__=='__main__':unittest.main(verbosity=2)
