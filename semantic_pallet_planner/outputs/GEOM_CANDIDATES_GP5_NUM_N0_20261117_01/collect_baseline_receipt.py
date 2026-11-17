import hashlib,json,subprocess
from pathlib import Path
OUT=Path('semantic_pallet_planner/outputs/GEOM_CANDIDATES_GP5_NUM_N0_20261117_01');SRC=Path('semantic_pallet_planner/src/semantic_pallet_planner')
def sha(b):return hashlib.sha256(b).hexdigest()
def save(n,v):(OUT/n).write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n')
head=subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip();verified=[]
for pkg,rev in [('GEOM_CANDIDATES_GP5_P1_R1_QA_20261117_01',head),('GEOM_CANDIDATES_GP5_P1_R1_20261117_01','0c7cacb2dc58fcf97c1d4a682f65fb42b9cfe377')]:
 manifest=OUT.parent/pkg/'delivery_manifest.json';m=json.loads(manifest.read_bytes())
 for r in m['files']:
  p=Path(r['path']);raw=subprocess.check_output(['git','show',rev+':'+str(p)]) if p.name=='README.md' else p.read_bytes()
  assert sha(raw)==r['sha256'] and len(raw)==r['size_bytes'],str(p)
 verified.append({'manifest':str(manifest),'manifest_sha256':sha(manifest.read_bytes()),'members':len(m['files']),'status':'PASS','navigation_revision':rev})
files={str(p.relative_to(SRC)):sha(p.read_bytes()) for p in SRC.rglob('*') if p.is_file() and p.suffix in ('.py','.json') and not {'tests','__pycache__'}.intersection(p.relative_to(SRC).parts)}
frozen=json.loads((OUT.parent/'GEOM_CANDIDATES_GP5_P1_R1_20261117_01/source_manifest.json').read_bytes());assert files==frozen['files']
save('source_inventory.json',{'files':files,'source_identity':frozen['source_identity'],'production_files':len(files),'status':'UNCHANGED_FROM_REVIEWED_R1'})
save('readonly_receipt.json',{'root':'NBU_Papper','branch':'dev/jev-select','upstream':'origin/dev/jev-select','initial_head':'0c7cacb2dc58fcf97c1d4a682f65fb42b9cfe377','initial_worktree':'CLEAN','initial_index':'EMPTY','pull':'git pull --ff-only','pull_attempts':['FETCH_HEAD sandbox read-only; no sync','user-authorized escalated pull succeeded FAST_FORWARD'],'actual_head':head,'sync_changes':'12 QA/report/navigation files only; production unchanged','manifests':verified,'no_production_imports':True})
paths=[Path('AGENTS.md')]
for d in ('docs/02_阶段实施方案/几何规划模块','docs/03_阶段产出分析/几何规划模块'):
 paths.extend(p for p in Path(d).glob('*.md') if 'GP5' in p.name or p.name=='README.md' or 'PCT与GOPT' in p.name or 'GP3-N0' in p.name)
for name in ['quality_review.json','next_stage_admission.json','handoff.json','saved_evidence_verification.json','verification.json','delivery_manifest.json']:
 paths.append(OUT.parent/'GEOM_CANDIDATES_GP5_P1_R1_QA_20261117_01'/name)
paths += [SRC/'jev_select'/n for n in ['geometry_runtime_contracts.py','geometry_runtime_input.py','candidate_backends.py','geometry_execution.py','geometry_order_execution.py','packaging_geometry_protocol.py','geometry_kernel_completion.py','geometry_order_accounting.py','packaging_runtime.py','packaging_versions.py','config.py','contracts.py','context.py','execution.py','episode.py','stability/monitor.py']]
paths += [SRC/n for n in ['planner/space_candidates/generator.py','planner/space_candidates/reduction.py','planner/space_candidates/runtime_generator.py','planner/constraints.py','evaluation/state.py','evaluation/geometry_oracle.py','o4/buffer/buffer_state.py']]
save('read_inventory.json',[{'path':str(p),'sha256':sha(p.read_bytes()),'size_bytes':len(p.read_bytes())} for p in paths])
# Proposed names checked as exact byte strings in all production py/json, no imports.
names=['jev_packaging_geometry_order_v17','geometry_runtime_native_shape_bridge_v2','geometry_candidate_publication_v2','geometry_candidate_publication_proof_v2','geometry_native_shape_publication_policy_v2','geometry_order_plan_v2','geometry_order_execution_v2','geometry_order_durable_decision_v2','geometry_real_kernel_receipt_v3','geometry_kernel_completion_review_v2','geometry_kernel_required_coverage_v2','geometry_order_accounting_v2','geometry_order_metrics_v2','geometry_order_run_v2','geometry_development_binding_v2','geometry_kernel_launch_v2','geometry_order_admission_v2','geometry_scope_authorization_v2','geometry_scope_review_v2']
occupied={n:[rel for rel in files if n.encode() in (SRC/rel).read_bytes()] for n in names};assert not any(occupied.values()),occupied
save('proposed_name_inventory.json',{'status':'ALL_UNOCCUPIED_AT_BASELINE_NOT_REGISTERED','names':occupied,'recheck_before_implementation':True})
print('PASS: QA',verified[0]['members'],'R1',verified[1]['members'],'production',len(files),'source',frozen['source_identity'])
