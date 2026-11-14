"""Independent P1-C QA: saved bytes/counts plus reviewed verify-only worker.
Never calls prepare/run/hold-lock/probe, solver, candidate generation or order.
"""
import collections,hashlib,json,os,subprocess
from pathlib import Path
Q=Path(__file__).parent;D=Path('PCT/outputs/PCT_P1_C_20261114_01')
def read(p):return json.loads(Path(p).read_text())
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def dg(x):return hashlib.sha256(json.dumps(x,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()
def logical(x):
 if isinstance(x,dict):return {k:logical(v) for k,v in x.items() if k not in ('timings','duration_s','result_digest','credential_digest')}
 if isinstance(x,list):return [logical(v) for v in x]
 return x
def calls(root):return [json.loads(s) for s in (root/'calls.jsonl').read_text().splitlines()]
def main():
 manifest=read(D/'delivery_manifest.json');identity=read(D/'identity.json')
 mismatch=[e['path'] for e in manifest['files'] if sha(e['path'])!=e['sha256']]
 drift=[p for p,h in identity['source_configuration_schema_sha256'].items() if sha(p)!=h]
 assert not mismatch and not drift,(mismatch,drift)
 comparisons=read(D/'attempt_02/cross_process_comparisons.json');assert len(comparisons)==12
 checks=[];jobs=[]
 for scenario in ('stable','unstable','stub_unstable'):
  baseline=D/'attempt_02'/('baseline_'+scenario);jobs.append(baseline);ref=read(baseline/'episode.json')
  expected=dict(collections.Counter(x['role'] for x in calls(baseline)))
  for phase in ('DECISION_READY','SELECTED','MONITORED','COMMITTED'):
   root=D/'attempt_02'/(scenario+'_'+phase);jobs.append(root);ep=read(root/'episode.json');log=calls(root)
   count=dict(collections.Counter(x['role'] for x in log));assert count==expected
   assert ep['final_state']==ref['final_state'] and ep['summary']['loading']==ref['summary']['loading']
   assert logical(ep['events'])==logical(ref['events'])
   row=next(r for r in comparisons if r['scenario']==scenario and r['phase']==phase)
   assert row['actual_cross_process_role_counts']==count==row['baseline_counts'] and row['old_pid']!=row['resume_pid']
   assert row['old_pid'] in {x['pid'] for x in log}
   archived_commands=[read(p) for p in (D/'attempt_02').glob('command_*.json')]
   assert any(r['exit_code']==0 and str(row['resume_pid']) in r['stdout'] and root.name in str(r['argv']) for r in archived_commands)
   # A COMMITTED-only continuation may make no business calls in resumed process;
   # its new PID is independently recorded in subprocess stdout.
   h=read(root/'header.json');prev=dg(h);records=[]
   for p in sorted((root/'journal').glob('*.json')):
    r=read(p);assert r['previous_digest']==prev and r['record_digest']==dg({k:v for k,v in r.items() if k!='record_digest'})
    assert r['checkpoint_digest']==dg(r['checkpoint']);cp=r['checkpoint']
    assert cp['record_digest']==dg({k:v for k,v in cp.items() if k!='record_digest'})
    records.append(cp);prev=r['record_digest']
   assert records[-1]==ep['checkpoint']
   for cp in records:
    ev=cp.get('pending_event')
    if ev and ev.get('monitor'):
     m=ev['monitor'];assert m['result_digest']==dg(m['result']) and m['credential_digest']==dg({k:v for k,v in m.items() if k!='credential_digest'})
   checks.append(dict(scenario=scenario,phase=phase,counts=count,records=len(records),old_pid=row['old_pid'],resume_pid=row['resume_pid']))
 # Read-only worker was fully reviewed; snapshot all files before/after each run.
 py=read(D/'environment.json')['executable'];env=dict(os.environ,PYTHONDONTWRITEBYTECODE='1',PYTHONPATH='PCT/tests:PCT/src:semantic_pallet_planner/src')
 commands=[]
 for root in jobs:
  before={str(p.relative_to(root)):sha(p) for p in root.rglob('*') if p.is_file()}
  r=subprocess.run([py,'PCT/tests/p1c_worker.py','verify','--root',str(root)],env=env,text=True,capture_output=True)
  result=dict(command='PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=PCT/tests:PCT/src:semantic_pallet_planner/src "$NBU_PY" PCT/tests/p1c_worker.py verify --root '+str(root),exit_code=r.returncode,stdout=r.stdout,stderr=r.stderr)
  commands.append(result)
  assert r.returncode==0,result
  value=json.loads(r.stdout);assert value['forbidden_calls']==[] and not value['scipy_imported']
  assert before=={str(p.relative_to(root)):sha(p) for p in root.rglob('*') if p.is_file()}
 (Q/'verify_commands.json').write_text(json.dumps(commands,ensure_ascii=False,indent=2)+'\n')
 result=dict(status='PASS_SAVED_FACTS_ONLY',source_files=len(identity['source_configuration_schema_sha256']),delivery_files=len(manifest['files']),source_mismatches=drift,delivery_mismatches=mismatch,cross_process_comparisons=checks,read_only_validator_jobs=len(jobs),forbidden_calls=[],scipy_imported=False,not_run=['order','candidate generation','LP','new interruption/resume','lock contention','business tests','install','models'])
 (Q/'saved_checks.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n');print('PASS:',len(manifest['files']),'delivery files,',len(checks),'comparisons,',len(jobs),'read-only validators')
if __name__=='__main__':main()
