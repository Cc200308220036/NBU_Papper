"""Bind every row of the E5 fault table to executed evidence."""
from pathlib import Path
import xml.etree.ElementTree as ET
from semantic_pallet_planner.o4.common import read,write

WS=Path('/home/cyw/NBU_Papper')
OUT=WS/'report/analysis/O4_E5_DEVELOPMENT_20261026_01'
EXP=WS/'semantic_pallet_planner/outputs/EXP_O4_E5_090_OFFLINE_20261026_06'
faults={r['purpose']:r for r in read(EXP/'audit/faults.json')}
extra={r['purpose']:(name,r) for name in ('extra_fault_audit.json','extra_state_fault_audit.json','nonfinite_fault_audit.json','collision_fault_audit.json') for r in read(OUT/name)['faults']}
invalid={r['case_id']:r for r in read(EXP/'metrics/invalid.json')}
tests=[r.get('name') for r in ET.parse(OUT/'tests_acceptance_v2_final.xml').iter('testcase')]
rows=[]
def row(index,requirement,expectation,checks):
    evidence=[]
    for kind,key in checks:
        if kind=='fault':
            assert faults[key]['passed'];evidence.append({'path':str((EXP/'audit/faults.json').relative_to(WS)),'purpose':key})
        elif kind=='extra':
            name,r=extra[key];assert r['passed'];evidence.append({'path':str((OUT/name).relative_to(WS)),'purpose':key})
        elif kind=='invalid':
            assert invalid[key]['passed'];evidence.append({'path':str((EXP/'metrics/invalid.json').relative_to(WS)),'case_id':key})
        else:
            found=[t for t in tests if t==key or t.startswith(key+'[')];assert found
            evidence.append({'path':str((OUT/'tests_acceptance_v2_final.xml').relative_to(WS)),'test_cases':found})
    rows.append({'spec_table_row':index,'requirement':requirement,'expected':expectation,'status':'PASS','evidence':evidence})

row(1,'区域/指令/能力/坐标/标签/渲染变化后复用旧响应','拒绝绑定失效或不支持约定',[
 ('fault','stale_response_regions'),('fault','stale_response_instruction_text'),('fault','unsupported_capability_version'),
 ('fault','unsupported_coordinate_convention'),('fault','unsupported_placement_convention'),('fault','changed_render_version'),
 ('extra','stale_response_after_label_change'),('extra','stale_response_after_coordinate_change')])
row(2,'图片字节/facts改变或有图响应进入无图请求','字节/独立几何/绑定拒绝',[
 ('extra','image_bytes_changed'),('extra','image_facts_changed'),('extra','image_geometry_changed_even_with_updated_digest'),
 ('extra','stale_response_after_image_attachment_change'),('fault','image_response_into_plain_request')])
row(3,'yaw/候选ID及顺序/槽位/容量/EOS改变后的旧动作','拒绝旧动作，真实状态不变',[
 ('fault','changed_candidate_yaw'),('fault','changed_candidate_order'),('fault','changed_slot_action'),('fault','changed_eos_action'),
 ('extra','stale_action_after_capacity_change'),('extra','stale_action_after_candidate_identity_change')])
row(4,'未知对象/区域、布尔/字符串数值、NaN/Infinity及跨族覆盖','当前或兼容协议明确拒绝',[
 ('invalid','E1_BAD01'),('invalid','E1_BAD06'),('invalid','E1_BAD08'),('invalid','E2_BAD02'),('invalid','E2_BAD03'),
 ('extra','nonfinite_current_protocol_nan'),('extra','nonfinite_current_protocol_inf'),('extra','nonfinite_current_protocol_-inf'),('fault','cross_family_override')])
row(5,'allowed_yaw/180/270/侧面标签/roll/pitch','不支持能力在模型调用前拒绝',[
 ('fault','unsupported_allowed_yaw_ast'),('fault','explicit_unsupported_yaw_instruction'),
 ('test','test_current_scope_refuses_orientation_rules_before_model_call')])
row(6,'只改未到货未来箱','首个决策请求/候选/trace完全一致',[
 ('fault','e5_hidden_future_invariance'),('fault','candidate_public_input_only')])
row(7,'搜索假设克隆被篡改或搜索预算不合法','检出异常，真实状态不变，所有实际trace不越界',[
 ('extra','hypothetical_clone_corruption_detected'),('fault','search_budget_too_small'),('fault','search_clone_and_budget')])
row(8,'合法错误AST漏规则/反方向','按错误AST真实提交，参考检出至少两类违规，无语义修复',[
 ('fault','wrong_ast_drop'),('fault','wrong_ast_direction')])
row(9,'网络错误或修复仍无效','保留原始失败/attempt，无Parser或Oracle回退',[
 ('fault','provider_failure_no_fallback'),('fault','repair_still_invalid_no_fallback')])
row(10,'全局预算不足和多任务恢复','至少两任务/一次恢复，上限及已用不重置',[
 ('fault','global_budget_repair_and_resume'),('fault','budget_increase_on_resume'),('fault','attempt_list_reset_rejected_before_http')])
row(11,'编译ID碰撞或相同输出目录','发送前拒绝，不覆盖已保存响应',[
 ('extra','duplicate_compilation_rejected_before_http'),('extra','existing_output_directory_rejected'),
 ('test','test_plan_full_denominators_frozen_source_and_no_overwrite')])
row(12,'发送前后及提交前后中断','未知尝试保留，已知响应恢复，无重复HTTP或真实提交',[
 ('fault','unknown_attempt_not_resent'),('fault','http_saved_before_commit_resume'),
 ('test','test_crash_after_http_finish_recovers_exact_saved_response'),
 ('test','test_crash_before_actual_commit_resumes_without_second_http'),
 ('test','test_crash_after_saved_place_does_not_repeat_compilation_or_placement')])
row(13,'保存事件/模型回答/参考评分/PNG被改','在独立副本中复算或封存校验检出',[
 ('fault','e5_event_tamper'),('extra','saved_model_response_changed'),('extra','saved_reference_metrics_changed'),
 ('extra','saved_reference_state_changed'),('extra','image_bytes_changed'),('test','test_plan_tamper_detected')])
assert len(rows)==13
write(OUT/'fault_requirement_mapping.json',{'status':'PASS','spec_section':8,'rows':rows,
      'scope':'42 frozen-run fault rows,17 additional checks and named acceptance tests; not independent research samples'})
print({'fault_requirement_rows':len(rows),'status':'PASS'})
