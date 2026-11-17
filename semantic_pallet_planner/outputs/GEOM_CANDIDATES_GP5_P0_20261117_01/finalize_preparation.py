"""Seal preparation documents, never execute production or issue runtime authorization."""
import ast,hashlib,json,pathlib,re,subprocess
P=pathlib.Path
OUT=P('semantic_pallet_planner/outputs/GEOM_CANDIDATES_GP5_P0_20261117_01')
BASE=P('semantic_pallet_planner/src/semantic_pallet_planner')
DES=P('docs/02_阶段实施方案/几何规划模块/几何候选器GP5-P0真实订单接入与验收补充方案_20261117_01.md')
REPORT=P('docs/03_阶段产出分析/几何规划模块/几何候选器GP5-P0准备方案与GP4离线补图交付_20261117_01.md')
def read(p):return json.loads(p.read_bytes())
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def save(n,d):(OUT/n).write_text(json.dumps(d,ensure_ascii=False,indent=2)+'\n')
paths=['jev_select/packaging_versions.py','jev_select/contracts.py','jev_select/config.py','jev_select/candidate_backends.py','jev_select/geometry_execution.py','jev_select/geometry_runtime_contracts.py','jev_select/geometry_runtime_input.py','jev_select/episode.py','jev_select/packaging_runtime.py','jev_select/selector.py','jev_select/execution.py','jev_select/stability/monitor.py','jev_select/stability/exact_adapter.py','jev_select/stability/exact_contracts.py']
interfaces=[]
for rel in paths:
 p=BASE/rel;tree=ast.parse(p.read_text())
 interfaces.append({'path':str(p),'sha256':sha(p),'definitions':[{'name':n.name,'line':n.lineno} for n in tree.body if isinstance(n,(ast.FunctionDef,ast.ClassDef))]})
for p in [P('semantic_pallet_planner/tests/unit/test_stability_balance.py'),P('semantic_pallet_planner/tests/unit/test_packaging_exact.py')]:
 interfaces.append({'path':str(p),'sha256':sha(p),'scope':'READ_ONLY_ANALYTIC_REFERENCE_NOT_EXECUTED'})
evidence=[]
for folder in ['GEOM_CANDIDATES_GP3_N3_20261117_01','GEOM_CANDIDATES_GP3_N3_R1_20261117_01','GEOM_CANDIDATES_GP3_N3_R1_QA_20261117_01']:
 for name in ['handoff.json','delivery_manifest.json','checks.json']:
  p=OUT.parent/folder/name
  if p.exists():
   d=read(p);evidence.append({'path':str(p),'sha256':sha(p),'top_level_keys':list(d)})
save('interface_inventory.json',{'version':'gp5_p0_interfaces_v1','existing':interfaces,'archive_receipts':evidence,'missing_proposed_module':'jev_select/packaging_geometry_protocol.py','proposed_v16':'NOT_REGISTERED_NOT_IMPLEMENTED','design':str(DES),'no_production_import':True})
figures=[]
for f in sorted((OUT/'figures').glob('*.png')):
 figures.append({'path':str(f),'sha256':sha(f),'status':'DEVELOPER_READABILITY_CHECK_PASS_PENDING_QA','dimensions':[1600,1300],'checks':['four axes titles and x/y/z units','tick digits','legend and caption','no selection/monitor claim'],'method':'view_image final PNG plus native-resolution/crop inspection when conversation preview omitted repeated labels'})
save('visual_review.json',{'issue':'GP4-FIG-01','status':'SUPPLEMENT_COMPLETE_PENDING_INDEPENDENT_QA','original_issue_not_rewritten':True,'figures':figures,'limits':'same saved candidate overlap; action identity/counts remain in original tables','iterations':['initial layout export with fontconfig warnings','explicit text clip/dpi and temporary caches','one process per saved point','final 100dpi 1600x1300; original source data unchanged']})
save('command_receipts.json',{'commands':[{'command':'git pull --ff-only','exit':1,'detail':'sandbox .git/FETCH_HEAD read-only; no sync'},{'command':'git pull --ff-only (approved escalation)','exit':0,'detail':'adbdf21d -> e1422b01 FF_ONLY'},{'command':'PYTHONDONTWRITEBYTECODE=1 python3 '+str(OUT/'audit_preparation.py'),'exit':1,'detail':'first source comparison included 29 tests files; assertion failed (571 vs542); no changed source members'},{'command':'PYTHONDONTWRITEBYTECODE=1 python3 '+str(OUT/'audit_preparation.py'),'exit':0,'detail':'same exclusion of tests as frozen manifest;542 files match; all delivery hashes match;16 tasks inventoried'},{'command':'MPLCONFIGDIR=/tmp/gp5_p0_mpl PYTHONDONTWRITEBYTECODE=1 python3 '+str(OUT/'render_saved_figures.py'),'exit':0,'detail':'initial offline five exports; fontconfig no writable cache warnings, no dependency install'},{'command':'for point in P01_ffcfcc6e4af4 P02_f17e03ef6116 P03_81c78da5f3a7 P04_53bacc63aa29 P05_392be366b95d; do XDG_CACHE_HOME=/tmp/gp5_p0_cache MPLCONFIGDIR=/tmp/gp5_p0_mpl PYTHONDONTWRITEBYTECODE=1 python3 '+str(OUT/'render_saved_figures.py')+' "$point"; done','exit':0,'detail':'final export 5 independent saved-data processes; no generator; each SAVED_FIGURES 5 counts directory not process output'},{'command':'git diff --check','exit':0,'detail':'checked during finalization'}],'format':'tool-output summaries, not claimed raw stderr transcripts','read_search_errors':['proposed packaging_geometry_protocol.py absent (expected gap)','exploratory packaging_order.py/test_exact_stability.py absent; actual packaging_runtime.py/test_packaging_exact.py read'],'no_add_commit_push':True})
# Verify relative markdown references of newly delivered docs, no internet.
links=[]
for p in [DES,REPORT]:
 for target in re.findall(r'\]\(([^)]+)\)',p.read_text()):
  q=p.parent/target;links.append({'document':str(p),'target':target,'exists':q.exists()})
assert all(r['exists'] for r in links)
# Verify immutable saved render inputs and original PNGs after export.
for r in read(OUT/'figure_sources.json')['files']:assert sha(P(r['path']))==r['sha256']
for rel,h in read(OUT/'source_inventory.json')['files'].items():assert sha(BASE/rel)==h
matrix=read(OUT/'task_matrix_draft.json');assert len(matrix['jobs'])==8 and not matrix['execution_authorized']
assert all(r['status']=='NOT_RUN' for r in matrix['jobs'])
subprocess.run(['git','diff','--check'],check=True)
assert not subprocess.check_output(['git','diff','--cached','--name-only']).strip()
changed=subprocess.check_output(['git','-c','core.quotepath=false','diff','--name-only']).decode().splitlines()
assert set(changed)=={'docs/02_阶段实施方案/几何规划模块/README.md','docs/03_阶段产出分析/几何规划模块/README.md'}
save('checks.json',{'scope':'GP5_P0_PREPARATION_ONLY','checks':[{'item':'manifests/source/data','status':'PASS','evidence':'readonly_receipt.json; source_inventory.json; data_inventory.json'},{'item':'new document links','status':'PASS','links':links},{'item':'original figures and saved inputs preserved','status':'PASS','evidence':'figure_sources.json'},{'item':'8job draft no permit','status':'PASS'},{'item':'design/protocol/kernel acceptance plan','status':'DESIGN_COMPLETE_PENDING_QA'},{'item':'GP4-FIG-01','status':'SUPPLEMENT_COMPLETE_PENDING_QA','evidence':'visual_review.json'},{'item':'git diff --check; index empty','status':'PASS'},{'item':'A03 real exact E2E','status':'PARTIAL_NOT_RUN'},{'item':'production integration','status':'NOT_IMPLEMENTED'},{'item':'GP5 execution','status':'NOT_READY'}],'actual_candidate_order_kernel_model_calls':0,'production_tests':'NOT_RUN'})
save('not_run_and_blockers.json',{'production_integration':'NOT_IMPLEMENTED','real_exact_v3_E2E':'NOT_RUN','A03':'PARTIAL','GP5':'NOT_READY','matrix_jobs_executed':0,'model_kernel_freeze_LP_calls':0,'remaining':['independent QA of preparation','explicit later development authorization','v16 implementation and limited compatibility checks','explicit limited real-kernel authorization and independently accepted A03 evidence','actual run identities and independent GP5 admission plus later run instruction'],'same_source_limit':'2 task variants / 1 source family','public_negative_E2E':'not guaranteed by adapter analytic counterexample; retain PARTIAL if not covered','old_raw':'NOT_AVAILABLE; unchanged','GP6_F1_T_E_training':'NOT_AUTHORIZED'})
save('handoff.json',{'version':'geometry_gp5_p0_handoff_v1','scope':'GP5_P0_PREPARATION_ONLY','date':'2026-11-17','entry_head':'adbdf21ded76df9ba4704087841ccff6154b53b7','sync_head':subprocess.check_output(['git','rev-parse','HEAD']).decode().strip(),'status':'PREPARATION_AND_OFFLINE_SUPPLEMENT_COMPLETE_PENDING_INDEPENDENT_QA','design':str(DES),'report':str(REPORT),'matrix':'task_matrix_draft.json','figures':'figures/','manifest':'delivery_manifest.json','A03':'PARTIAL','GP5':'NOT_READY','production_changed':False,'calls':{'candidate':0,'order':0,'kernel':0,'model':0,'actual_kernel_freeze':0},'execution_permission_issued':False,'git_add_commit_push':'NOT_RUN','index':'EMPTY','stopped':True,'next_task_prompt_authored':False})
files=[p for p in OUT.rglob('*') if p.is_file() and p.name!='delivery_manifest.json']+[DES,REPORT,DES.parent/'README.md',REPORT.parent/'README.md']
save('delivery_manifest.json',{'version':'geometry_gp5_p0_delivery_manifest_v1','scope':'PREPARATION_ONLY_NOT_EXECUTABLE','files':[{'path':str(p),'sha256':sha(p),'size_bytes':p.stat().st_size} for p in sorted(files)],'excludes':['delivery_manifest.json self'],'historical_manifests':'NOT_RESIGNED'})
print('PREPARATION_CHECKS_PASS',len(files),'files; no production execution')
