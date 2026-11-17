"""Static packaging only; no production imports or historical re-signing."""
import ast,hashlib,json,pathlib,re,subprocess,sys
P=pathlib.Path
OUT=P('semantic_pallet_planner/outputs/GEOM_CANDIDATES_GP5_P1_20261117_01')
BASE=P('semantic_pallet_planner/src/semantic_pallet_planner')
DES=P('docs/02_阶段实施方案/几何规划模块/几何候选器GP5-P1协议实现与P2启动合同补充_20261117_01.md')
REPORT=P('docs/03_阶段产出分析/几何规划模块/几何候选器GP5-P1真实订单协议限定实现与替身验收交付_20261117_01.md')
def read(p):return json.loads(p.read_bytes())
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def save(n,v):(OUT/n).write_text(json.dumps(v,ensure_ascii=False,sort_keys=True,indent=2)+'\n')
def digest(v):return hashlib.sha256(json.dumps(v,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()
current={str(p.relative_to(BASE)):sha(p) for p in sorted(BASE.rglob('*')) if p.is_file() and p.suffix in ('.py','.json') and not {'tests','__pycache__'}.intersection(p.relative_to(BASE).parts)}
before=read(OUT/'before_source_manifest.json')['files'];modified=[k for k in before if before[k]!=current.get(k)];added=[k for k in current if k not in before];removed=[k for k in before if k not in current]
assert not removed
allowed={'jev_select/'+n for n in ('packaging_versions.py','contracts.py','config.py','candidate_backends.py','episode.py','execution.py','selector.py','packaging_runtime.py','geometry_execution.py','stability/monitor.py')}
assert set(modified)==allowed
assert all(not k.startswith(('planner/','evaluation/','domain.py','o4/')) for k in modified)
assert all('/schemas/' not in k for k in modified)
for rel in modified+added:
 target=OUT/'code_snapshot'/rel;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes((BASE/rel).read_bytes())
newtest=P('semantic_pallet_planner/tests/unit/test_geometry_order_p1.py');(OUT/'test_geometry_order_p1.py.snapshot').write_bytes(newtest.read_bytes())
(OUT/'production_diff.patch').write_bytes(subprocess.check_output(['git','diff','--','semantic_pallet_planner/src']))
save('source_manifest.json',{'files':current,'source_identity':digest(current),'production_files':len(current),'interpreter':sys.version,'executable':sys.executable})
save('changes.json',{'modified':modified,'added':added,'removed':removed,'unchanged':len(before)-len(modified),'old_schemas_unchanged':True,'geometry_physics_numeric_core_unchanged':True,'new_test_sha256':sha(newtest),'source_after_checks05':sha(OUT/'source_manifest_checks05.json')})
# Historical manifests: pinned navigation revisions, all other bytes checked directly.
history=[]
for folder,rev in [('GEOM_CANDIDATES_GP5_P0_QA_20261117_01','a0ba4364e7f3f08018d3147b21dfc5a5f674bc7f'),('GEOM_CANDIDATES_GP5_P0_20261117_01','0fbb847d66bd72eda8e120682f73e98fd9e86884'),('GEOM_CANDIDATES_GP4_20261117_01','adbdf21ded76df9ba4704087841ccff6154b53b7')]:
 manifest=OUT.parent/folder/'delivery_manifest.json';rows=[]
 for r in read(manifest)['files']:
  p=P(r['path']);raw=subprocess.check_output(['git','show',rev+':'+str(p)]) if p.name=='README.md' else p.read_bytes()
  actual=hashlib.sha256(raw).hexdigest();assert actual==r['sha256'],p
  rows.append({'path':str(p),'sha256':actual,'navigation_revision':rev if p.name=='README.md' else None})
 history.append({'manifest':str(manifest),'sha256':sha(manifest),'members':rows})
save('readonly_receipt.json',{'history':history,'baseline_production_equal_P0':before==read(OUT.parent/'GEOM_CANDIDATES_GP5_P0_20261117_01/source_inventory.json')['files'],'no_historical_manifests_resigned':True,'only_git_network':'user-authorized ff-only pull','credentials_read':False})
# All final byte blobs independently verify their content-address names.
blobs=[]
for p in sorted((OUT/'final_evidence').rglob('blobs/*')):
 if p.is_file():assert sha(p)==p.name;blobs.append({'path':str(p),'sha256':sha(p)})
assert blobs
# AST and JSON syntax of delivered production files (read-only, no imports).
for rel in modified+added:
 path=BASE/rel
 if path.suffix=='.py':ast.parse(path.read_text())
 else:read(path)
links=[]
for p in (DES,REPORT):
 for target in re.findall(r'\]\(([^)]+)\)',p.read_text()):
  q=p.parent/target;assert q.exists(),q;links.append({'document':str(p),'target':target})
assert read(OUT/'p2_draft/acceptance_plan_DRAFT.json')['source_identity']==digest(current)
for log,count in [('offline_checks_05.log',33),('p1_final_06.log',13),('p1_archive_07.log',13)]:
 text=(OUT/log).read_text();assert 'Ran '+str(count)+' tests' in text and '\nOK\n' in text
subprocess.run(['git','diff','--check'],check=True)
assert not subprocess.check_output(['git','diff','--cached','--name-only']).strip()
save('static_checks.json',{'syntax':'PASS','old_source_guards':'UNCHANGED_ALGORITHM_PHYSICS_NUMERIC_AND_SCHEMAS','links':links,'durable_blob_count':len(blobs),'durable_blobs':blobs,'git_diff_check':'PASS','index':'EMPTY','P2_draft_identity':'MATCH_CURRENT_SOURCE'})
issue={'id':'GP5-P1-NUM-01','status':'OPEN','classification':'INHERITED_MULTISTEP_NATIVE_TYPE_COMPATIBILITY','backend':'ems_surface_hybrid_v1','actual':'integer dimensions, float oriented_size after first commit; next common input rejects RUNTIME_INPUT_INVALID','evidence':'final_evidence/test_integer_multistep_type_conflict_is_preserved_technical_failure/integer_type_conflict.json','not_fixed':'no algorithm/profile/physical/tolerance changes authorized','blocks':'real integer-order readiness; A03 total acceptance','P2_float_fixture_does_not_close_issue':True}
save('failure_and_limits.json',{'issues':[issue],'test_failures':[{'log':'test_01.log','failure':'two test expectation errors: public technical stop not external raise; first K02 pool2 notsingleton'},{'log':'test_02.log','failure':'integer multistep type conflict after first new-backend commit'}],'successful_iterations':['test_03.log','test_04.log','offline_checks_05.log','p1_final_06.log','p1_archive_07.log'],'actual_kernel_solver_freeze_model_real_orders':0,'real_meter_instrumentation':'NOT_RUN','GP4_main_generation':'NOT_RUN','P2':'NOT_READY','A03':'PARTIAL','orders_8job':'NOT_RUN','model_GF6_F1_T_E_training':'NOT_AUTHORIZED','test_temporary_approvals':'FIXTURE_ONLY_NOT_VALID_PERMISSIONS','test_relocation':'mapping resolves saved temp prefix; original bytes not rewritten'})
save('command_receipts.json',{'commands':[{'command':'git pull --ff-only','status':'READ_ONLY_FETCH_HEAD_FAILURE_THEN_APPROVED_FF_SUCCESS','entry':'0fbb847d66bd72eda8e120682f73e98fd9e86884','sync':'a0ba4364e7f3f08018d3147b21dfc5a5f674bc7f'},*({'command':'PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=semantic_pallet_planner/src GP5_P1_EVIDENCE='+str(OUT/ev)+' python3 -m unittest discover -s semantic_pallet_planner/tests/unit -p test_geometry_order_p1.py -v','log':log,'runner_status':status,'scope':scope} for log,ev,status,scope in [('test_01.log','evidence','FAILED_2_ASSERTIONS','first nine methods'),('test_02.log','iteration_02','FAILED_INTEGER_TYPE_CONFLICT','nine methods'),('test_03.log','iteration_03','OK_9','float K02'),('test_04.log','iteration_04','OK_11','integer negative and metrics added'),('p1_final_06.log','iteration_06','OK_13','driver ledger added'),('p1_archive_07.log','final_evidence','OK_13','same methods; complete durable archive')]),{'command':'PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=semantic_pallet_planner/src GP5_P1_EVIDENCE='+str(OUT/'iteration_05')+' python3 '+str(OUT/'run_offline_checks.py'),'exit_code':0,'log':'offline_checks_05.log','scope':'12 P1 +21 affected old regressions; saved-metadata TEST_DOUBLE freezer'},{'command':'PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=semantic_pallet_planner/src python3 '+str(OUT/'prepare_p2_draft.py'),'exit_code':0,'log':'p2_draft_preparation.log','scope':'draft only; no freezer/loop/assess/solver'},{'command':'git diff --check','exit_code':0}],'raw_log_notes':'initial runner failures preserved; log runner statuses are authoritative even where exploratory shell followed Python with tail','no_actual_kernel_or_network':True})
save('checks.json',{'scope':'GP5_P1_IMPLEMENTATION_ONLY','items':[{'id':'P1-01','item':'v16 contracts/routing; v14/v15 preservation','status':'PASS_LIMITED','evidence':'source diff; offline_checks_05.log'},{'id':'D01','item':'noncyclic scopes/typed receipts/separate counters','status':'IMPLEMENTED_OFFLINE_PASS_PENDING_QA','real_instrumentation':'NOT_RUN'},{'id':'D02','item':'float K02 target determinism without dedicated selector','status':'PASS_SYNTHETIC_TEST_DOUBLE','evidence':'final_evidence/test_two_backends_two_methods_complete_and_k02_exact_target/K02_reachability.json'},{'id':'P1-04','item':'phases, failures, exact commit and durable recovery','status':'PASS_TEST_DOUBLE','evidence':'final_evidence; static_checks.json'},{'id':'P1-05','item':'metrics/full denominator; real admin adaptation and execution refusal','status':'PASS_OFFLINE'},{'id':'GP5-P1-NUM-01','item':'integer multistep compatibility','status':'PARTIAL_OPEN','evidence':issue['evidence']},{'id':'A03','item':'real exact-v3 E2E','status':'PARTIAL_NOT_RUN'},{'id':'GP5','item':'actual source-order execution','status':'NOT_READY'}],'no_total_PASS_over_integer_issue':True,'actual_real_calls':{'assessment_entries':0,'solver_calls':0,'kernel_freeze':0,'models':0,'real_source_order_jobs':0}})
save('handoff.json',{'version':'geometry_gp5_p1_handoff_v1','date':'2026-11-17','scope':'GP5_P1_IMPLEMENTATION_ONLY','sync_head':'a0ba4364e7f3f08018d3147b21dfc5a5f674bc7f','status':'IMPLEMENTATION_AND_LIMITED_OFFLINE_CHECKS_DELIVERED_PENDING_INDEPENDENT_QA','report':str(REPORT),'design_supplement':str(DES),'source_manifest':'source_manifest.json','before_source_manifest':'before_source_manifest.json','checks':'checks.json','failures':'failure_and_limits.json','P2_draft':'p2_draft/','manifest':'delivery_manifest.json','engineering':'IMPLEMENTED_WITH_EXPLICIT_INTEGER_MULTISTEP_LIMIT','A03':'PARTIAL','P2':'NOT_READY_NOT_AUTHORIZED','actual_GP5':'NOT_READY','actual_real_calls':0,'issue':issue,'no_execution_permission_issued':True,'git_add_commit_push':'NOT_RUN','index':'EMPTY','next_task_prompt_authored':False,'stopped':True})
files=[p for p in OUT.rglob('*') if p.is_file() and p.name not in ('delivery_manifest.json','verification.json')]+[DES,REPORT,DES.parent/'README.md',REPORT.parent/'README.md',newtest]+[BASE/k for k in modified+added]
save('delivery_manifest.json',{'version':'geometry_gp5_p1_delivery_manifest_v1','scope':'IMPLEMENTATION_ONLY_NOT_REAL_EXECUTION_PERMISSION','files':[{'path':str(p),'sha256':sha(p),'size_bytes':p.stat().st_size} for p in sorted(files)],'excluded':['delivery_manifest.json self','verification.json post-seal read-only receipt'],'historical_identity':'not resigned'})
print('SEALED',len(files),'files; SOURCE',len(current),'MODIFIED',len(modified),'ADDED',len(added),'BLOBS',len(blobs))
