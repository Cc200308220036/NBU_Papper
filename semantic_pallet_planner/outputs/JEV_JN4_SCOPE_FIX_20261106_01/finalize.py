"""Write the repair receipt/report after the focused offline checks finish."""
import hashlib
import json
from pathlib import Path
import xml.etree.ElementTree as ET

out=Path(__file__).resolve().parent
repo=Path.cwd()
def read(n):return json.loads((out/n).read_text())
def write(n,v):(out/n).write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n')
xml=ET.parse(out/'tests_final.xml').getroot()
suites=[xml] if xml.tag=='testsuite' else list(xml.iter('testsuite'))
tests={k:sum(int(s.get(k,0)) for s in suites) for k in ('tests','failures','errors','skipped')}
guards=read('test_access_guards.json')
assert guards=={'exit_code':0,'network_connects':0,'credential_reads':0}
assert not any(tests[k] for k in ('failures','errors','skipped'))
identity=read('source_identity.json')
receipt={'version':'jev_monitor_scope_fix_receipt_v1','baseline_head':'8f708196','scope':'batch UNASSESSABLE classification only; v9/v10/v11 shared helper',
 'status':'PASS_IN_OFFLINE_REPAIR_SCOPE','tests':tests,'access_guards':guards,'source_digest':identity['source_digest'],
 'criteria':{'mixed_success_then_registered_range':'PASS_V9_V10_V11','unregistered_range_stops_and_resume_does_not_dispatch':'PASS_V9_V10_V11','malformed_terminal_facts':'PASS_FAIL_CLOSED','first_gate_and_granted_resume_scope':'PASS_CONSTRUCTED','unknown_send_and_saved_response_commit_restore':'PASS_CONSTRUCTED','historical_bytes_preserved':'PASS','old_plan_new_source_rejected':'PASS'},
 'monitor_algorithm_or_tolerances_changed':False,'historical_run_changed':False,'new_execution_plan_generated':False,
 'actual_formal_jobs':0,'actual_model_api_calls':0,'remaining_original_slots':29,'old_batch_state':'ERROR_RETAINED','stop':'repair delivered; do not resume old plan or start further experiments'}
write('repair_receipt.json',receipt)
command='PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=semantic_pallet_planner/src python3 semantic_pallet_planner/outputs/JEV_JN4_SCOPE_FIX_20261106_01/run_tests.py'
write('commands.json',{'cwd':'NBU_Papper','environment':'existing python3; no new dependency installation','final_command':command,'final_log':'tests_final.log','junit':'tests_final.xml','final_result':tests,'initial_run':'scope_tests.log/xml: 10 failures from a duplicate reason argument in a new test fixture, 6 integration passes; fixture corrected before final run; batches overlap and are not summed','static_checks':['saved J0006 reason extraction without replay','old run and parent package manifest byte checks','current source and unchanged monitor identity','old plan rejects new source identity','git diff --check'],'preliminary_static_check_note':'first ad-hoc assertion omitted source_admission_ prefix from expected error code; corrected check confirms identity rejection','not_run':['real model calls','credential reads','formal orders','full historical regression/replay','geometry/kernel changes','remaining29','new execution plan','commit/push']})
report=Path('docs/03_阶段产出分析/Jev/Jev_JN4批次监测范围误停修复验收_20261106.md')
prefix='../../../'+str(out.relative_to(repo))
report.write_text(f'''# Jev JN4批次监测范围误停修复验收

日期：2026-11-06；启动HEAD `8f708196`，开始时仅有既有未跟踪`raw/mixed_pallet_boxes/`，未修改。按[修复方案](../../02_阶段实施方案/Jev/Jev_JN4停批误判与高度语义修复方案_20261106.md)仅实施A：批次范围误判修复，未实施高度语义适配B。未启动子代理，不commit/push。

交付：[修复收据]({prefix}/repair_receipt.json) · [实际命令]({prefix}/commands.json) · [源码身份]({prefix}/source_identity.json) · [旧证据复核]({prefix}/saved_evidence_review.json) · [测试日志]({prefix}/tests_final.log)。

## 实现与行为

新增公共 `packaging_experiment.unassessable_reasons_from_checkpoint`，仅读取已结束订单的检查点：要求终止状态、STOP事件和监测状态一致，提取UNASSESSABLE结果的非空原因。成功监测原因不再进入范围白名单判断。空原因、缺失监测、矛盾状态和未正常结束的记录不能获得放行。

`packaging_evaluation_orders._run_plan`（共用v10/v11）和旧 `packaging_memory_pilot.run`（v9）复用该函数。记录无法读取或不合法时按技术失败停止；未知原因仍按原白名单停止整批。完整 `monitor_reasons` 统计保留，未把成功原因加入白名单，未改变Schema或PCT算法。

构造回归中，每个订单先成功提交2箱，再发生已登记的POSE_HEIGHT_MISMATCH：订单停止且失败动作前后状态相同、缓冲保留；批次继续下一job。未知原因在相同成功前缀后仍停止整批，再次调用不派发后续。修复不使原J0006装完，也不允许失败后代选。

## 本机验证

最终独立批次：**{tests['tests']}项通过，failures/errors/skipped均0**。原始JUnit与日志见交付包；该批包括新增范围回归、原v10停止/验证保护、原v11首批/接续/恢复、发送不明、保存响应复用和已提交恢复。网络与凭证入口被阻断，保护计数均0。构造传输中模拟jev-origin记录不构成真实服务调用，原始构造产物位于 `constructed/`。

首轮新测试存在参数命名冲突，10项失败、6个集成用例通过；修复的是测试夹具，随后运行上述最终完整批次，两批不相加。一次临时身份检查的预期错误码漏写前缀，已更正核对；旧计划始终正确拒绝新源码。

实际命令：

```bash
{command}
git diff --check
```

旧J0006只读原因提取为 `{{'POSE_HEIGHT_MISMATCH'}}`，未生成候选、重算监测或回放轨迹。旧运行manifest及父准备1396项、执行接入454项原件摘要一致；原首批PASS及批次ERROR不改写。当前生产身份仅三个运行模块改变，PCT监测配置及算法身份与旧计划完全一致。旧计划校验以 `source_admission_synthetic_plan_runtime_identity` 拒绝当前源码；未重签或新建计划。

## 限制、交接与停止

本轮源码修复、针对性构造验证及历史原件保护通过；真实模型调用0，正式订单0，未跑全量历史测试。原实验仍为6个完整完成、1个UNASSESSABLE、29个NOT_RUN、64次发送，未恢复或追加调用。下方空隙与PCT垂直下落语义差异仍按既有UNASSESSABLE合同处理；不修改候选、容差或平衡求解器。

后续若授权补跑29项，需要独立的补充执行计划和新源码身份，引用原预算消耗及旧槽位证据；不能在旧目录强行resume，不能将旧结果冒充新源码运行。新计划、续跑和高度适配均未实施。本轮交付后停止。
''')
for index,entry in [(report.parent/'README.md',f'| [JN4批次监测范围误停修复]({report.name}) | 仅A修复；v9/v10/v11共用UNASSESSABLE原因提取，最终{tests["tests"]}项构造回归通过；PCT不变、旧记录保留、真实调用0、未续跑29项。 |\n'),(Path('docs/02_阶段实施方案/Jev/README.md'),f'| [JN4批次监测范围误停修复验收](../../03_阶段产出分析/Jev/{report.name}) | A已实现并通过针对性构造回归，PCT高度边界B保留；不新建计划或运行真实订单。 |\n')]:
    text=index.read_text()
    if report.name not in text:index.write_text(text.replace('|---|---|\n','|---|---|\n'+entry,1))
write('handoff.json',{'version':'jev_monitor_scope_fix_handoff_v1','receipt':'repair_receipt.json','source_identity':'source_identity.json','report':str(report),'status':receipt['status'],'stopped':True,'next':'separately authorize supplemental execution integration; do not resume frozen old plan','real_calls':0,'formal_jobs':0})
print(json.dumps({'tests':tests,'report':str(report)},ensure_ascii=False))
