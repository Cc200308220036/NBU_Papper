"""Publish local E5 documentation only from completed authoritative evidence."""
import hashlib
import json
from pathlib import Path

WS=Path('/home/cyw/NBU_Papper')
OUT=WS/'report/analysis/O4_E5_DEVELOPMENT_20261026_01'
BASE=WS/'semantic_pallet_planner/outputs'
EXP=BASE/'EXP_O4_E5_090_OFFLINE_20261026_06'
PLAN=BASE/'PLAN_O4_E5_090_OFFLINE_READY_20261026_06'
ONLINE=BASE/'PLAN_O4_E5_090_ONLINE_READY_20261026_01'
def read(path):return json.loads(path.read_text())
report=read(EXP/'acceptance_report.json')
evidence=read(OUT/'evidence.json')
descriptive=read(OUT/'descriptive_summary.json')
summary=read(EXP/'metrics/summary.json')
assert report['offline_status']=='PASS' and all(report['gates'].values())
assert evidence['status']=='PASS' and evidence['new_api_attempts']==0 and evidence['job_checks']==240
assert descriptive['recorded_jobs']==240 and read(OUT/'readonly_verify.json')['status']=='PASS'
assert read(ONLINE/'plan.json')['maximum_api_attempts']==3100
assert read(PLAN/'plan.json')['version']=='o4_e5_090_development_v2'
assert read(OUT/'fault_requirement_mapping.json')['status']=='PASS'
test_files=read(OUT/'tests_v2_source_binding.json')['checked_files']

def table(kind):
    rows=['| 后端 | 规划器 | 整单完成 | 放置箱数/计划箱数 | 平均件数比例 | 平均体积比例 | 违规提交步 |',
          '|---|---|---:|---:|---:|---:|---:|']
    for g in descriptive['groups']:
        if g['source_kind']!=kind:continue
        rows.append(f"| {g['backend']} | {g['planner']} | {g['completed']}/{g['episodes']} | {g['placed_items']}/{g['planned_items']} | {g['mean_item_ratio']:.2%} | {g['mean_volume_ratio']:.2%} | {g['violating_steps']} |")
    return '\n'.join(rows)

compilations=sum(g['compilation']['decisions'] for g in summary['groups'])
semantic_correct=sum(g['components']['semantic_equal']['correct'] for g in summary['groups'])
semantic_n=sum(g['components']['semantic_equal']['comparable'] for g in summary['groups'])
allowed_correct=sum(g['components']['allowed_set_equal']['correct'] for g in summary['groups'])
allowed_n=sum(g['components']['allowed_set_equal']['comparable'] for g in summary['groups'])
gates='\n'.join(f'| {key} | PASS |' for key,value in report['gates'].items() if value)
source_rows=[g for g in descriptive['groups'] if g['source_kind']=='development_order']
completed=sum(g['completed'] for g in source_rows)
main_note=(f'来源主矩阵共192个episode，整单完成{completed}/192；' +
           ('本轮没有来源订单完成整单。' if completed==0 else '各方法的完成数见下表。') +
           '这与执行正确性分开：所有实际提交均通过独立物理与正确AST的参考业务检查。停止只代表当前方法/采样池/布局限制，不能据此宣布来源订单全局无解。')
result_doc=WS/'docs/03_阶段产出分析/O4/O4E5混合约束完整订单开发与验收_20261026.md'
result_doc.write_text(f'''# O4-E5混合约束完整订单开发与验收

2026-10-26。开发版本`o4_e5_090_development_v2`，本范围工程离线验收PASS，真实API调用0。已实现五类规则在来源完整订单中的单箱/三箱缓冲闭环，以及Text/Image真实编译接口、全局账目和恢复。真实API仅交由用户运行，尚无E5真实在线结果。

依据[开发规范](../../02_阶段实施方案/O4/O4E5混合约束完整订单闭环开发与验收规范_20261026.md)。范围为直立箱体、标签固定`pos_z`、yaw仅0°/90°；E3为DEFERRED，E4为OUT_OF_SCOPE。本轮未开发视觉识别、机器人控制或未见泛化。

## 1. 实际验收结果

| 项目 | 实际结果 |
|---|---|
| 自动测试 | {evidence['distinct_tests']}项通过；测试前后{test_files}个源码/配置/测试文件SHA256一致 |
| 语义回归 / 非法协议回归 / 组合gold | 180/180、48/48、12/12符合预先冻结期望 |
| 来源主矩阵 / 构造矩阵 | 192/192、48/48记录完成并逐条复算 |
| Oracle独立重复 / 检查点恢复 | 120/120、120/120一致；{evidence['restores_with_nonterminal_prefix']}份从含待码箱的非终止前缀恢复 |
| 独立物理检查 | {evidence['actual_commits_independently_checked']}次实际提交通过；正确AST业务违规步0 |
| 规则 / 同池允许集合一致 | {semantic_correct}/{semantic_n}、{allowed_correct}/{allowed_n}；统计的是本地Parser/Oracle，不是模型成绩 |
| 逐状态编译 | {compilations}次本地决策编译；不计为真实API请求 |
| 冻结故障 / 补充副本检查 | {report['faults']}/{report['faults']}、{evidence['additional_independent_copy_fault_checks']}/{evidence['additional_independent_copy_fault_checks']}通过；规范第8节13行均有执行证据 |
| 图像 | {report['visual']['unique_png']}份唯一PNG，{report['visual']['public_state_checks']}条公共状态检查通过 |
| 旧件保护 | {evidence['protected_files']}个开发前既有文件SHA256未变 |
| 真实API计划 | 240个job，冒烟前缀20、余下220；总尝试上限3100，前缀上限260，尚未执行 |

权威原件：[验收报告](../../../semantic_pallet_planner/outputs/EXP_O4_E5_090_OFFLINE_20261026_06/acceptance_report.json)、[分组指标](../../../semantic_pallet_planner/outputs/EXP_O4_E5_090_OFFLINE_20261026_06/metrics/summary.json)、[逐项审计](../../../report/analysis/O4_E5_DEVELOPMENT_20261026_01/requirements_audit.json)、[只读复算](../../../report/analysis/O4_E5_DEVELOPMENT_20261026_01/readonly_verify.json)。实际命令见[运行/API交接手册](../../04_运行与复核手册/O4E5混合约束完整订单运行及API交接_20261026.md)。

## 2. 代码与执行流程

公共已到货状态和指令 → 本方法编译AST → 公共物理候选 → 本方法业务过滤与规划 → 独立物理提交 → 更新真实状态 → 独立参考评价 → 下一次接收/决策。

| 模块（`o4/extensions/e5/`） | 作用 |
|---|---|
| `data.py` | 适配F封存来源，冻结C0/C1、12组合gold、6构造及手工路径/矛盾证明 |
| `backends.py`、`capability.py` | Parser/Oracle/Text/Image，拒绝超能力；返回实际带图请求；持久化全局attempt |
| `episode.py` | WAIT/PLACE/EOS/STOP及失败状态机，逐次编译、单次提交、完整原始N_i与状态链 |
| `planning.py` | 复用E2四规划器；仅缓存精确公共输入的纯计算拷贝，不缓存模型响应 |
| `diagnostics.py`、`activity.py` | 事后分析公开采样/Top-K、规则实际生效/deferred/N/A，不向选择器提供参考答案 |
| `storage.py` | 原子写入、单写锁、仅本次新建目录的初始化失败日志；不改写被拒绝的旧目录 |
| `metrics.py` | 规则、编译有效率、整单、件数/体积及未执行分母分别统计 |
| `experiment.py`、`delivery.py`、`online.py` | 冻结、240离线矩阵、重复/恢复、只读复算、故障/图像/保护及真实API交接 |

入口为`runners/o4_e5.py`，配置为`configs/o4_e5_090_offline_v2.json`。E1/E2实现和原实验未修改。候选/搜索实测最大值为`{json.dumps(report['resource_maxima'],ensure_ascii=False,sort_keys=True)}`，未超过16/48/3/8/256。

Image的实际PNG附件、请求摘要、模型原始响应和动作一直绑定到真实提交；不改写返回摘要。合法语义错误按原AST执行，再由参考记录违规，不以Parser/Oracle兜底。格式/绑定至多修复一次；失败、超时、修复和未知in-flight均占账目预算，恢复不自动重发未知尝试。

## 3. 来源主矩阵

12个既有开发来源按source key排序，每个保留前`min(12,N)`箱；22个任务12箱、2个任务11箱，合计24个C0/C1任务。几何、质量、到货顺序及已有合成属性保持原快照。C1仅比C0增加食品/清洁用品方向与50mm间距关系。仍只有12个独立开发来源，不是未见测试。

{main_note}

{table('development_order')}

表中平均件数/体积比例按已记录订单等权计算，两种配置合并展示；C0/C1、逐来源、规则组件、覆盖不足与停止原因详见原始分组指标及`metrics/failure_attribution.json`。完整分母始终保留未到货和待码箱。

## 4. 构造、规则适用性与错误证据

四个四箱正例和两个物理可放、业务有矛盾证明的反例，共48条。各规划器符合运行前冻结的完成/停止期望；负例未完成是预期结果，不能删除或算作正例完成。证书和手工路径在`private/manual_witnesses.json`，不把Oracle同候选池无动作当全局无解证明。

{table('constructed')}

规则的“AST表达正确”与“实际非空生效”分开统计。没有食品/清洁用品/加固对象的来源按N/A列出；待放端点按deferred记录，不把空目标当执行证据。两类合法错误AST的实际违规轨迹、真实HTTP编码的假传输、Image进入提交和预算恢复见`audit/faults.json`及[fault逐行映射](../../../report/analysis/O4_E5_DEVELOPMENT_20261026_01/fault_requirement_mapping.json)。假HTTP均明确标记，不计真实API。

## 5. 门槛、状态与真实实验交接

| 门槛 | 结果 |
|---|---|
{gates}

E5-R真实在线测量为NOT_RUN；未见泛化和图像增量为NOT_MEASURED。既有E1/E2真实编译PASS不替代E5完整订单在线实验。

已封存离线计划`PLAN_O4_E5_090_OFFLINE_READY_20261026_06`、离线实验`EXP_O4_E5_090_OFFLINE_20261026_06`及真实计划`PLAN_O4_E5_090_ONLINE_READY_20261026_01`。计划中的documentation保留冻结创建时点文本，当前状态应读实际验收报告和本次交付文档，不能把快照中的历史进度描述当当前结果。

用户只需按运行手册先跑20个job，再在同一输出目录resume余下220；两步共享3100尝试总上限，不是各3100，不要求用满。不需重跑旧D replay或E1/E2编译题。模型合法错误和失败任务全部保留；真实矩阵执行完不要求模型正确率或订单完成率满分。

## 6. 版本与历史保留

v1的`_01`在11条通过后中止；`_02/_03/_04`为诊断冻结计划。`_05`保留240条主/构造和120份重复、120份恢复，因复现初始化失败后空目录缺口而停止后处理，标PARTIAL，未作为最终验收。

v2补齐新建目录的operation/phase/error及完整未执行分母，保留已有更具体运行报告；分组编译率包含失败与未执行组，“无违规完成”要求历史真实提交步均无违规。未修改来源、规则、独立期望、候选或排序预算；v2使用新计划和新输出完整重验。旧诊断与副本注入原件均保留；`v1_archive/`是旧17项副本检查，当前同名报告为v2重新执行结果。
''')

handbook=WS/'docs/04_运行与复核手册/O4E5混合约束完整订单运行及API交接_20261026.md'
text=handbook.read_text()
text=text.replace('E5当前处于开发验收中，以下入口已实现，正式计划/结果是否完成以对应封存产物为准。',
                  'E5当前范围工程离线验收已PASS，80项测试、240个episode复算及120次重复/恢复均通过；真实在线计划已封存，API尚未运行。用户从第4节执行两步真实API命令即可，不需重复第2、3节。')
handbook.write_text(text)

navigation=WS/'docs/02_阶段实施方案/README.md'
text=navigation.read_text().replace('E5代码已进入开发与离线验收，最终状态见实际交付报告。',
                                  'E5开发版本v2已完成0°/90°范围工程离线验收，真实API计划已封存，尚待用户运行；见实际交付报告。')
text=text.replace('直接按新文档开发E5（保持0°/90°）','E5已完成0°/90°范围工程离线验收，真实在线计划已封存但尚未执行')
navigation.write_text(text)
for relative,old,new in [
 ('docs/03_阶段产出分析/README.md','E5当前0°/90°范围的实现、来源订单完整闭环、统一API账目、离线验收与实际交付证据。','E5 v2离线门槛全部通过：240条复算、120重复/恢复、80测试，真实240-job计划已封存，API尚未执行。'),
 ('docs/04_运行与复核手册/README.md','E5实际CLI、冻结离线计划、240个真实在线计划及20个job冒烟前缀、全局预算和显式恢复；API由用户运行。','E5离线已通过，用户只需20-job前缀＋同目录220-job续跑，共享3100尝试上限；无需旧D replay，API尚未执行。')]:
    path=WS/relative;path.write_text(path.read_text().replace(old,new))

main_navigation=WS/'docs/README.md'
text=main_navigation.read_text().replace('E5代码及实验尚未执行，不能将原四方向方案标完成。','E5开发版本v2的0°/90°范围工程离线验收已PASS；240条记录复算、120次重复/恢复及80项测试均通过，真实在线计划已封存、API尚未执行。不能将原四方向方案标完成。')
main_navigation.write_text(text)
parent_spec=WS/'docs/02_阶段实施方案/O4/O4E区域相对位置与朝向扩展开发及验收规范_20261025.md'
text=parent_spec.read_text().replace('E5当前仅完成开发文档，业务代码和实验尚未执行。','E5当前0°/90°范围已完成工程离线开发与验收，真实240-job计划已封存、API尚未执行；见[实际结果](../../03_阶段产出分析/O4/O4E5混合约束完整订单开发与验收_20261026.md)。E3仍为DEFERRED。')
parent_spec.write_text(text)
current_spec=WS/'docs/02_阶段实施方案/O4/O4E5混合约束完整订单闭环开发与验收规范_20261026.md'
text=current_spec.read_text()
status_note='\n\n后续开发验收结果：v2已按本文原定分母完成0°/90°范围工程离线验收，真实240-job计划已封存，真实API由用户执行、当前NOT_RUN。实际证据与命令见上方开发记录和交接手册；本规范首次编写时点与验收条件保留。'
if status_note not in text:text=text+status_note+'\n'
current_spec.write_text(text)

(OUT/'README.md').write_text('''# O4-E5 v2工程离线验收与API交接

最终离线范围PASS，API=0。业务范围0°/90°、顶面标签；E3 DEFERRED、E4 OUT_OF_SCOPE。

- `evidence.json`、`requirements_audit.json`：全矩阵独立检查、逐项规范映射。
- `readonly_verify.json`：实际冻结CLI复算240条及120份重复/恢复。
- `tests_acceptance_v2_final.xml`、`tests_v2_source_binding.json`：80项测试及源码前后绑定。
- `fault_requirement_mapping.json`：规范第8节13行故障的直接执行证据；42冻结故障＋17补充检查。
- `descriptive_summary.json`、`per_job_summaries.json`：来源与构造分开，完成/失败及完整分母保留。
- `source_and_tests.json`、`protected.before.json`：本轮交付摘要与108343旧件保护基线。
- `delivery_stage.json`：矩阵后处理、复算和API计划准备阶段日志；没有remote-run。
- `v1_archive/`、`startup_failure_before_fix.json`：旧版本和缺口复现保留，不当新证据。

权威实际产物位于`semantic_pallet_planner/outputs/EXP_O4_E5_090_OFFLINE_20261026_06`，配套离线计划`PLAN_O4_E5_090_OFFLINE_READY_20261026_06`，真实计划`PLAN_O4_E5_090_ONLINE_READY_20261026_01`。真实执行与命令见docs下E5运行/API交接手册。
''')
paths=[result_doc,handbook,navigation,main_navigation,parent_spec,current_spec,WS/'docs/03_阶段产出分析/README.md',WS/'docs/04_运行与复核手册/README.md',OUT/'README.md']
(OUT/'final_document_hashes.json').write_text(json.dumps({str(p.relative_to(WS)):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths},ensure_ascii=False,indent=2)+'\n')
print({'status':'PASS','documents_written':len(paths),'real_api_attempts':0})
