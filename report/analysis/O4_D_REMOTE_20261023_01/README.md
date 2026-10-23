# O4-D工程交付证据

日期：2026-10-23。最终状态：**本地工程验收PASS，真实模型实验NOT_RUN**。

- 正式产物：[`EXP_O4_D_OFFLINE_20261023_03`](../../../semantic_pallet_planner/outputs/EXP_O4_D_OFFLINE_20261023_03/offline_acceptance.json)。
- 工程说明：[开发与离线验收解析](../../../docs/03_阶段产出分析/O4/O4真实模型D工程开发与离线验收解析_20261023.md)。
- 用户执行：[DeepSeek Flash真实API命令](../../../docs/04_运行与复核手册/O4真实模型D运行与验收手册_20261023.md)。

## 最终结果

| 内容 | 结果与证据 |
|---|---|
| 完整规划器回归 | [pytest_final.txt](pytest_final.txt)、[JUnit](pytest_final.xml)：414 passed，0失败，14条已有弃用提示 |
| 数据集回归 | [dataset_pytest.txt](dataset_pytest.txt)：7 passed |
| 新增测试 | 两个test_o4_remote测试文件共43项，已包含于414；局部日志不重复加总 |
| 正式离线矩阵 | [offline_acceptance_final.txt](offline_acceptance_final.txt)：48＋576条固定记录、96个episode，三矩阵D4回放均通过 |
| 实际CLI | [帮助](cli_help.txt)、[prepare](cli_prepare_final.txt)、[run --offline](cli_run_final.txt)、[replay](cli_replay_final.txt) |
| 冻结源码回放 | [snapshot_replay.txt](snapshot_replay.txt)：使用冻结包且禁止写pycache，48条记录回放PASS |
| 旧文件保护 | [legacy_protection.json](legacy_protection.json)：A5冻结清单62948份文件变化0 |
| 四阶段交付核验 | [frozen_deliveries.json](frozen_deliveries.json)：A/B 201、C 1878、F 861、A5 11009项SHA256均一致 |
| 正式封存复制 | [final_delivery.json](final_delivery.json)：3055项文件一致；镜像不是独立重复 |
| 命令语法 | [command_syntax.json](command_syntax.json)：运行手册5段bash命令通过bash -n |
| 全开发计划 | [full_plan_check.txt](full_plan_check.txt)：144固定题、72订单、1152个episode，上限19296次API尝试；仅冻结，未远程运行 |

`offline_matrices_v3/`是实际原始本地运行。为避免旧测试的保护扫描受到并行写入影响，先在报告目录运行，再于完整回归结束后原样封存到正式输出目录。两处是同一批数据，不能合并当作更多独立实验。

三矩阵共868次本地服务替身请求、1119次实际PNG附件传输。在线阶段独立核验2364个事件、1028次物理提交及58608次搜索评价计数。零真实模型API请求，A6本轮不要求。在线六配置仍只来自一个已见开发订单；全部任务及图像收益均不能视为未见泛化或真实模型准确率证据。

## 复现与保留记录

`run_acceptance.py`只使用本地协议服务替身，可在当前版本环境下指定新的输出目录重新执行。真实调用使用手册中的CLI，不能替换替身标志来伪造真实结果。

正式输出`_01`因审计物理缓存恢复缺项中断，`_02`为保护收口前中断；保留原件，不作为最终通过证据。`pytest.txt`、`pytest_v2.txt`等早期中断日志也保留，最终测试依据仅为`pytest_final.xml`及对应日志。
