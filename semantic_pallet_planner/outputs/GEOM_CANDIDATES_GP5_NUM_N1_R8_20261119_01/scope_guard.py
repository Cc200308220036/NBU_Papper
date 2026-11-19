"""Test-only pre-dispatch authority. No production plan/schema modifications."""
import hashlib,json
from pathlib import Path
UNIT='GP5_NUM_N1_R8_MINIMAL_NEW_SOURCE_RECOVERY_REVALIDATION'
SOURCE='8a860eea3ec22f8805eb6767660301acfd526653f566b1b1bd3e42b4af53578f'
ALLOWED=[{'job_id':j,'task_id':'GP5_SYNTH_K02_INT','backend':b,'method':'local_first_test_double'} for j,b in [('J01','e2_original_v1'),('J03','ems_surface_hybrid_v1')]]
LIMITS={'E':4,'R':2,'R_COMMIT':4,'X_H':1,'TOTAL_MONITOR':7}
def require(value,code):
    if not value:raise ValueError(code)
def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
class Guard:
    def __init__(self,plan):
        require(plan['source_identity']==SOURCE,'SOURCE_IDENTITY_MISMATCH')
        self.plan=plan;self.used={k:0 for k in LIMITS};self.per_job={}
        for job in ALLOWED:
            require([v for v in plan['jobs'] if v['job_id']==job['job_id']]==[job],'ALLOWLIST_IDENTITY_MISMATCH')
    def jobs(self):return [dict(j) for j in ALLOWED]
    def validate_job(self,job):require(job in ALLOWED,'OUT_OF_SCOPE_JOB')
    def reserve(self,group,job):
        require(group in ('E','R','R_COMMIT','X_H'),'UNKNOWN_GROUP')
        if group=='X_H':require(job=='H_v16','OUT_OF_SCOPE_H_JOB')
        else:require(job in ('J01','J03'),'OUT_OF_SCOPE_JOB')
        require(self.used[group]<LIMITS[group],'BUDGET_WOULD_EXCEED')
        if group!='R_COMMIT':require(self.used['TOTAL_MONITOR']<7,'TOTAL_BUDGET_WOULD_EXCEED')
        key=(group,job);cap={'E':2,'R':1,'R_COMMIT':2,'X_H':1}[group]
        require(self.per_job.get(key,0)<cap,'JOB_BUDGET_WOULD_EXCEED')
        self.used[group]+=1;self.per_job[key]=self.per_job.get(key,0)+1
        if group!='R_COMMIT':self.used['TOTAL_MONITOR']+=1

def validate_authorization(auth,inputs,output):
    require(auth.get('unit')==UNIT and auth.get('explicit_user_assignment') is True,'EXPLICIT_EXECUTION_AUTHORIZATION_REQUIRED')
    require(auth.get('independent_allowance_confirmed') is True,'INDEPENDENT_ALLOWANCE_REQUIRED')
    require(auth.get('limits')==LIMITS and auth.get('allowed_jobs')==ALLOWED,'SCOPE_OR_ALLOWANCE_MISMATCH')
    require(auth.get('source_identity')==SOURCE,'SOURCE_IDENTITY_MISMATCH')
    require(auth.get('input_freeze_sha256')==sha(inputs/'frozen_identity.json'),'FREEZE_MISMATCH')
    freeze=json.loads((inputs/'frozen_identity.json').read_bytes())
    require(str(output)==str(Path(freeze['run_root']).resolve()) and auth.get('run_root')==freeze['run_root'],'RUN_ROOT_MISMATCH')
    require(not output.exists(),'FRESH_ROOT_REQUIRED')
