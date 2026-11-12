"""Read-only C1 delivery discovery. No credentials or business/runtime imports."""
import hashlib,json,subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3];OUT=Path(__file__).resolve().parent
HEAD='9cd053e474be9fc3e8a252c420258dc388ffacb1'
def load(p):return json.loads(p.read_text())
changed=subprocess.check_output(['git','-c','core.quotepath=false','diff','--name-only','8b15b534',HEAD],cwd=ROOT,text=True).splitlines()
assert len(changed)==8 and all(p.startswith('semantic_pallet_planner/outputs/JEV_JM_B2_FREEZE_CLOSURE_QA_20261112_01/') or p in ['docs/03_阶段产出分析/Jev/README.md','docs/03_阶段产出分析/Jev/Jev_JM1-B2正式冻结收尾独立质检与C1技术准入_20261112_01.md'] for p in changed)
found={}
for rel in ['semantic_pallet_planner/outputs','outputs']:
 base=ROOT/rel
 found[rel]=sorted(p.name for p in base.iterdir() if p.is_dir() and any(k in p.name.upper() for k in ['C1','PRESEND','PRE_SEND','PREFLIGHT']) and p.resolve()!=OUT.resolve()) if base.exists() else []
freeze=load(ROOT/'semantic_pallet_planner/outputs/JEV_JM1_B2_FREEZE_CLOSURE_20261112_01/formal_freeze.json')
runtime=ROOT/'semantic_pallet_planner/outputs/JEV_JM1_B2_FREEZE_CLOSURE_20261112_01/materials/future_runs'
result={'version':'jm_c1_delivery_discovery_v1','head':HEAD,'new_commit_content':'Previous B2 QA archive only; commit title not proof of C1 implementation','changes_from_last_reviewed_head':changed,'bounded_directory_discovery':found,'local_frozen_relative_runtime_root_exists':runtime.exists(),'known_freeze_identity':freeze['receipt_digest'],'known_freeze_operation_root':freeze['operation_root'],'C1_delivery_handoff':'NOT_LOCATED','C1_actual_authorization_execution_status':'UNKNOWN_NOT_PROVIDED','previous_B2_technical_C1_admission':'READY_TECHNICAL_ONLY_PRESERVED','status':'NOT_ASSESSED_MISSING_TARGET_DELIVERY','scope_limit':'bounded local discovery, does not prove no C1 work exists on developer host or elsewhere','current_business_dispatches':0}
if (OUT/'operator_followup.json').exists():
 result['operator_followup']=load(OUT/'operator_followup.json')
 snapshot=load(ROOT/'semantic_pallet_planner/outputs/JEV_JM1_B2_FREEZE_CLOSURE_20261112_01/source_manifest.json')
 package=ROOT/'semantic_pallet_planner/src/semantic_pallet_planner'
 actual={p.relative_to(package).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(package.rglob('*')) if p.is_file() and p.suffix in ('.py','.json') and not {'tests','__pycache__'}.intersection(p.relative_to(package).parts)}
 assert actual==snapshot
 result.update(frozen_runtime_manifest_files=len(actual),frozen_runtime_source_bytes_match=True,HEAD_difference_disposition='QA_ONLY_SUCCESSOR_ALLOWED_FOR_READ_ONLY_CONTINUATION',C1_actual_authorization_execution_status='OPERATOR_REPORTED_ZERO_CALLS_NO_EXECUTION',status='HEAD_ONLY_STOP_RESOLVED_FULL_PREFLIGHT_PENDING')
(OUT/'static_checks.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n');print(json.dumps(result,ensure_ascii=False))
