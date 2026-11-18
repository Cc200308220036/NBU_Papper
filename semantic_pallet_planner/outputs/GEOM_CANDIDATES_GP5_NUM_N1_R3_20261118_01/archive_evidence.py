import json,hashlib,sys,platform,subprocess,shutil
from pathlib import Path
O=Path('semantic_pallet_planner/outputs/GEOM_CANDIDATES_GP5_NUM_N1_R3_20261118_01')
def sha(b):return hashlib.sha256(b).hexdigest()
def save(n,v):(O/n).write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n')
def read(p):return json.loads(Path(p).read_bytes())
checked=[]
for name,rev in [('GEOM_CANDIDATES_GP5_NUM_N1_R2_20261118_01','1db7a7f78b7389105046bcaf6a6ddbfdf6ccb0ae'),('GEOM_CANDIDATES_GP5_NUM_N1_R2_QA_20261118_01','cfb399ca447d75d144ae33f018c249a864a5d156')]:
 m=O.parent/name/'delivery_manifest.json';rows=read(m)['files']
 for r in rows:
  p=Path(r['path']);b=subprocess.check_output(['git','show',rev+':'+str(p)]) if p.name=='README.md' else p.read_bytes()
  assert len(b)==r['size_bytes'] and sha(b)==r['sha256'],str(p)
 checked.append({'manifest':str(m),'sha256':sha(m.read_bytes()),'verified_members':len(rows),'navigation_revision':rev})
src=Path('semantic_pallet_planner/src/semantic_pallet_planner');old=read(O.parent/'GEOM_CANDIDATES_GP5_NUM_N1_R1_20261118_01/source_manifest.json')['files'];new=read(O/'source_manifest.json')['files']
assert set(old)==set(new) and len(new)==591
changes=[p for p in old if old[p]!=new[p]]
assert set(changes)=={'jev_select/geometry_native_shape_bridge.py','jev_select/geometry_native_protocol.py'}
for p in old:
 b=subprocess.check_output(['git','show','HEAD:'+str(src/p)]) if p in changes else (src/p).read_bytes()
 assert sha(b)==old[p],p
for phase in ('before','after'):
 for rel in changes:
  target=O/'source_snapshot'/phase/rel;target.parent.mkdir(parents=True,exist_ok=True)
  target.write_bytes(subprocess.check_output(['git','show','HEAD:'+str(src/rel)]) if phase=='before' else (src/rel).read_bytes())
(O/'production_change.patch').write_bytes(subprocess.check_output(['git','diff','--',*[str(src/p) for p in changes]]))
shutil.copyfile('semantic_pallet_planner/tests/unit/test_geometry_native_key_r3.py',O/'test_geometry_native_key_r3.py')
snap=read(O.parent/'GEOM_CANDIDATES_GP3_N3_20261117_01/cases/ems_surface_hybrid_v1_stable/config.json')['stability_monitor']
shutil.copyfile(O.parent/'GEOM_CANDIDATES_GP3_N3_20261117_01/cases/ems_surface_hybrid_v1_stable/config.json',O/'original_monitor_config.readonly.json')
actual={'python':sys.version,'executable':sys.executable,'platform':platform.platform()}
expected=snap['execution_environment']
save('environment_difference.json',{'archived':expected,'observed_stdlib_fields':actual,'differences':{k:{'expected':expected[k],'observed':v} for k,v in actual.items() if expected[k]!=v},'dependencies':'preflight reached final environment comparison after dependency/source checks; no second preflight','action':'STOP; no environment substitution, snapshot rewrite or retry'})
save('baseline_receipt.json',{'entry_head':'1db7a7f78b7389105046bcaf6a6ddbfdf6ccb0ae','actual_head':'cfb399ca447d75d144ae33f018c249a864a5d156','branch':'dev/jev-select','upstream':'origin/dev/jev-select','initial_worktree':'CLEAN','initial_index':'EMPTY','pull':{'command':'git pull --ff-only','first_attempt':'FETCH_HEAD read-only; exit1','authorized_escalated_attempt':'FAST_FORWARD_SUCCESS','changes':'QA/report/navigation only'},'baseline_source_identity':'be3486f6f90f4c4b3ec2696aaf8fee24353d4b83af78892576962e437370cd89','source_files':591,'baseline_full_set_and_bytes_verified':True,'changed':changes,'current_source_identity':read(O/'source_manifest.json')['source_identity'],'historical_manifests':checked})
save('stop.json',{'status':'FIRST_UNEXPECTED_FAILURE_STOPPED','group':'PRE_E_CONFIGURATION_FREEZE','command':'PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=semantic_pallet_planner/src:semantic_pallet_planner/tests/unit python semantic_pallet_planner/outputs/GEOM_CANDIDATES_GP5_NUM_N1_R3_20261118_01/prepare_validation.py','exit_code':1,'exception':'JevSelectError','code':'geometry_order_monitor_environment','location':'load_order_config -> preflight_order -> validate_monitor_snapshot','source_manifest_written':True,'complete_config_plan_policy_environment_freeze':False,'retry':False,'E_R_X_H_ADMIN':'NOT_RUN','real_kernel_LP_freeze_model':0})
save('call_accounting.json',{'historical_E_used':5,'old_E_limit_receipt':17,'R3_E_authorized_max':16,'cross_history_E_authorized_max':21,'R3_E_jobs_started':0,'R3_E_monitors':0,'cross_history_E_actual':5,'R3_R_resumes':0,'R3_R_monitors':0,'R3_R_commits':0,'R3_R_generation_bridge_selection':0,'R3_X_H_monitors':0,'candidate_generation_shadow_monitor_commit_total':0,'real_PCT_LP_freeze_model_real_episode_formal8job_GP6_install_subagents':0,'old_receipts_rewritten':False})
oldscope=read(O.parent/'GEOM_CANDIDATES_GP5_NUM_N1_R1_20261118_01/validation_scope.json')
save('not_run_inventory.json',{'C':[{'name':n,'status':'NOT_RUN'} for n in oldscope['C']],'E':[{'job_id':'J%02d'%i,'production_status':'NOT_RUN','validation_status':'NOT_RUN'} for i in range(8)],'R':[{'job_id':j,'phase':p,'status':'NOT_RUN'} for j in ('J01','J03') for p in ('SELECTED','MONITORED','COMMITTED')],'X_H_ADMIN':[{**r,'status':'NOT_RUN','entrypoint':'NOT_IMPLEMENTED_BEFORE_STOP'} for r in oldscope['X_H']],'reason':'first unexpected pre-E environment failure; no remaining validation dispatch'})
save('command_receipts.json',{'commands':[{'command':'git pull --ff-only','result':'normal exit1 read-only; escalated exit0 fast-forward'},{'command':'PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=semantic_pallet_planner/src:semantic_pallet_planner/tests/unit python -m unittest discover -s semantic_pallet_planner/tests/unit -p test_geometry_native_key_r3.py -v','exit_code':0,'evidence':'pure_key_test.log','scope':'pure metadata2 methods; no generation'},{'command':read(O/'stop.json')['command'],'exit_code':1,'evidence':'prepare_failure.log','scope':'configuration preflight only; first unexpected failure stopped'}],'archival_checks':'standard library manifest and source verification only after stop','no_business_retry':True})
print(json.dumps({'verified':checked,'source_identity':read(O/'source_manifest.json')['source_identity'],'environment_difference':{k:[expected[k],v] for k,v in actual.items() if expected[k]!=v}},ensure_ascii=False))
