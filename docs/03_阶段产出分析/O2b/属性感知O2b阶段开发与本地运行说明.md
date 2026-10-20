# O2b 受限 AST 核心对照：开发产出与本地运行说明

> **2026-10-11 结果更新**：以下“待真实调用”和续跑命令是 2026-10-09 的历史操作说明，现已完成，无需再次对 `_05` 运行付费命令。最终 `acceptance_report.json`：`offline_engineering_status=PASS`、`remote_matrix_status=COMPLETE`、`remote_matrix_engineering_status=PASS`、`o2b_full_acceptance=PENDING_STATISTICAL_DESIGN`；1080/1080 条独立回放通过，已提交物理违规 0。Flash AST＋Executor 与 Public Parser＋Executor 在这批已公布语法上均为 0/111 可避免的原始业务硬违规、最优等价率 100%，没有观察到模型相对强 Parser 的增益。当前决定进入 O3 框架开发，费用不再是本阶段记录或验收要求；见[O3在线码垛框架与论文创新验证路线](../../02_阶段实施方案/O3/属性感知O3在线码垛框架与论文创新验证路线.md)。旧产物及本文历史命令保留作追溯。

> 2026-10-09。本文记录本轮**已经完成的离线开发**和**尚待真实 DeepSeek 调用**的事项。数据沿用 O1b `_03` 的原 train 派生开发验证集，不是新的未见 test；未改写 V1、O2a、O1b 原目录。

## 现在的结论

O2b 的代码、六方法运行框架、受限 AST 协议、共同确定性执行器、公开业务提交屏障、逐题记录、来源订单聚类比较及独立回放已经实现。最终冻结离线目录为 [`EXP_OPT_O2B_AST_PILOT_20261009_05`](../../../semantic_pallet_planner/outputs/EXP_OPT_O2B_AST_PILOT_20261009_05)。其 [`acceptance_report.json`](../../../semantic_pallet_planner/outputs/EXP_OPT_O2B_AST_PILOT_20261009_05/acceptance_report.json) 目前为 `offline_engineering_status=PASS`、`remote_matrix_status=PENDING_REAL_DEEPSEEK_CALLS`、`o2b_full_acceptance=PENDING`。因此**不能说 O2b 全项验收完成，也不能说 Flash/VLM 在 O2b 已有优势**。

同日前缀 `_01`～`_04` 是开发迭代输出，不用于后续付费续跑或对外结论；请只在 `_05` 上执行下文命令。

这批公开指令属于已公布的受限语法。充分开发的公开 Parser 在 180 题上与真值 AST Executor 完全一致。该结果表明这个子域内确定性解析已经很强；Flash 的价值需要通过真实调用、语言变化和后续新的独立测试来判断，不能预设其胜出。

## 代码与数据如何连接

入口是 [`attribute_o2b.py`](../../../semantic_pallet_planner/src/semantic_pallet_planner/runners/attribute_o2b.py)。它只读取 O1b `_03` 已冻结的 30 个独立来源订单、180 道 A/B/C 题及对应公开请求，核验请求 Schema、`state_hash`、`policy_digest`、候选共享关系、来源和文件 SHA256。每题使用原有 Top-K=16 候选、真值状态、`buffer_size=1`。

六臂为 Geometry-Greedy、固定属性启发式、公开 Parser＋Executor、Flash Direct-Text、Flash Policy-Parser＋**同一 Executor**、真值 AST＋同一 Executor。真值 AST 只进入离线评价；公开解析器和两种 Flash 输入只有相同公开状态、属性、候选关系事实与指令。两种 Flash 分别使用直接选择协议及新增 [`policy_protocol_o2b.py`](../../../semantic_pallet_planner/src/semantic_pallet_planner/vlm/policy_protocol_o2b.py) 的受限 AST 协议。后者只接受本轮公布的易碎业务限载、电子品与重箱禁止面接触、重箱低位/靠中心两级优先级及当前箱是否为重箱的条件分支；拒绝额外字段、任意代码、错误绑定和域外 AST。格式错误最多修复一次，修复请求只携带公开请求和错误码，不回显模型原文。

每个非特权方法均保留**原始提议**。提交前，同一个公开 Parser 得到的业务硬规则仅作拦截：提议违规则记录 `screen_intervened` 并 `abstain`，不会替模型改选更优候选。因此 `raw_avoidable_hard_wrong`、原始最优等价命中、AST 准确率反映方法本身；`committed_*` 反映加屏障后的实际提交。Direct 的数值/关系错误只能通过选中候选的可复算事实诊断，不能仅从其 `reason` 推断内部推理过程。

产物可从以下文件快速查看：

| 文件 | 用途 |
|---|---|
| [`manifest.json`](../../../semantic_pallet_planner/outputs/EXP_OPT_O2B_AST_PILOT_20261009_05/manifest.json) | Git 父提交、工作树源码 SHA256、O1b 输入 SHA256、Prompt 与运行约束；源码摘要优先于父提交识别本次未提交代码 |
| [`metrics/per_decision.csv`](../../../semantic_pallet_planner/outputs/EXP_OPT_O2B_AST_PILOT_20261009_05/metrics/per_decision.csv) | 1080 条计划行，含原始提议、屏障、提交结果、业务/几何指标、AST 与 API 状态 |
| [`metrics/summary.json`](../../../semantic_pallet_planner/outputs/EXP_OPT_O2B_AST_PILOT_20261009_05/metrics/summary.json)、[`metrics/per_track.csv`](../../../semantic_pallet_planner/outputs/EXP_OPT_O2B_AST_PILOT_20261009_05/metrics/per_track.csv) | 各方法总体与 A/B/C 分轨结果，显式分母和 N/A |
| [`metrics/policy_pairs.csv`](../../../semantic_pallet_planner/outputs/EXP_OPT_O2B_AST_PILOT_20261009_05/metrics/policy_pairs.csv)、[`metrics/paired_cluster_ci.json`](../../../semantic_pallet_planner/outputs/EXP_OPT_O2B_AST_PILOT_20261009_05/metrics/paired_cluster_ci.json) | 同来源订单双政策配对与来源订单聚类 bootstrap；重复视图不算独立订单 |
| [`metrics/coverage_report.json`](../../../semantic_pallet_planner/outputs/EXP_OPT_O2B_AST_PILOT_20261009_05/metrics/coverage_report.json)、[`metrics/cost_summary.json`](../../../semantic_pallet_planner/outputs/EXP_OPT_O2B_AST_PILOT_20261009_05/metrics/cost_summary.json) | 候选可行覆盖、调用/tokens/时延/费用；未知费用为 null |
| [`replay_report.json`](../../../semantic_pallet_planner/outputs/EXP_OPT_O2B_AST_PILOT_20261009_05/replay_report.json)、[`audit/cases.csv`](../../../semantic_pallet_planner/outputs/EXP_OPT_O2B_AST_PILOT_20261009_05/audit/cases.csv) | 独立复算和重点成功/失败案例入口；远程完成后案例会增多 |

## 已核实的离线结果

- O1b 30 个独立来源订单、180 题；Top-K 有业务可行候选 168 题，当前枚举空间无业务可行候选 12 题。无解题保留为 abstain/误提交诊断，不算业务成功。
- 六方法计划记录 1080 条；四种离线方法各 180 条，Flash 两臂各 180 条待调用。提交的物理违规为 0；[`replay_report.json`](../../../semantic_pallet_planner/outputs/EXP_OPT_O2B_AST_PILOT_20261009_05/replay_report.json) 为 `PASS`，失败列表为空。
- 公开 Parser 与真值 AST Executor 的整条政策及分字段准确率均为 180/180，候选内原始最优等价率 100%。这仅说明**在已经公开并用于开发 Parser 的本批语法**上它们一致，不能作为未见语言泛化证据。
- 有业务硬约束且 Top-K 可避免的分母为 111 题。原始可避免硬违规率：Geometry 27/111（24.3%），固定属性 3/111（2.7%），公开 Parser 0/111。全尝试成功率另含无解等适用题，不能把可避免分母与全尝试分母混用。
- A/B/C 每轨只有 10/30 个来源订单形成政策最优集合差异；其余为控制组。几何和固定属性在机会组的配对成功均为 0/10，公开 Parser 为 10/10。Flash 结果目前为 N/A。该机会来源数不足以支撑正式测试的功效结论。
- **未发生真实 DeepSeek 调用**；Flash 的合法率、AST 准确率、业务表现、token、时延和费用目前都是未知，不应读取占位行当作失败率或零费用。

## 你在 `pallet_vlm` 环境中的运行步骤

在项目根目录执行。不要把 API key 填入命令、脚本或仓库文件；交互输入不会回显：

```bash
conda activate pallet_vlm
cd /home/cyw/NBU_Papper
read -rsp 'DeepSeek API key: ' DEEPSEEK_API_KEY
export DEEPSEEK_API_KEY
echo
```

先跑 **12 个远程任务**的付费冒烟：它覆盖首个来源订单的 A/B/C 两政策 × Direct/AST 两臂；格式修复最多使实际 API 请求达到 24 次。`--resume` 会先核验已保存的源码、O1b 数据和逐题回放，拒绝不一致记录：

```bash
PYTHONPATH=semantic_pallet_planner/src python -m semantic_pallet_planner.runners.attribute_o2b \
  --output semantic_pallet_planner/outputs/EXP_OPT_O2B_AST_PILOT_20261009_05 \
  --resume --remote --limit-remote 12
```

检查 [`acceptance_report.json`](../../../semantic_pallet_planner/outputs/EXP_OPT_O2B_AST_PILOT_20261009_05/acceptance_report.json)、[`metrics/summary.json`](../../../semantic_pallet_planner/outputs/EXP_OPT_O2B_AST_PILOT_20261009_05/metrics/summary.json) 以及 `selector_inputs/flash_direct_text/`、`selector_inputs/flash_policy_parser/` 下的公开请求、Prompt、原始响应、解析结果和 attempts。确认绑定、Schema、屏障和费用记录正常后，续跑剩余的远程任务：

```bash
PYTHONPATH=semantic_pallet_planner/src python -m semantic_pallet_planner.runners.attribute_o2b \
  --output semantic_pallet_planner/outputs/EXP_OPT_O2B_AST_PILOT_20261009_05 \
  --resume --remote
```

满额矩阵为 180 题 × 两个 Flash 方法＝**360 个基础请求**，另加最多每题一次格式修复；冒烟中完成的 12 个任务会被复用，不再次请求。供应商/网络错误会保留为本次任务记录，不会静默删除或自动改成成功。程序不会保存 API key；`actual_cost` 没有账单时保持 null，先依据 token/供应商账单记录真实费用。**运行前不要改动 O2b 源码或 O1b 冻结输入**；如确需修改，应新建实验目录并重新生成版本快照，不能在同一目录混用代码版本。

真实矩阵完成后，去掉 `--remote` 再复核一次，不会新增 API 调用：

```bash
PYTHONPATH=semantic_pallet_planner/src python -m semantic_pallet_planner.runners.attribute_o2b \
  --output semantic_pallet_planner/outputs/EXP_OPT_O2B_AST_PILOT_20261009_05 --resume
PYTHONPATH=semantic_pallet_planner/src pytest -q semantic_pallet_planner/tests
```

验收时查看 `acceptance_report.json` 的远程状态、1080 行完整记录、`replay_report.json` 的失败列表和物理违规数，以及 B/C 分轨配对结果。远程矩阵完成只使 `remote_matrix_engineering_status` 成为 PASS；`o2b_full_acceptance` 仍需独立重复、正式样本量功效模拟与预算冻结，因此此时保持 PENDING_STATISTICAL_DESIGN。完整结果仍是**开发验证证据**。如果 Flash Parser 未胜出、Public Parser 仍到达上界，应如实记录该受限语言域不需要模型；若混合方法胜出，也只能归因于语言解释＋确定性执行架构，不能表述成 VLM 数值排序优势。

## 尚未完成与下一步

真实两臂尚未调用，因而 O2b 全项状态保持 PENDING；调用级随机性、真实费用和正式样本量也未可估。完成首轮矩阵后，先按独立来源订单查看 B/C 效应量与区间、API/AST 失败率，再在新的独立调用中估计重复随机性，结合账单做预先声明的功效模拟，冻结正式 test 组数、重复次数和预算。不要把 180 个题目当成 180 个独立订单，也不要利用已查看 test 调参。O1b/O2a 的双人类签认和维护工时状态仍以其原报告为准；本轮自动测试不替代它们。

本轮验证命令：

```text
PYTHONPATH=semantic_pallet_planner/src pytest -q semantic_pallet_planner/tests
→ 114 passed
PYTHONPATH=semantic_pallet_planner/src python -m semantic_pallet_planner.runners.attribute_o2b --output semantic_pallet_planner/outputs/EXP_OPT_O2B_AST_PILOT_20261009_05
→ offline PASS；remote PENDING_REAL_DEEPSEEK_CALLS；full PENDING
```
