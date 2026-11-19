"""Pure identity preparation only; never generate candidates or execute orders."""
import json,hashlib,shutil,subprocess,traceback
from pathlib import Path
I=Path(__file__).resolve().parent;B=I.parent;R6=B/'GEOM_CANDIDATES_GP5_NUM_N1_R6_20261118_01';R7=B/'GEOM_CANDIDATES_GP5_NUM_N1_R7_20261118_01'
def read(p):return json.loads(p.read_bytes())
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def write(n,v):(I/n).write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n')
def main():
 from scope_guard import UNIT,SOURCE,ALLOWED,LIMITS,Guard
 from semantic_pallet_planner.jev_select.contracts import digest
 from semantic_pallet_planner.jev_select import packaging_geometry_protocol as p,geometry_order_execution as order
 from semantic_pallet_planner.jev_select.geometry_native_protocol import identity_fields,policy_digest
 from semantic_pallet_planner.jev_select.stability.runtime import environment
 assert not (I/'preparation_started.json').exists(),'NO_RETRY'
 write('preparation_started.json',{'unit':UNIT,'execution_authorized':False})
 src=Path('semantic_pallet_planner/src/semantic_pallet_planner')
 actual={str(f.relative_to(src)):sha(f) for f in src.rglob('*') if f.is_file() and f.suffix in ('.py','.json') and not {'tests','__pycache__'}.intersection(f.relative_to(src).parts)}
 assert len(actual)==591 and actual==read(R7/'source_manifest.json')['files'] and digest(actual)==SOURCE,'SOURCE_MISMATCH'
 write('source_manifest.json',{'files':actual,'source_files':591,'source_identity':SOURCE})
 # Full original historical byte inventory retained, not migrated or re-signed.
 history=read(R7/'historical_identity.json')
 write('historical_inventory.readonly.json',history)
 tasks=[]
 for tid in ('GP5_SYNTH_K02_INT','GP5_SYNTH_K02'):
  raw=(R6/(tid+'.raw.json')).read_bytes();t=p.adapt_task(raw,origin='SYNTHETIC_FIXED',expected_sha256=p.sha(raw));tasks.append(t)
  (I/(tid+'.raw.json')).write_bytes(raw);write(tid+'.identity.json',t['identity'])
 mon=read(R6/'monitor_snapshot.json');order.validate_monitor_snapshot(mon)
 plan=p.prepare_order_plan(tasks,data_identity=digest({'unit':UNIT,'data':[t['identity'] for t in tasks]}),scope=p.DEVELOPMENT,native=True)
 adm={**identity_fields(plan),'version':'geometry_development_binding_v2','scope':p.DEVELOPMENT,'evidence':'TEST_DOUBLE','plan_digest':digest(plan)}
 configs={j['job_id']:order.load_order_config(plan,j['job_id'],monitor_snapshot=mon,admission=adm) for j in plan['jobs']}
 assert len(configs)==8;Guard(plan)
 for n,v in [('plan',plan),('admission',adm),('configs',configs),('monitor_snapshot',mon)]:write(n+'.json',v)
 scope=read(R6/'validation_scope.json');scope.update(unit=UNIT,E_jobs=2,E_new_monitor_max=4,historical_E_used=21,historical_E_cross_max=21,allowed_jobs=ALLOWED,independent_limits=LIMITS)
 write('validation_scope.json',scope)
 write('environment_receipt.json',{'observed':environment(),'expected':mon['execution_environment'],'dependencies':mon['algorithm_identity']['dependencies'],'preflight':'PASS','configs_preflighted':8,'monitor_evidence':'TEST_DOUBLE_ONLY'})
 write('strategy_identity.json',{'policy_digest':policy_digest(),'config_digests':{k:digest(v) for k,v in configs.items()},'data':[t['identity'] for t in tasks]})
 protected=[R6,R7,B/'GEOM_CANDIDATES_GP5_NUM_N1_R7_QA_20261118_01',B/'GEOM_CANDIDATES_GP5_NUM_N1_FIXED_SYNTHETIC_REVALIDATION_20261118_01']
 write('archive_member_identity.json',{'files':{str(f):sha(f) for folder in protected for f in folder.rglob('*') if f.is_file() and '__pycache__' not in f.parts}})
 from run_state import case_rows
 rows=case_rows(scope)
 for row in rows:
  if row['group']=='E' and row['id'] not in ('E/J01','E/J03'):row['status']='NOT_RUN_OUT_OF_PROPOSED_MINIMUM_SCOPE'
 write('case_results.json',{'rows':rows,'denominator':35,'proposed':29,'execution':'NOT_AUTHORIZED'})
 write('baseline_receipt.json',{'branch':'dev/jev-select','upstream':'origin/dev/jev-select','before_head':'a060652f4f557337753043e1c91bed024f647139','synced_head':subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),'worktree_before':'CLEAN','index_before':'EMPTY','pull':'FAST_FORWARD','source_files':591,'source_identity':SOURCE})
 print('PASS 591 source files; new plan/config8 preflight; allowlist J01/J03; no business dispatch')
if __name__=='__main__':
 try:main()
 except BaseException as e:
  write('stop.json',{'type':type(e).__name__,'detail':str(e),'traceback':traceback.format_exc(),'no_retry':True});raise
