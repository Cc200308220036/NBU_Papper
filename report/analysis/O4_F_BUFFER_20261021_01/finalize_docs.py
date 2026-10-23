"""Publish verified F status in editable navigation; never touch frozen experiments."""
import json
from pathlib import Path
R=Path('report/analysis/O4_F_BUFFER_20261021_01')
assert json.loads((R/'completion_audit.json').read_text())['status']=='PASS'
assert json.loads((R/'full_rerun_replay.json').read_text())['status']=='PASS'
paths=[Path('README.md'),Path('docs/README.md'),Path('semantic_pallet_planner/README.md'),
       Path('docs/00_总览与指导/README.md'),Path('docs/00_总览与指导/semantic_pallet_planner代码数据与评测现状速览.md'),
       Path('docs/02_阶段实施方案/README.md'),Path('docs/03_阶段产出分析/README.md'),Path('docs/04_运行与复核手册/README.md'),
       Path('docs/02_阶段实施方案/O4/O4阶段任务实现与验收规范_20261021.md'),
       Path('docs/02_阶段实施方案/O4/O4视觉业务语义落地与不确定性约束实验路线_20261021.md')]
for path in paths:
 s=path.read_text()
 s=s.replace('C/F/D未执行','该轮未执行C/F/D；后续C/F已离线验收，D未执行')
 s=s.replace('F/D未执行','F待码缓冲离线验收已通过，D真实模型未执行')
 s=s.replace('F/D待开发','F已离线验收，D待开发')
 s=s.replace('下一阶段为F缓冲，C不需要Flash调用','F缓冲也已完成离线验收，下一阶段补齐A5/A6并推进D真实模型；C/F不需要Flash调用')
 path.write_text(s)
root=Path('README.md');s=root.read_text();marker='- [O4-F 待码缓冲结果]'
if marker not in s:
 lines=s.splitlines();idx=next(i for i,l in enumerate(lines) if l.startswith('- [O4-C 单箱完整订单结果]'))
 lines.insert(idx+1,'- [O4-F 待码缓冲结果](docs/03_阶段产出分析/O4/O4待码缓冲联合规划开发与验收结果解析_20261021.md) · [运行手册](docs/04_运行与复核手册/O4待码缓冲离线运行与验收手册_20261021.md)：F1—F10通过，360条主记录及重复/恢复/完整重跑；启发式17/72、搜索13/72、单箱11/72，退化结果完整保留。')
 root.write_text('\n'.join(lines)+'\n')
p=Path('semantic_pallet_planner/README.md');s=p.read_text()
if 'O4-F待码缓冲结果' not in s:
 s+='\n- [O4-F待码缓冲结果](../docs/03_阶段产出分析/O4/O4待码缓冲联合规划开发与验收结果解析_20261021.md) · [F运行手册](../docs/04_运行与复核手册/O4待码缓冲离线运行与验收手册_20261021.md)：容量1/2/3，正式360条记录；F1—F10通过，API调用0。\n'
 p.write_text(s)
p=Path('docs/README.md');s=p.read_text()
if 'O4当前缓冲闭环' not in s:
 s+='\n13. O4当前缓冲闭环：[F开发与验收结果](03_阶段产出分析/O4/O4待码缓冲联合规划开发与验收结果解析_20261021.md) · [F运行手册](04_运行与复核手册/O4待码缓冲离线运行与验收手册_20261021.md)。F1—F10通过；下一步为A5/A6补齐及D真实模型，不预设搜索优于启发式。\n'
 p.write_text(s)
p=Path('docs/03_阶段产出分析/README.md');s=p.read_text();new='| [O4待码缓冲联合规划开发与验收结果解析_20261021.md](O4/O4待码缓冲联合规划开发与验收结果解析_20261021.md) | F1—F10通过：360条主记录、360次独立重复、360次恢复及360条完整重跑；启发式17/72、搜索13/72、单箱11/72；退化保留，API调用0。 |'
if new not in s:
 lines=s.splitlines();idx=next(i for i,l in enumerate(lines) if l.startswith('| [O4单箱完整订单闭环'));lines.insert(idx+1,new);p.write_text('\n'.join(lines)+'\n')
p=Path('docs/04_运行与复核手册/README.md');s=p.read_text();new='| [O4待码缓冲离线运行与验收手册_20261021.md](O4待码缓冲离线运行与验收手册_20261021.md) | F单箱/容量2/三箱、完整验收、恢复及只读回放；F1—F10已通过，不需Flash；包含历史A/B、C冻结快照回放说明。 |'
if new not in s:
 lines=s.splitlines();idx=next(i for i,l in enumerate(lines) if l.startswith('| [O4单箱完整订单离线运行'));lines.insert(idx+1,new);p.write_text('\n'.join(lines)+'\n')
p=Path('docs/02_阶段实施方案/O4/O4阶段任务实现与验收规范_20261021.md');s=p.read_text();header='### O4-F：待码缓冲与业务约束下的联合规划（新增必做阶段）'
note='当前实施状态（2026-10-22）：**F1—F10离线验收通过**，见[F开发与结果解析](../../03_阶段产出分析/O4/O4待码缓冲联合规划开发与验收结果解析_20261021.md)。六个缓冲模块采用等价的`o4/buffer/`子包组织，四份新schema保留旧协议；360条主记录、独立重复、恢复、完整重跑与独立审核齐全。下列预算及门槛维持原定义。启发式本轮优于有界搜索，完整保留退化订单；D及A5/A6未因此视为通过。'
if note not in s:s=s.replace(header,header+'\n\n'+note);p.write_text(s)
p=Path('docs/03_阶段产出分析/O4/O4待码缓冲联合规划开发与验收结果解析_20261021.md');s=p.read_text()
s=s.replace('日期：2026-10-21。范围：','开发日期：2026-10-21；最终验收日期：2026-10-22。范围：')
s=s.replace('本文在本轮验收过程中建立，最终结果以下文实际验收记录为准；不将F离线结果写作全部O4或真实VLM通过。','**F1—F10离线验收、360条完整重跑及独立逐事件审核全部通过。** 完整O4仍有A5/A6/D等未结项；本轮不构成真实VLM通过。')
audit=json.loads((R/'completion_audit.json').read_text())
text=f"\n\n最终独立审核：{audit['event_checks']}个事件、{audit['independent_physical_checks']}次实际提交物理核验、{audit['independent_reference_commit_checks']}次参考业务复核、{audit['independent_metric_checks']}项核心指标重算、{audit['counted_successor_attempts']}次模拟候选评价计数，全部通过。{audit['protected_files']}个旧文件SHA256变化为0，实际网络尝试及API调用均为0。360条主记录均为新运行，另有360次独立重复、360次中断恢复和360条从空状态完整重跑；来源仍为12个开发订单。\n\n完整证据：[验收汇总](../../../semantic_pallet_planner/outputs/EXP_O4_F_BUFFER_20261021_01/buffer_acceptance.json)、[完整重跑](../../../report/analysis/O4_F_BUFFER_20261021_01/full_rerun_replay.json)、[独立审核](../../../report/analysis/O4_F_BUFFER_20261021_01/completion_audit.json)。\n"
if '最终独立审核：' not in s:s+=text
p.write_text(s)
for name in ('O4属性协议三约束AST与独立评价器开发及产物解析_20261021.md','O4单箱完整订单闭环开发与验收结果解析_20261021.md'):
 p=Path('docs/03_阶段产出分析/O4')/name;s=p.read_text();note='> 后续状态（2026-10-22）：[O4-F待码缓冲开发与验收](O4待码缓冲联合规划开发与验收结果解析_20261021.md)已通过。本文以下保留该轮原范围与历史结论；A5/A6/D仍未完成。'
 if note not in s:
  lines=s.splitlines();lines[1:1]=['',note];p.write_text('\n'.join(lines)+'\n')
p=Path('docs/04_运行与复核手册/O4单箱完整订单离线运行与验收手册_20261021.md');s=p.read_text();note='> 后续状态（2026-10-22）：F已通过离线验收，见[F运行手册](O4待码缓冲离线运行与验收手册_20261021.md)。本工作树新增F模块/schema后，C原回放器的完整源码清单检查会检测到新增项；复核原C实验请在仓库根目录运行`PYTHONDONTWRITEBYTECODE=1 python report/analysis/O4_F_BUFFER_20261021_01/replay_legacy_c.py`。原源码、清单及实验不改写。'
if note not in s:
 lines=s.splitlines();lines[1:1]=['',note];p.write_text('\n'.join(lines)+'\n')
print('Verified F documentation status updated; frozen experiment files untouched.')
