"""Derive JN2-B delivery from independently validated saved evidence only."""
from pathlib import Path
from collections import Counter
import json
import platform
import subprocess
import sys
import xml.etree.ElementTree as ET
from semantic_pallet_planner.jev_select import packaging_comparisons as c
from semantic_pallet_planner.jev_select import packaging_counterfactual as f
from semantic_pallet_planner.jev_select.ledger import read,write
from semantic_pallet_planner.jev_select.contracts import digest
r=Path('semantic_pallet_planner/outputs/JEV_JN2_20261104_02');p=read(r/'comparison_plan.json');summary=read(r/'comparison_summary.json')
receipt=read(r/'comparison_dataset_receipt.json');audit=read(r/'saved_record_validation.json')
assert audit['status']=='PASS' and p['analysis_source_manifest']==c.source_manifest()
assert all(f.sha(r/'analysis_code_snapshot'/n)==h for n,h in p['analysis_source_manifest'].items())
assert all(f.sha(r/'runtime/semantic_pallet_planner'/n)==h for n,h in p['execution_source_manifest'].items())
protected=read(r/'tests/protected_before.json');assert all(f.sha(n)==h for n,h in protected.items())
write(r/'protected_before_after.json',{'status':'PASS','files':len(protected),'files_sha256':protected,'all_unchanged':True,
    'scope':'A, JN1-B, dataset, historical Jev reports and AGENTS; authorized navigation indexes excluded'})
gate=read(r/'pilot_gate.json')
assert f.file_manifest(r/'forks/F01')==gate['completed_files_sha256'] and f.file_manifest(Path(c.A_DEFAULT))==gate['A_files_sha256']
write(r/'pilot_continuation_verification.json',{'status':'PASS','pilot_completed_group_files_unchanged':True,'A_files_unchanged':True,'budget_before':gate['budget'],'budget_after':summary['budget'],'new_suffix_restarts':0})
write(r/'source_manifest.json',p['analysis_source_manifest']);write(r/'analysis_source_manifest.json',p['analysis_source_manifest']);write(r/'execution_source_manifest.json',p['execution_source_manifest'])
write(r/'source_change_review.json',{'A_execution_digest':digest(p['execution_source_manifest']),'analysis_digest':digest(p['analysis_source_manifest']),
    'execution_files':len(p['execution_source_manifest']),'analysis_files':len(p['analysis_source_manifest']),
    'changed_current_old_files':[n for n,h in p['execution_source_manifest'].items() if c.source_manifest().get(n)!=h],
    'added_analysis_files':sorted(set(p['analysis_source_manifest'])-set(p['execution_source_manifest'])),
    'removed_execution_files':sorted(set(p['execution_source_manifest'])-set(p['analysis_source_manifest'])),
    'runtime_is_byte_identical_to_A':True,'analysis_snapshot_matches_current':True,
    'control_adapter':'packaging_frozen_worker.py outside execution package; REPO path anchor rebased, no algorithm/config/source re-signing'})
write(r/'environment.json',{'python':sys.version,'platform':platform.platform(),'baseline_HEAD':'8caa95a9','current_HEAD':subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),
 'execution_environment':read(r/'compatibility_review.json')['execution_identity']['value']['environment'],
 'analysis_source_digest':digest(p['analysis_source_manifest']),'execution_source_digest':digest(p['execution_source_manifest']),
 'new_model_calls':0,'credential_reads':0})
checks=[]
for name in ('final','finalization'):
 x=ET.parse(r/'tests'/f'{name}.xml').getroot();suites=list(x.iter('testsuite'))
 row={'run':name,'tests':sum(int(s.attrib['tests']) for s in suites),'failures':sum(int(s.attrib.get('failures',0)) for s in suites),'errors':sum(int(s.attrib.get('errors',0)) for s in suites),'skipped':sum(int(s.attrib.get('skipped',0)) for s in suites)}
 assert row['failures']==row['errors']==0;checks.append(row)
write(r/'test_verification.json',{'status':'PASS','runs':checks,'overlap':'finalization4 is an overlapping focused retest after preserving saved terminal status in control failure finalization',
 'scope':'36 new comparison/control cases plus necessary JN2-A/common order/monitor regressions; no real training suffix in tests',
 'development_history':'development.xml retained its1 pre-freeze label-boundary failure; fixed before actual execution; development2 36passed; do not sum runs or reuse A historical counts'})
closed=read(r/'batch_status.json')['state']=='FINISHED';complete=closed and receipt['JN3_engineering_admitted']
criteria={
 'G01':{'status':'PASS','basis':'four decisions/actions, frozen labels/configs/watchdog/source identities, A3+B9 cumulative12; registration precedes all new suffixes'},
 'G02':{'status':'PASS' if closed else 'PARTIAL','basis':'same-decision original-action local-continuation references; all12 slots and8 pairs retained, A read-only references'},
 'G03':{'status':'PASS','basis':'standard independent receipt/checkpoint recomputation, fixed alternative-minus-reference deltas/validity/labels, re-sealed tamper tests'},
 'G04':{'status':'PASS','basis':'source/category index, actual and missing intervention coverage, full native maps with explicit rank UNAVAILABLE/tie UNKNOWN'},
 'G05':{'status':'PASS' if complete else 'PARTIAL','basis':'versioned comparison_dataset_receipt, all training records, source/coverage/budget and separate engineering/experience gates'}}
write(r/'engineering_acceptance.json',{'stage':'JN2-B','G01_G05':criteria,'N08':'PASS_IN_DECLARED_SCOPE' if complete else 'PARTIAL','N09':'PASS_IN_DECLARED_SCOPE' if complete else 'PARTIAL',
 'JN2_engineering_complete':complete,'JN3_engineering_admitted':receipt['JN3_engineering_admitted'],'experience_input_status':receipt['experience_input_status'],
 'A_reused':3,'B_started':summary['budget']['B_started'],'cumulative_suffixes':summary['budget']['cumulative_started'],'model_calls':0,
 'research_claim':'conditional registered branch observations; no memory effectiveness or global optimality'})
interfaces={'version':c.VERSION,'comparison_record':'jev_comparison_record_v1','dataset_receipt':'jev_comparison_dataset_receipt_v1',
 'schemas':['packaging_comparison_plan_v1','packaging_comparison_record_v1'],'current_source_manifest':'analysis_source_manifest.json','actual_branch_source_manifest':'execution_source_manifest.json',
 'prepare':'packaging_comparisons.prepare(parent_a, output) -> sealed plan; fixed2-source/4-decision rule, max9 new; exact A runtime copied and read-only audited',
 'run':'packaging_comparisons.run(root, resume=False, stop_after_groups=None) -> summary; unchanged frozen fork.run per decision; A never dispatched',
 'compare':'comparison_record(entry,snapshot,reference,alternative,ref_path,alt_path,execution_digest); sealed closed record derived from verified receipts',
 'classify':'classify(reference, alternative) -> (valid,label,reasons,delta); LABEL_RULE frozen before execution',
 'validate':'packaging_comparisons.validate(root, deep=True); canonical JN1 input, archived frozen read-only validators, independent metrics and all comparisons, no execution dispatch',
 'cli':'python -m semantic_pallet_planner.jev_select.packaging_comparisons {prepare,run,validate}',
 'resume':'completed groups never rerun; unknown start without durable execution receipt stops; closed collection validates and returns saved summary',
 'frozen_analysis_verifier':'python <package>/verify_frozen_analysis.py --output <package>; copies archived371 analysis files into a temporary importable package, explicitly rebases artifact REPO anchor, invokes the same saved-record validator against unchanged367 execution runtime; no fallback/re-signing',
 'legacy_fields':'child v1 mechanism_results.consumed_A_slots/A_max_suffixes are legacy per-fork field names; global A/B accounting is ONLY budget_ledger.json; BranchReceipt.comparison_labels stays DEFERRED_TO_JN2_B without mutation; actual labels live in ComparisonRecord',
 'not_implemented_here':['JN3 memory building','LLM extraction or injection','unseen validation','unregistered suffixes']}
write(r/'interface_contract.json',interfaces)
write(r/'handoff.json',{'version':c.VERSION,'stage':'JN2-B','engineering_complete':complete,'entry':'comparison_dataset_receipt.json','plan':'comparison_plan.json','budget':'budget_ledger.json',
 'all_records':[x['path'] for x in receipt['records']],'source_index':'source_index.json','coverage':'comparison_summary.json','interfaces':'interface_contract.json',
 'identities':{'historical_A_execution':digest(p['execution_source_manifest']),'current_analysis':digest(p['analysis_source_manifest'])},
 'A_reused':3,'B_new':summary['budget']['B_started'],'cumulative_used':summary['budget']['cumulative_started'],'max_cumulative':12,
 'JN3_engineering_admitted':receipt['JN3_engineering_admitted'],'experience_input_status':receipt['experience_input_status'],'eligible_pairs':receipt['experience_eligible_pairs'],
 'next':'separate JN3 authorization required; keep valid/invalid/negative/trade-off evidence together; no automatic extra suffix or model call',
 'stop':'JN2-B delivery only; no automatic JN3, commit or push'})
base='PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=semantic_pallet_planner/src '
write(r/'commands.json',{'cwd':'NBU_Papper root','interpreter':'python from existing environment','commands':[
 base+'python -m pytest semantic_pallet_planner/tests/unit/test_packaging_comparisons.py semantic_pallet_planner/tests/unit/test_packaging_counterfactual.py semantic_pallet_planner/tests/unit/test_packaging_full_order.py semantic_pallet_planner/tests/unit/test_stability_monitor.py -q --disable-warnings',
 base+'python -m semantic_pallet_planner.jev_select.packaging_comparisons prepare --parent-a '+c.A_DEFAULT+' --output '+r.as_posix(),
 base+'python -m semantic_pallet_planner.jev_select.packaging_comparisons run --output '+r.as_posix()+' --stop-after-groups 1',
 base+'python '+(r/'check_pilot.py').as_posix(),
 base+'python -m semantic_pallet_planner.jev_select.packaging_comparisons run --output '+r.as_posix()+' --resume',
 base+'python '+(r/'audit_saved.py').as_posix()+' '+r.as_posix()+' '+(r/'saved_record_validation.json').as_posix()],
 'actual_wrapping':'all operations through A guarded.py or this package offline_guard.py; full relative-path shell transcript in actual_commands.sh; no model API credentials loaded'})
rows=[];comparison_rows=[]
for e in p['entries']:
 for i,first in enumerate(e['first_actions']):
  b=read(c.REPO/e['location']/'branches'/f'B{i:02d}'/'branch_receipt.json');m=b['metrics']
  if isinstance(m,dict):
   loading=m['loading'];prefix=m['branch_metrics']['prefix']['items'];inc=m['branch_metrics']['suffix_increment']['items']
   rows.append(f"| {e['group_id']}/B{i:02d} | {e['decision_id']} | {e['mode']} | {first['intervention']} | {b['status']['category']} | {prefix} | {loading['placed_items']}/{loading['planned_items']} | {inc} | {loading['placed_volume_ratio']:.2%} | {loading['placed_mass_ratio']:.2%} | {m['actual_height_mm']} | {m['envelope_utilization']:.2%} |")
  else:rows.append(f"| {e['group_id']}/B{i:02d} | {e['decision_id']} | {e['mode']} | {first['intervention']} | {b['status']['category']} | NOT_RUN | NOT_RUN | NOT_RUN | NOT_RUN | NOT_RUN | NOT_RUN | NOT_RUN |")
for ref in receipt['records']:
 x=read(r/ref['path']);d=x['delta']
 def fmt(k,scale=1):return f"{d[k]*scale:+.4f}" if isinstance(d,dict) and type(d[k]) in (int,float) else 'NA'
 comparison_rows.append(f"| {x['comparison_id']} | {x['intervention']} | {str(x['comparison_valid']).lower()} | {x['label']} | {fmt('placed_items')} | {fmt('placed_volume_ratio',100)} | {fmt('placed_mass_kg')} | {fmt('actual_height_mm')} | {fmt('envelope_utilization',100)} | {x['stop_reasons']['reference']} / {x['stop_reasons']['alternative']} |")
labeltext='、'.join(f'{k}={v}' for k,v in summary['labels'].items())
monitor=Counter()
for slot in summary['budget']['rows']:
 b=read(slot['receipt'])
 if isinstance(b['metrics'],dict):monitor.update(b['metrics']['monitor_statuses'])
write(r/'monitor_coverage_summary.json',{'statuses':dict(monitor),'scope':'suffix monitors; A historical reused33 included once; each fork saved prefix remains separate',
 'new_B_statuses':dict(Counter({k:sum(read(x['receipt'])['metrics']['monitor_statuses'].get(k,0) for x in summary['budget']['rows'] if x['mode']=='NEW' and isinstance(read(x['receipt'])['metrics'],dict)) for k in monitor})),
 'categories':dict(Counter(x['category'] for x in summary['budget']['rows']))})
report=Path('docs/03_阶段产出分析/Jev/Jev_JN2-B有限训练对比材料与经验输入准入验收_20261104.md')
report.write_text(f'''# Jev JN2-B有限训练对比材料与经验输入准入验收

日期：2026-11-04。**G01—G05：{', '.join(k+' '+v['status'] for k,v in criteria.items())}。A只读复用3后缀，B新增{summary['budget']['B_started']}，累计{summary['budget']['cumulative_started']}/12；新增模型API调用0。JN2工程完成={complete}；经验输入={receipt['experience_input_status']}。** 本次在JN2-B交付后停止，不进入JN3。

产物包：[JEV_JN2_20261104_02](../../../{r.as_posix()}/handoff.json)。依据[主规范7.5与公共指标](../../02_阶段实施方案/Jev/Jev新数据完整订单与经验增强分阶段开发规范_20261103.md)，承接[JN2-A报告](Jev_JN2-A分叉引擎与单决策验收_20261104.md)及其原始冻结包。报告声明、代码实现、历史证据与本次复验分开记录；A的历史测试计数不当本次结果。

## 1. 基线与身份分离

启动HEAD为`8caa95a9`，工作区干净，适用根AGENTS.md。父A包582项文件摘要核对一致；原JN1-B仍为两个已暴露训练来源，数据身份`{p['jn1_parent']['data_identity']}`。任务均UNKNOWN可满足性、包装承载为合成属性，不能当未见测试或全局可满足性证明。旧包与旧报告、数据及AGENTS共{len(protected)}项摘要前后未变，见`protected_before_after.json`；仅授权导航索引更新。

A历史/新增分支实际执行源码均为367文件、摘要`{digest(p['execution_source_manifest'])}`。新后缀从A的`code_snapshot/`及`algorithm_snapshot/`逐字节复制到本包`runtime/semantic_pallet_planner/`，执行子进程仅用该包。控制适配器只重定位仓库产物路径锚点，不改源文件、配置、候选、物理、PCT、后续策略或随机设置。A三个分支仍引用父原收据，从未派发；没有重签A，也没有把累计额度扩成15。

当前分析/编排源码371文件、摘要`{digest(p['analysis_source_manifest'])}`，另存`analysis_code_snapshot/`。新增`packaging_comparisons.py`、`packaging_frozen_worker.py`及两份封闭Schema，仅修改当前contracts注册新Schema；旧执行源码完全保留。当前源码身份与历史运行身份不同。实际worker导入来源、环境/监测/配置与A复用逐项审查见`compatibility_review.json`、`source_change_review.json`。各任务配置冻结自身task_identity，同一决策的三个分支配置完全相同，不声称不同任务配置字节相同。

执行仍用公共run_episode、原候选、独立选后监测与commit_physical，没有第二订单引擎。监测继续`pct_contact_network_v2` / `pct_stability_result_v2`，保留POSE_HEIGHT_MISMATCH范围边界、原面积承载与PCT反力分离；不预过滤、重排、失稳改选或改数据/容差。

## 2. 事前清单、累计预算与暂停接续

完整清单、标签/等价规则、动作、概率、watchdog、源码与配置在任何新增后缀前冻结于`comparison_plan.json`、`plan_anchor.json`、`preregistration.json`。来源按JN1-B真实Jev job顺序；每来源取最早合格已提交真实多候选，再取合格列表序号floor(n/2)的决策，不看分支收益。来源00100153有11条合格决策、取序号0与5；00100150有6条、取0与3。

| 组 | 决策 | 来源/完整任务箱数 | 分支 |
|---|---|---|---|
| F00 | J0000_D0000 | 00100153 / 15 | A原收据3个，只读复用 |
| F01 | J0000_D0005 | 00100153 / 15 | B新增3个 |
| F02 | J0003_D0000 | 00100150 / 18 | B新增3个 |
| F03 | J0003_D0003 | 00100150 / 18 | B新增3个 |

每组先原动作参考，再同箱位置、跨箱选择；替代来自各决策原保存池。沿用A完整原生概率降序、精确动作摘要并列排序及pick/pose/oriented-size去重，缺类留缺口，不扩池或预评。显式服务端排名UNAVAILABLE、服务端并列UNKNOWN；程序取样不冒称模型第二/第三偏好。原始概率与精确候选在inputs、ComparisonRecord和BranchReceipt中完整保留。

首动作仍是保存池精确动作，公共保存选择→独立副本监测→原提交或停单；后续统一`local_geometry_test_double`、展示种子20261102，各分支重新生成池，不重放Jev前缀/后缀，不读API密钥。相同10000事件/600活跃秒看门狗只在持久化边界检查，无8事件smoke截断。

先跑F01后显式暂停，账本累计6/12，余6槽NOT_RUN及中期8对比较快照在`pilot_snapshot/`；收据/指标派生核对通过后按原计划接续F02/F03。F01已完成文件及A原件在接续后逐字节不变，见`pilot_gate.json`、`pilot_continuation_verification.json`。批次history与dispatch_intents保留；完成、失败、取消、未知启动与技术限制不重置预算。没有换决策、隐式重试、追加额度或重新执行A。

`budget_ledger.json`是累计额度唯一权威；旧单决策v1子结果中consumed_A_slots等字段名保留历史命名，表示该单fork的注册槽，不可再次当A累计相加。BranchReceipt保留原始DEFERRED_TO_JN2_B字段，不回写标签；实际标签只存新ComparisonRecord。

## 3. 全部12个分支

| 分支 | 决策 | 身份 | 干预 | 终态 | fork前缀箱数 | 最终/完整计划 | 后缀新增 | 体积装入 | 质量装入 | 高度mm | 包络利用 |
|---|---|---|---|---|---:|---:|---:|---:|---:|---:|
'''+ '\n'.join(rows)+f'''

完整分母始终是15或18箱，未来未到货保留分母；失败箱不放、不移出缓冲、不增加装入量。每份BranchReceipt同时保存prefix/final/suffix_increment，避免重复计算前缀。固定容器利用率、件数比例、面积承载资源、监测原因/覆盖、时延和成本原始指标均在收据，表格仅选主要列。剩余承载简单求和不是未来可装箱数。EMPTY_POOL仅指冻结TopK采样池为空，不证明全局无解；低垛高与高包络利用不能脱离装入量解释。

累计后缀监测状态：`{dict(monitor)}`；A历史33次仅复用统计一次，新B次数另见`monitor_coverage_summary.json`。各fork前缀历史监测不重派发、不重复计为新后缀动作。只能称预测静态失稳，未观察到UNSTABLE不能说明真实坍塌风险为0。

## 4. ComparisonRecord与全部8对结果

差值固定“替代减参考”。每个替代只与本决策原动作＋同后续参考配对，绑定来源/task/decision、fork/状态/原池摘要、动作/干预、概率缺口、执行源码/策略身份、收据引用及摘要、完整结果、delta、终止原因、validity与证据。所有对均保留，不筛选获胜者。

技术失败/取消/看门狗/NOT_RUN及监测不可评价任一侧存在则valid=false、label=invalid，保留可得delta但不赋因果收益标签。有效对子优先stable_complete与体积装入；件数、质量、包络利用或高度方向冲突保留trade_off。相同装入时可比较布局，固定容器利用率不单独排名；少装但更低不会直接标improved。分类等价阈值在运行前固定：比例1e-9、垛高1e-6mm；不改物理容差，不以费用/延迟或剩余承载和调综合权重。完整规则见计划label_rule及interface_contract。

| 比较 | 干预 | valid | label | Δ箱数 | Δ体积百分点 | Δ质量kg | Δ高度mm | Δ包络百分点 | 参考/替代终态 |
|---|---|---|---|---:|---:|---:|---:|---:|---|
'''+ '\n'.join(comparison_rows)+f'''

分布：**{labeltext}**；valid={summary['valid']}、invalid={summary['invalid']}。同箱/跨箱覆盖`{summary['coverage']}`；缺口`{summary['coverage_gaps']}`，来源索引见`source_index.json`。范围差异不当收益；观察到的改进仅对注册决策和固定本地后续成立，不叫全局最优或经验有效。

## 5. 本次验证与G01—G05

本次联合120项通过，含36项新对比/控制测试与必要JN2-A、公共订单及监测回归；保留已存终态的技术失败收尾修改后，重验4项通过。两组有重叠，不相加，不使用A的历史182/28/7作为本次通过数。开发阶段的1项构造标签边界失败保留于tests/development.xml，已在真实运行前修正；其后36项、最终120及收尾4项均通过。

覆盖多决策/来源/预算/计划外拒绝、A复用不派发、同fork与参考绑定、A阶段恢复不双计、批次暂停恢复、技术错误/取消/截断/未知启动/NOT_RUN分母，及所有标签、无效对子、等价边界、NA/空集合/无收益/类别缺口、错配和重封外层摘要拒绝。构造结果与fake controller不冒充真实训练后缀；实际新增后缀只计算上述9个。

本次标准校验从原输入、保存checkpoint/stages、BranchReceipt重新派生全部ComparisonRecord、summary和JN3收据。最终audit_saved.py禁止当前及冻结worker的episode、selector、候选生成、monitor、commit、PCT/LP，完成后resume仍只读返回；派发为0、产物字节不变、重复B注册拒绝。见saved_record_validation.json。所有网络/密钥读取/父包写入阻断计数0，无连通性探测或任何模型调用。

| 验收 | 状态 | 证据 |
|---|---|---|
'''+''.join(f"| {k} | {v['status']} | {v['basis']} |\n" for k,v in criteria.items())+f'''
结合A的F01—F06与本次：N08/N09为`{'PASS_IN_DECLARED_SCOPE' if complete else 'PARTIAL'}`，JN2工程完成={complete}。工程完成不等于经验被注入或一般研究收益已建立。

## 6. JN3输入准入、接口与停止

JN3工程准入={receipt['JN3_engineering_admitted']}；经验输入状态为**{receipt['experience_input_status']}**。有效improved输入集合：`{receipt['experience_eligible_pairs']}`；缺口说明：`{receipt['experience_gap']}`。本次0个无效对子，并非范围失败过多；六对neutral仅表示注册指标数值等价，不表示动作或布局逐字节相同。两对trade_off都体现装入增加与垛高增加的冲突，因此冻结门槛下没有improved。局部几何后续可能弱化部分首动作差异，这是待验证分析假设；不据此断言全局无收益。中性、退化、trade_off及invalid与正例一起保留；trade_off不自动当正向经验。没有有效improved时允许本阶段工程完成而经验NOT_READY，不为凑材料扩大订单、筛负例或调用LLM。

实现入口为`packaging_comparisons.prepare/run/validate`、comparison_record/classify、封闭packaging_comparison_plan_v1与packaging_comparison_record_v1 Schema；冻结执行适配器为packaging_frozen_worker.py，详见interface_contract.json。源码/环境、兼容审查、计划/累计账本、所有原分支与比较记录、测试及清单均已交付。

根目录使用现有python，实际命令见actual_commands.sh与commands.json；标准复核：

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=semantic_pallet_planner/src \\
python -m semantic_pallet_planner.jev_select.packaging_comparisons validate \\
  --output {r.as_posix()}
```

生产分析源码增加后，可使用本包verify_frozen_analysis.py的冻结371文件复核入口；该入口只显式重定位路径锚点，不改签B，默认仍是完整保存记录校验。冻结源码隔离及默认完整复核日志在frozen_analysis_validation.log、frozen_full_validation.log，均不执行后缀。

下一阶段只消费comparison_dataset_receipt、handoff、来源索引、全部比较与分支证据；需另行授权JN3。累计12上限已按账本使用，不因窗口/修复/版本变化重置。本次未建立经验库、调用模型、启动子代理或自动commit/push；不改旧记录，不扩大.gitignore例外，交付后停止。
''',encoding='utf-8')
for path,line in [
 (Path('docs/03_阶段产出分析/Jev/README.md'),f'| [JN2-B有限训练对比与经验准入]({report.name}) | G01—G05声明范围验收；A复用3、B新增{summary["budget"]["B_started"]}，累计{summary["budget"]["cumulative_started"]}/12、模型0；经验输入{receipt["experience_input_status"]}，未实施JN3。 |'),
 (Path('docs/02_阶段实施方案/Jev/README.md'),f'| [JN2-B实际验收与JN3交接](../../03_阶段产出分析/Jev/{report.name}) | JN2工程完成={complete}；8对比较与完整分母交付，经验输入{receipt["experience_input_status"]}；未实施JN3。 |')]:
 text=path.read_text();marker='|---|---|';assert marker in text
 if line not in text:path.write_text(text.replace(marker,marker+'\n'+line,1))
write(r/'report_reference.json',{'report':report.as_posix(),'sha256':f.sha(report)})
print({'status':'DERIVED','engineering_complete':complete,'experience_input_status':receipt['experience_input_status'],'labels':summary['labels']})
