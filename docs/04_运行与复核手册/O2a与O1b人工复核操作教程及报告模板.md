# O2a 与 O1b 复核操作教程及报告模板

> 编写日期：2026-10-09。工作区：`/home/cyw/NBU_Papper`。本教程可交给另一位 Agent 做**独立技术复查**，也可交给两名研究者分别做人工复核。Agent 的结论必须标记为 `agent_independent_audit`；它不能冒充两名不同的人，不能把 `human_double_review` 改为 PASS。两名研究者未独立签认时，O2a/O1b 的人工验收仍为 PENDING。

## 1. 开始前：范围、顺序和保存位置

这次要核对两批不同材料：

| 阶段 | 核对对象 | 数量 | 核心问题 |
|---|---:|---:|---|
| O2a | 旧 V2 pilot 的关键错例 | 12 条：8 条协议错误＋4 条有效但违反可避免业务硬约束；其中 3 条协议错误也属于“有解硬规则题” | 自动归因是否正确，旧模型到底哪里错？ |
| O1b | 新发布的公开业务指令及其形式化规则 | 180 题，来自 30 个独立来源订单、A/B/C 三轨各两条政策 | 自然语言和当前箱属性应当转成什么规则 AST？机器生成真值是否正确？ |

**工作原则：**

1. 只读原始实验产物。不要编辑 `EXP_1C_*`、`EXP_OPT_V2_PILOT_20260929_04`、O2a `_01/_02` 或 O1b `_03` 的原始请求、响应、私有题目和指标。另建复核目录，例如 `docs/05_审计与验收记录/O2a_O1b_20261009/`，存放个人表格、差异清单与最终报告。
2. 两名人类复核者应分别复制模板，独立完成首轮，不交流具体答案；Agent 应在报告元数据写明 `reviewer_type: agent_independent_audit`、模型/工具版本（能获取则写）和复核时间。**任何一位 Agent 的复查均不计作一名“人工复核者”。**
3. 首轮只看公开输入与原始模型输出；O1b 还应遮蔽 `expected_ast`、`resolved_policy` 等答案列。第二轮才比较自动归因或机器真值。保存首轮原始判断，不因看到机器答案而覆盖。
4. 允许借助脚本定位文件、筛选字段和复算数值；报告中把“自己独立判断”“程序重算”“机器原标注”分开。模型 `reason` 是待检查内容，不是真值。遇到歧义，写 `uncertain`，不要猜测。
5. 所有统计同时写**分子、分母和 N/A**；180 道 O1b 题不是 180 个独立订单。对研究结论仍按 30 个来源订单区分，其中仅 10 个订单含政策最优动作切换。

先阅读：[V2 指标与判定口径](../01_技术原理与数据规范/metrics_v2_spec.md)、[O2a 现有验收记录](../03_阶段产出分析/O1b_O2a/属性感知O2a协议修复与验收记录.md)、[O1b/O2a 产出总览](../03_阶段产出分析/O1b_O2a/属性感知O1b与O2a阶段产出总览.md)。这些文件解释规则和目录；**独立首轮逐题判断时不要抄录报告中的自动结论**。

## 2. O2a：逐条核对 12 个旧错例

### 2.1 到哪里找

- 入口与最终签认格式：[O2a `reviewer_signoff_template.csv`](../../semantic_pallet_planner/outputs/EXP_OPT_V3_PROTOCOL_PILOT_20261008_02/audit/reviewer_signoff_template.csv)。该表 12 行，含 `request_id`、`automatic_tags`、`evidence_json`、两名复核者姓名/结论、`resolution` 和 `notes`。每位复核者先另存个人副本，不直接共同编辑原模板。
- 自动证据索引：[O2a `human_review_queue.csv`](../../semantic_pallet_planner/outputs/EXP_OPT_V3_PROTOCOL_PILOT_20261008_02/audit/human_review_queue.csv)；全部 60 题的归因在[`old_60_classification.json`](../../semantic_pallet_planner/outputs/EXP_OPT_V3_PROTOCOL_PILOT_20261008_02/audit/old_60_classification.json)。索引里的 `selected_public_relations`、`feasible_witness_public_relations`、`protocol_error` 是**待核对的程序结论**。
- 每条原始证据来自**旧 V2 pilot**，路径模板：
  - `semantic_pallet_planner/outputs/EXP_OPT_V2_PILOT_20260929_04/selector_inputs/flash_direct_text/<request_id>/public_request.json`
  - `semantic_pallet_planner/outputs/EXP_OPT_V2_PILOT_20260929_04/selector_inputs/flash_direct_text/<request_id>/response.raw.json`
  - 必要时看同目录 `error.json`。模型原文在 `response.raw.json` 的 `raw_text` 字段。
- [独立程序交叉核验](../../semantic_pallet_planner/outputs/EXP_OPT_V3_PROTOCOL_PILOT_20261008_02/checks/old_critical_crosscheck.json)只作第二轮参考，不替代人工判定。

例如 `V2_PILOT_002_0`：先看[公开请求](../../semantic_pallet_planner/outputs/EXP_OPT_V2_PILOT_20260929_04/selector_inputs/flash_direct_text/V2_PILOT_002_0/public_request.json)和[原始响应](../../semantic_pallet_planner/outputs/EXP_OPT_V2_PILOT_20260929_04/selector_inputs/flash_direct_text/V2_PILOT_002_0/response.raw.json)。原响应多出 `type` 字段，因此可独立确认协议字段错误；`no_semantic_opportunity` 是另一项标签，需要另核对候选之间是否真的没有规则差异。

### 2.2 每条题按这个顺序判断

1. **先判协议。**模型应返回可解析 JSON，字段**恰好**为 `schema_version`、`request_id`、`state_hash`、`policy_digest`、`action`、`display_label`、`reason`。前三项绑定值须与公开请求逐字一致；选择动作只能引用请求中给出的 `C01`～`C16` 显示编号；`abstain` 时编号应为 `null`。将多余字段、缺字段、JSON 语法错误、绑定错误分别记录，不能混称“语义错误”。这里判的是**旧 V2 协议**，不要拿 O2a 新 Prompt 的响应替换旧证据。
2. **再判指令。**只从 `public_request.json` 的 `instruction_text` 确定硬约束对象、阈值和软优先级。规则定义见[指标规范](../01_技术原理与数据规范/metrics_v2_spec.md)：易碎箱累计承载与物理承重上限分开；禁止接触只算面接触，边/角接触不算；硬约束优先于任何软分数。
3. **再看候选公共事实。**在 `candidates[]` 中用 `display_label` 找模型所选项和索引所说的可行见证。检查 `public_relations.after.fragile_load_by_item_kg`、`contact_pairs`、重箱底面高度及中心距离；必要时核对 `before`/`delta`，区分已有违规与本次新造成/加重的违规。与 `placed_items`、`available_items` 的 `fragile`、`product_category`、`weight_class` 对上目标箱体。**不要使用隐藏规则 AST、Oracle 分或真实候选 ID 映射作为首轮答案。**
4. **核对错因。**协议错误题：原文是否确实无法通过协议？有效硬误选题：所选候选是否违反适用硬约束，且 Top-K 中是否至少有一个满足所有硬约束的候选？若 Top-K 本来无解，不能判“可避免误选”。软优先级仅在硬可行后比较；无目标属性时记 N/A，不强判成功或失败。
5. **记录结论。**建议个人逐题表有 `request_id`、`raw_response_sha256`、`protocol_verdict`、`business_verdict`、`selected_label`、`feasible_witness_label`、`key_public_facts`、`automatic_tag_agreement`（`confirm`/`disagree`/`uncertain`）、`reason`、`reviewer_id`、`reviewed_at`。写明事实，例如“响应多出 type 字段”或“所选候选新增禁止接触，而见证候选没有该接触”，不要只写“同意”。

O2a 的完成条件是 12/12 条都有两份独立判断、原始依据和对照结论。若有分歧，两份原记录都保留，由研究负责人在 `resolution` 说明裁定和证据；签名不能由 Agent 代填。

## 3. O1b：逐题核对 180 条新规则真值

### 3.1 到哪里找、怎样防止先看到答案

- 入口：[O1b `ast_human_review_queue.csv`](../../semantic_pallet_planner/outputs/EXP_OPT_O1B_LANGUAGE_PILOT_20261009_03/audit/ast_human_review_queue.csv)，共 180 行；[简短复核说明](../../semantic_pallet_planner/outputs/EXP_OPT_O1B_LANGUAGE_PILOT_20261009_03/audit/review_instructions.md)。表内的 `expected_ast`、`resolved_policy` 是**机器生成的待验证答案**。首轮只取 `request_id`、`source_order_key`、`track`，隐藏其余答案列；若写脚本，读取这些 ID 后不要把私有真值传给判断模型。
- 每题的公开请求位于 `semantic_pallet_planner/outputs/EXP_OPT_O1B_LANGUAGE_PILOT_20261009_03/data/public_requests/<request_id>.json`。只看 `instruction_text`、`available_items[0]` 和理解规则所需的公开物料字段。
- 第二轮才打开队列的 `expected_ast`、`resolved_policy`，或[私有题目列表](../../semantic_pallet_planner/outputs/EXP_OPT_O1B_LANGUAGE_PILOT_20261009_03/data/tasks.private.json)核对。`tasks.private.json` 含隐藏真值与评价，**不得被输入到受评模型或首轮独立判断 Agent**。
- 候选和来源可在[来源清单](../../semantic_pallet_planner/outputs/EXP_OPT_O1B_LANGUAGE_PILOT_20261009_03/data/source_manifest.json)、[`policy_pairs.csv`](../../semantic_pallet_planner/outputs/EXP_OPT_O1B_LANGUAGE_PILOT_20261009_03/metrics/policy_pairs.csv)核查。O1b 人工任务的主要对象是“指令→规则 AST”，**不要求两名复核者手算全部 180 题×最多 16 个候选的排名**；候选重算已有独立程序报告。

### 3.2 每条题要独立写下哪些答案

从公开文本提取以下字段，再看机器答案：

| 问题 | 应写出的内容 |
|---|---|
| 作用对象 | 例如所有 `fragile=true` 的箱，或 `product_category=electronics` 与 `weight_class=heavy` 这一对类别；不得把“电子产品”误当当前箱专属条件 |
| 业务硬约束 | 易碎箱累计承载阈值是多少 kg？是否要求电子产品箱与重箱不得面接触？这些与物理限载不同 |
| 业务软目标 | 第一优先级、第二优先级分别是 `heavy_low` 还是 `heavy_center`？前一级不能被后一级高分抵消 |
| 条件与例外（C 轨） | `available_items[0].weight_class` 是否为 `heavy`？应执行“若本次箱为重箱”还是“否则”的政策？两分支及最终生效政策均应记录 |
| 适用性 | 当前状态有无易碎箱、重箱和对应接触对象？规则可以存在但当前目标不适用，N/A 不等于规则不存在 |
| 文本是否明确 | 若对象、阈值、分支或优先级无法唯一理解，标 `ambiguous` 并给出两种解释，不自行补写规则 |

A 轨是规范表达；B 轨换了说法，但同一组同一 `0/1` 变体的 A/B 应对应相同规则 AST。C 轨把两条政策放在“若当前箱是重箱／否则”两个分支；**C0 不一定等于 A0 的生效政策**，必须先检查当前箱属性再决定。例：[O1B_GROUP_001_C0](../../semantic_pallet_planner/outputs/EXP_OPT_O1B_LANGUAGE_PILOT_20261009_03/data/public_requests/O1B_GROUP_001_C0.json) 的当前箱 `weight_class=light`，应走“否则”分支：易碎限载 3 kg、禁止 electronics-heavy 面接触、先靠中心再低位。首轮请先自己判断，再看此示例结论。

建议个人逐题表字段：`request_id`、`source_order_key`、`track`、`policy_digest`、`independent_hard_rules`、`independent_soft_order`、`condition_truth`、`effective_branch`、`applicability`、`ambiguity`、`evidence_text`、`machine_ast_agreement`（第二轮填写）、`disagreement_fields`、`reviewer_id`、`reviewed_at`。180/180 都需有处理状态：`confirm`、`disagree` 或 `uncertain`；不能只抽样却报告“全部复核”。

### 3.3 不要混淆的四件事

- **A/B 文本改写**只改语言，不应改 AST；若不同，先核查指令、再核查机器标注。
- **C 条件分支**是公开当前箱属性选择政策；不准偷看未来箱体或隐藏 AST 来决定分支。
- **无目标/N/A**与**无可行候选**不同：前者是规则当前不适用；后者是当前物理候选中没有满足硬约束的放置。
- 本发布的 O1b 是原 train 来源派生的开发验证集，原 validation 仍只有 10 个来源订单；人工复核不会把它变成未见 test。

## 4. 双人合并、分歧仲裁与 Agent 报告边界

首轮各自完成后，对齐 `request_id` 合并两份 CSV。给出 O2a/O1b 各自的 `两人同意`、`两人都认为原标注错误`、`两人意见相反`、`至少一人不确定`、`未评`数量；逐条列出分歧字段、两人依据、最终裁定者及裁定依据。**不要直接覆盖任何人的首轮判断。**确认标签错误时，在新复核目录写勘误表 `proposed_corrections.csv`，列旧值、新建议、证据和影响范围；不要改旧实验 JSON 或已经冻结的题集。

如果执行者是 Agent：可以输出“Agent 独立审查发现 X 条同意／分歧／不确定”，供人类聚焦复核；不得在原模板的 `reviewer_a_name` / `reviewer_b_name` 或 `reviewer_1` / `reviewer_2` 栏填虚构人员，也不得把自动复算或两个 Agent 运行计为两名人类独立签认。正式人工 PASS 仍需两名真人的独立记录与仲裁。若用户后来修改验收要求，须先在正式 test 之前版本化修订标准，不能倒填当前验收。

[O1b `maintenance_cost_template.csv`](../../semantic_pallet_planner/outputs/EXP_OPT_O1B_LANGUAGE_PILOT_20261009_03/audit/maintenance_cost_template.csv) 是另一项待办：真正参与规则/Parser/提示词开发的人员填写阅读、实现、测试和复核工时。Agent 或复核者不能推测这些历史工时；未知保持 `null`，不填 0。

## 5. 最终希望收到什么报告

请在**新复核目录**交付以下三类文件，原始实验目录保持只读：

1. `o2a_review_rows.csv`：12 行，包含每题旧原文路径/哈希、独立协议判定、业务判定、所选项、可行见证、公开数值依据、与自动标签是否一致、复核者身份类型和待仲裁项。
2. `o1b_ast_review_rows.csv`：180 行，包含首轮独立 AST 字段、C 轨条件分支、第二轮与机器 AST 的逐字段差异、模糊性和适用性；A/B 同义一致性单列。若只有 Agent 复查，写 `reviewer_type=agent_independent_audit`，人类签认列留空。
3. `review_report.md`（或同名 PDF）：给研究负责人快速审阅的总报告，建议按下面模板书写；另附 `proposed_corrections.csv`（若存在）。

```markdown
# O2a / O1b 独立复核报告

- 复核者及类型：姓名或 Agent 标识；human / agent_independent_audit
- 时间、代码版本、输入目录与文件清单及哈希：
- 复核范围：O2a 12/12；O1b 180/180；若未完成写实际分母
- 方法：首轮可见文件、遮蔽字段、使用的指标规范、第二轮比对方式

## O2a 结论
- 协议错因：确认 / 不同意 / 不确定（逐类计数）
- 有解硬规则误选：确认 / 不同意 / 不确定
- 关键逐题证据：request_id、原始响应问题或候选关系数值、可行见证
- 自动标签勘误及可能影响的旧 pilot 结论

## O1b 结论
- AST 全字段一致：x / 已复核题数；对象、阈值、接触、硬软、优先级、条件分支分项计数
- A/B 同义一致性、C 条件分支正确性；按独立来源订单汇总
- 模糊指令、机器真值错误、未评题目及其 request_id
- 对后续 O2b 开发集/正式测试设计的影响

## 分歧及处理
- 两名真人：分别保留原判、仲裁者、最终依据；若只有 Agent，写“待人工签认”
- proposed_corrections.csv 的条数与对应文件；不修改冻结原始产物

## 验收状态
- O2a 自动核验 / 本次独立复查 / 双人人工签认分别是什么状态
- O1b 自动核验 / 本次独立复查 / 双人人工 AST 签认分别是什么状态
- 人工维护工时：已记录 / 未知；不得将未知写成零
- 明确写：本报告不能单独证明 VLM 优势，也不是新 test 结果
```

**报告质量门槛：**任何 `confirm` 都应能追溯到公开请求、原始响应或公开物料关系的具体字段；任何 `disagree` 都应写出建议更正值与影响范围；`uncertain` 不得在总表里算作通过。报告应给出问题清单和下一步处理建议，而不只给“总体通过”四个字。
