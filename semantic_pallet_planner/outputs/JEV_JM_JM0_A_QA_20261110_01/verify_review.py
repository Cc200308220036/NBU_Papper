"""Independent QA: stdlib saved-file checks only; no project imports or mutations outside QA receipt."""
from pathlib import Path
import json, hashlib, re, collections, subprocess
ROOT=Path(__file__).resolve().parents[3]
OUT=Path(__file__).resolve().parent
REPORT=ROOT/'docs/03_阶段产出分析/Jev/Jev_JM0-A源码数据来源与暴露审查_20261110.md'
def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def read(p): return json.loads((ROOT/p).read_text())
refs=[]
for target in re.findall(r'\]\(([^)]+)\)', REPORT.read_text()):
 p=(REPORT.parent/target).resolve();refs.append({'target':target,'exists':p.exists()})
checks=[]
for folder,names in [('JEV_JN3_20261104_01',['trajectory_snapshot.json']),('JEV_JN3_20261104_02',['contrast_snapshot.json']),('JEV_JN5_ANALYSIS_20261107_03',['handoff.json','all_36_metrics.json','main_24_metrics.json','evidence_index.json'])]:
 base='semantic_pallet_planner/outputs/'+folder
 manifest=read(base+'/delivery_manifest.json')
 for name in names:
  path=base+'/'+name
  entries=[r for r in manifest.get('files',[]) if r['path']==path]
  if 'files_sha256' in manifest and name in manifest['files_sha256']: entries=[{'sha256':manifest['files_sha256'][name]}]
  checks.append({'path':path,'actual_sha256':sha(ROOT/path),'manifest_sha256':entries[0]['sha256'] if len(entries)==1 else None,'matches':len(entries)==1 and sha(ROOT/path)==entries[0]['sha256']})
audit=read('semantic_pallet_planner/outputs/JEV_JN4_20261105_01/source_audit.json')['components']
split=read('semantic_pallet_planner/outputs/DATA_JEV_PACKAGING_LOAD_20261102_02/split_manifest.json')
code={
 'geometry_continuation':('packaging_counterfactual.py',"METHOD = 'local_geometry_test_double'"),
 'nonempty_history_guard':('packaging_experience.py',"require(not o['placed'],'memory_nonempty_history_projection_not_supported')"),
 'remote_empty_memory_guard':('packaging_remote.py',"if context.data['model_state']['memories']!=[]"),
 'exact_v3_route':('stability/monitor.py',"if algorithm=='pct_exact_pose_network_v3'")}
symbol_checks={k:{'path':'semantic_pallet_planner/src/semantic_pallet_planner/jev_select/'+f,'found':t in (ROOT/'semantic_pallet_planner/src/semantic_pallet_planner/jev_select'/f).read_text()} for k,(f,t) in code.items()}
result={'version':'jm0a_independent_static_checks_v1','head':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),'original_delivery_exists':(ROOT/'semantic_pallet_planner/outputs/JEV_JM0_A_20261110_01').exists(),'report_links':refs,'missing_report_links':sum(not x['exists'] for x in refs),'historical_selected_hash_checks':checks,'historical_selected_hash_checks_pass':all(x['matches'] for x in checks),'source_component_count':len(audit),'exposure_counts':dict(collections.Counter(x['exposure_status'] for x in audit)),'strict_eligible_count':sum(x['strict_test_eligible'] for x in audit),'split_groups':split['groups'],'snapshot_counts':{'T':len(read('semantic_pallet_planner/outputs/JEV_JN3_20261104_01/trajectory_snapshot.json')['cases']),'E':len(read('semantic_pallet_planner/outputs/JEV_JN3_20261104_02/contrast_snapshot.json')['cards'])},'current_material_presence':{p:(ROOT/p).exists() for p in ['ReMe-main','ReMe-main.zip','raw/mixed_pallet_boxes']},'source_text_checks':symbol_checks,'limits':'No project imports, behavior tests, candidate reconstruction, orders, forks, solver, credentials, model or network. Text checks are not behavioral validation.'}
(OUT/'static_checks.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
print(json.dumps({k:result[k] for k in ['head','original_delivery_exists','missing_report_links','historical_selected_hash_checks_pass','source_component_count','exposure_counts','strict_eligible_count','snapshot_counts','current_material_presence']},ensure_ascii=False))
