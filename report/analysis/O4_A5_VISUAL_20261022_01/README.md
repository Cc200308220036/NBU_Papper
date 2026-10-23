# O4-A5验收补充证据

正式实验：`semantic_pallet_planner/outputs/EXP_O4_A5_VISUAL_20261022_02`。本目录编号`_01`是报告编号，不是中断的实验`_01`。

A5为PASS，完整O4尚未完成。A6实际人工审阅、D真实模型与E扩展单独进行。本轮真实API和网络尝试均为0。

| 文件 | 用途 |
|---|---|
| [evidence.json](evidence.json) | 最终来源/交付/保护/测试汇总；7431份公共输入、3552张PNG全部核验 |
| [audit_corpus.py](audit_corpus.py)、[corpus_audit.json](corpus_audit.json) | 独立遍历旧A/B/C/F原始公开记录，逐项比较20030条引用与全部导出源；不使用生产语料装载器 |
| [pytest.xml](pytest.xml)、[pytest.txt](pytest.txt) | 完整规划器371项通过，包含26项新增测试 |
| [dataset_pytest.txt](dataset_pytest.txt) | 数据集7项通过 |
| [both_modes_transport.json](both_modes_transport.json) | 单箱/三待码真实PNG字节传入fake客户端；重签摘要但换槽位的错图绑定拒绝 |
| [gallery.json](gallery.json)、[public_sample_buffer3.json](public_sample_buffer3.json) | 正式实验样例及公开输入，无参考答案 |
| [render_cli.log](render_cli.log)、[cli_help.txt](cli_help.txt) | 真实render命令执行及帮助；单输入结果为PARTIAL |
| [formal_acceptance.log](formal_acceptance.log)、[corpus_audit.log](corpus_audit.log) | 正式全语料验收与独立审核原始日志 |
| [intermediate_run_note.json](intermediate_run_note.json) | 首批中断说明；不作通过证据 |

`visual_pytest.xml`与`additional_pytest.xml`是局部补测，已被完整371项覆盖，不能再叠加。正式图像的逐图几何/像素和字节重复证据位于实验的`image_consistency.json`，其完整性最终已复算。图像为理想感知公共事实的技术示意图，未做真实图像感知或模型准确率验证。

详细解释见[开发与验收解析](../../../docs/03_阶段产出分析/O4/O4公共图像A5开发与验收结果解析_20261022.md)。
