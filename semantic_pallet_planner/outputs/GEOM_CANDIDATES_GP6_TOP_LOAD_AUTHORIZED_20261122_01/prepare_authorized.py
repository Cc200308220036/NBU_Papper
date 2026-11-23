"""Materialize exact user-authorized frozen plan and bindings; never dispatch."""
import copy
import hashlib
import json
from pathlib import Path
import sys
REPO=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(REPO/'semantic_pallet_planner/src'))
from semantic_pallet_planner.jev_select.contracts import digest,validate_schema
from semantic_pallet_planner.jev_select.experiment import source_manifest
from semantic_pallet_planner.jev_select.geometry_jev_kernel_bridge import target_binding,source_delta
from semantic_pallet_planner.jev_select.geometry_jev_protocol import validate_jev_plan,validate_jev_admission
from semantic_pallet_planner.jev_select.geometry_order_execution import validate_monitor_snapshot
from semantic_pallet_planner.jev_select.geometry_jev_execution import GeometryJevRequestLedger
from semantic_pallet_planner.jev_select.geometry_order_meter import CallBudget
from semantic_pallet_planner.jev_select.ledger import write
OUT=Path(__file__).parent
BASE=Path('semantic_pallet_planner/outputs')
EXPECTED='f5bb85910e1b44017b19c1ada506b4d48da87f2f74be4e87ce7f6addf42d6f73'
def read(p):return json.loads(Path(p).read_text())
def put(name,v):
 p=OUT/name
 if p.exists():assert read(p)==v, 'REFUSE_OVERWRITE_'+name
 else:write(p,v)
 return p

def ref(p):return {'path':Path(p).relative_to(REPO).as_posix() if Path(p).is_absolute() else str(p),'sha256':hashlib.sha256(Path(p).read_bytes()).hexdigest()}

def main():
 draft=read(BASE/'GEOM_CANDIDATES_GP6_TOP_LOAD_SWITCH_20261122_01/gp6_top_load_disabled_plan_DRAFT.json')
 plan={**draft,'status':'FROZEN'}
 assert digest(plan)==EXPECTED
 validate_jev_plan(plan)
 qa_path=BASE/'GEOM_CANDIDATES_GP6_TOP_LOAD_SWITCH_QA_20261122_01/next_stage_admission.json'
 qa=read(qa_path);assert qa['prospective_plan_digest_status_change_only']==EXPECTED and qa['source_identity']==plan['source_identity']
 assert digest(source_manifest())==plan['source_identity']
 snap_path=BASE/'GEOM_CANDIDATES_GP5_P2_FINAL_RUNTIME_20261120_01/monitor_snapshot.json'
 snap=read(snap_path);validate_monitor_snapshot(snap)
 for p,h in snap['algorithm_identity']['files_sha256'].items():
  assert hashlib.sha256((Path('semantic_pallet_planner/src/semantic_pallet_planner/jev_select/stability')/p).read_bytes()).hexdigest()==h
 put('gp6_top_load_plan_FROZEN.json',plan)
 prior=read(BASE/'GEOM_CANDIDATES_GP6_F0_FORMAL_ADMISSION_QA_20261122_01/kernel_bridge_APPROVED.json')
 target=target_binding(plan,snap)
 delta=source_delta(read(prior['historical_source_manifest']['path'])['files'],source_manifest())
 review={
  'version':'geometry_jev_kernel_applicability_review_v2','status':'APPROVED',
  **{k:prior[k] for k in ('evidence_receipt','historical_source_manifest','historical_monitor')},
  'target':target,'diff_digest':digest(delta),
  'changes':[{**row,'rationale':'当前源码身份与已归档包装承载开关限定独立复核一致；exact-v3 的23项身份文件及快照保持相同。本项属于版本化GP6运行/物理限载投影接线或其封闭Schema，旧证据仅按引用绑定使用。'} for row in delta],
  'conclusion':'绑定既有独立限定复核通过的源码及用户明确授权摘要；保留原exact-v3监测，准许驱动2/2内置预检后单次执行。',
  'reviewer':'执行窗口依据既有独立限定复核进行授权后绑定；非新增独立审查',
  'limitations':'REFERENCE_BINDINGS_ONLY_NO_HISTORICAL_EXECUTION；未重跑历史内核或其凭证子项；不证明新订单稳定、不证明收益。包装承载关闭与请求投影同时变化。'}
 validate_schema(review['version'],review)
 rp=put('kernel_applicability_review_APPROVED.json',review)
 bridge={
  'version':'geometry_jev_kernel_bridge_v3','status':'APPROVED',
  **{k:prior[k] for k in ('evidence_receipt','historical_source_manifest','historical_monitor')},
  'target':target,'applicability_review':ref(rp),'validation_mode':'REFERENCE_BINDINGS_ONLY_NO_HISTORICAL_EXECUTION'}
 put('kernel_bridge_APPROVED.json',bridge)
 authorization={'scope':plan['scope'],'plan_digest':EXPECTED,'status':'APPROVED','authority':'user_explicit_chat_authorization','date':'2026-11-22','timezone':'Asia/Shanghai',
  'user_authorization':'我授权在目标 Linux 上按最终计划摘要 f5bb85910e1b44017b19c1ada506b4d48da87f2f74be4e87ce7f6addf42d6f73，单次运行关闭包装承载上限的 GP6-F0 基础订单 G00（E2）和 G01（EMS），使用 jev-1.14.0。允许将每次决策的当前可观察状态与候选动作请求发送至 https://api.typesafe.ai/v1/systemone，我知悉这些数据将离开本机。每项最多 19 次发送保留，合计最多 38 次。驱动内置预检两项全过后才派发，不扩大矩阵，不隐式重试。',
  'jobs':['G00','G01'],'model':plan['model'],'endpoint':'https://api.typesafe.ai/v1/systemone','target_host':'cyw-R7000P','single_execution':True,'per_job_max_sends':19,'shared_max_sends':38,'preflight':'2/2 required','packaging_top_load_limit_enabled':False}
 ap=put('scope_authorization_APPROVED.json',authorization)
 srp=put('scope_review_APPROVED.json',{'scope':plan['scope'],'plan_digest':EXPECTED,'status':'APPROVED','reviewer':'授权后绑定既有独立复核，非新增独立审查','independent_review_reference':ref(qa_path),'source_identity':plan['source_identity'],'release_scope':'G00/G01 on target Linux once after built-in 2/2 preflight','date':'2026-11-22'})
 api=put('api_spec_check_VERIFIED.json',{'status':'VERIFIED','date':'2026-11-22','timezone':'Asia/Shanghai','plan_digest':EXPECTED,'model':plan['model'],'endpoint':'https://api.typesafe.ai/v1/systemone','official_sources':['https://docs.typesafe.ai/models','https://docs.typesafe.ai/api/system-one','https://docs.typesafe.ai/primitives/choice'],'conclusion':'官方公开规格确认固定模型、Bearer认证、三字段JSON和Choice请求响应；未为预检发送探测请求。','model_calls':0})
 admission={'version':'geometry_jev_admission_v2','runtime_version':plan['runtime_version'],'publication_policy_digest':plan['publication_policy_digest'],'scope':plan['scope'],'plan_digest':EXPECTED,'source_identity':plan['source_identity'],'environment_digest':plan['environment_digest'],'monitor_digest':digest(snap),'status':'APPROVED','authorization':ref(ap),'review':ref(srp),'api_spec_check':ref(api)}
 put('order_admission_APPROVED.json',admission)
 assert validate_jev_admission(plan,snap,admission,bridge) is True
 assert not Path(read(BASE/'GEOM_CANDIDATES_GP6_TOP_LOAD_SWITCH_20261122_01/run_layout_DRAFT.json')['run_root']).exists()
 assert not Path(plan['request_ledger_path']).exists() and not Path(plan['call_ledger_path']).exists(), 'REFUSE_REINITIALIZE_LEDGERS'
 GeometryJevRequestLedger(Path(plan['request_ledger_path']).parent,plan_digest=EXPECTED,per_job_max_sends=19,shared_max_sends=38,allow_real_transport=True,runtime_version=plan['runtime_version'])
 CallBudget(plan['call_ledger_path'],plan,evidence='REAL_KERNEL',job_id='INITIALIZATION_ONLY')
 put('preparation_receipt.json',{'status':'PREPARED','plan_digest':EXPECTED,'real_calls':0,'model_calls':0,'kernel_calls':0,'delta_paths':len(delta),'exact_files_unchanged':len(snap['algorithm_identity']['files_sha256']),'independent_review':ref(qa_path),'new_independent_review':False,'authorization':'explicit current user message','next':'one driver invocation with --execute; built-in 2/2 preflight'})
 print(json.dumps({'status':'PREPARED','plan_digest':EXPECTED,'jobs':2,'real_calls':0,'new_independent_review':False}))
if __name__=='__main__':main()
