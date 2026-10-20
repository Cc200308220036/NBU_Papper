# O2a / O1b 独立复核报告

- **复核者及类型**：`agent_independent_audit_20261009`（`reviewer_type: agent_independent_audit`，**不是**人工复核者）
- **模型 / 工具版本**：`deepseek-v4-pro`（复核执行模型）；重算脚本 Python 3.13
- **时间**：`2026-10-09`
- **代码版本**：Git `HEAD = d38f34c9a2bf13974ab01d9c9f78fdc0494ed663`（O1b 新增文件尚未提交，与本轮复核无关）
- **输入目录与文件清单及哈希**（只读，未改动任何 EXP_* 冻结产物）：

| 输入文件 | sha256 |
|---|---|
| `EXP_OPT_O1B_LANGUAGE_PILOT_20261009_03/audit/ast_human_review_queue.csv` | `8f4aeb98…bee990fd` |
| `EXP_OPT_O1B_LANGUAGE_PILOT_20261009_03/metrics/policy_pairs.csv` | `3604890a…560b982958` |
| `EXP_OPT_V3_PROTOCOL_PILOT_20261008_02/audit/old_60_classification.json` | `edcfd34c…84982a2e63` |
| `EXP_OPT_V3_PROTOCOL_PILOT_20261008_02/audit/reviewer_signoff_template.csv` | `708bba8f…ba874e0f8` |

- **复核范围**：O2a **12/12**；O1b **180/180**（A/B/C 各 60）。未抽样、未跳过。
- **方法**：
  1. O1b 首轮只取 `request_id` / `source_order_key` / `track`，遮蔽 `expected_ast`、`resolved_policy`，逐题从 `public_requests/<id>.json` 的 `instruction_text` 与 `available_items[0]` 独立提取硬约束、软优先级与（C 轨）条件分支；未把私有真值 `tasks.private.json` 输入判断模型。
  2. O2a 逐题从旧 V2 pilot 的 `public_request.json` / `response.raw.json` 独立判协议字段与业务硬约束，再对照 `old_60_classification.json` 的自动归因。
  3. 第二轮才比对机器答案。独立重算用脚本从公开文本重新解析规则并核对候选 `contact_pairs` / 目标箱属性，**独立判断**与**程序重算**与**机器原标注**在下方分开标注。

---

## O2a 结论

### 协议错因：确认 8/8，不同意 0，不确定 0

| 类别 | 数量 | 逐题 |
|---|---:|---|
| 多余 `type` 字段（协议要求恰好 7 字段） | 6 | 002_0, 002_1, 003_0, 020_0, 024_0, 026_0 |
| JSON 语法错误（`reason` 后多出 `)`） | 2 | 007_0, 019_1 |

以上 8 题均为协议错误，模型原文无法通过七字段协议解析，自动归因正确。8 题的业务副分类（独立核对，不混称）：

| request_id | 业务副分类 |
|---|---|
| 002_0, 002_1 | `no_semantic_opportunity`（Top-K 16 个候选全部等价，无硬/软差异） |
| 003_0 | `candidate_no_feasible`（硬规则适用但 Top-K 无可行候选） |
| 007_0, 024_0, 026_0 | `feasible_hard_rule_question`（硬规则适用且 Top-K 有解，见下） |
| 019_1, 020_0 | `hard_constraint_not_applicable`（硬约束当前不适用，但软目标仍区分候选，**存在语义机会**） |

其中 019_1、020_0 的“硬约束当前不适用”**不等于**“无语义机会”：两题状态均含重箱，`heavy_low`/`heavy_center` 软目标仍适用，oracle 最优等价集分别为 `{C03}`、`{C07}`（非全部 16 候选），故存在语义机会。协议错误判定不受影响，仍成立。

### 有解硬规则误选：确认 4/4，不同意 0，不确定 0

| request_id | 所选项 | 可行见证 | 关键公开事实（独立核对） |
|---|---|---|---|
| 006_0 | C01 | C08 | `item_05`(general,**heavy**) 与 `item_06`(**electronics**,light) 在 C01 的 `contact_pairs` 中出现 `['item_05','item_06']`，违反“electronics 与重箱禁止面接触”；C08 无该接触 |
| 006_1 | C01 | C08 | 同上（同一物理状态） |
| 027_0 | C02 | C04 | `item_04`(general,**heavy**) 与 `item_09`(**electronics**,medium) 在 C02 中出现 `['item_04','item_09']`；C04 无该接触 |
| 027_1 | C14 | C04 | 同上（同一物理状态） |

4 题所选候选都**新造成**禁止面接触，而同一 Top-K 中存在无该接触的可行候选，故判“可避免硬误选”成立。

### 3 条协议错误也属于“有解硬规则题”（确认）

| request_id | 说明 |
|---|---|
| 007_0 | `hard_applicable=True`，Top-K 有 14 个可行解（oracle=C06,C12）；响应因 JSON 语法错误失效，未提交 |
| 024_0 | `hard_applicable=True`，Top-K 有 15 个可行解（oracle=C09） |
| 026_0 | `hard_applicable=True`，Top-K 有 10 个可行解 |

即这 3 题若协议正确，硬规则本就适用且存在可行候选，模型却交出了无效响应；与“无可行解只能 abstain”的情况不同。

### 自动标签勘误及影响

- **0 条勘误**：12/12 自动标签均与独立判断一致（`automatic_tag_agreement=confirm`）。
- 对旧 pilot 结论的影响：本报告**未发现**需要修改旧 60 题归因或 12 条关键错例结论的证据；旧 V1/V2 原始目录哈希保持不变。

---

## O1b 结论

### AST 全字段一致：180 / 180（confirm），disagree 0，uncertain 0

独立重算从公开指令文本重新解析规则，与机器 AST 逐字段比对，分项计数：

| 分项 | 一致 / 已复核 | 说明 |
|---|---:|---|
| 作用对象（fragile 箱 / electronics-heavy 类别对） | 180/180 | 未把“电子产品”误当当前箱专属条件 |
| 业务硬约束阈值（易碎限载 kg） | 180/180 | 与物理 `top_load_limit` 区分；全部 180 条生效政策均含该规则 |
| 禁止面接触（electronics 与重箱） | 126/180 | 126 条生效政策含该规则，类别对一致、0 错误；54 条生效政策不含该规则（指令也未提及），无对象可错 |
| 硬约束先于软分数 | 180/180 | 优先级排序正确 |
| 软目标优先级（`heavy_low` / `heavy_center`） | 180/180 | 首级不被后级高分抵消 |
| 条件与例外（C 轨分支） | 60/60 | 见下 |

### A/B 同义一致性、C 条件分支正确性

- **A/B 同义一致性**：30 组 × 2 变体 = 60 对，**0 不一致**。B 轨只换说法，AST 与 A 轨逐字段相同。
- **C 条件分支**：60/60 正确。60 条 C 轨题中当前箱 `weight_class=heavy` 有 **32 条**（走 `then` 分支）、非 heavy 有 **28 条**（走 `else` 分支，其中 `light` **14 条**、`medium` **14 条**）；生效政策均与当前箱公开属性一致。**C 轨生效政策不一定等于同组 A0**，已逐题按当前箱属性核查。
- **按独立来源订单汇总**：30 个独立来源订单，每组 A/B/C 三轨。政策最优动作真正变化出现在 **10/30 个独立订单**（`GROUP_011, 012, 015, 016, 017, 022, 023, 024, 028, 030`，对应 30/90 组政策配对，其余 60 组为控制组）。

### 模糊指令、机器真值错误、未评题目

- 模糊指令（`ambiguous`）：**0**。所有 180 题的对象、阈值、分支、优先级均可唯一确定。
- 机器真值错误：**0**。
- 未评题目：**0**（180/180 均有处理状态）。

### 对后续 O2b / 正式测试的影响

1. 机器生成的 180 条规则 AST 经独立逐题核对**无错误**，可作为 O2b 开发集与失败归因起点。
2. 但政策最优动作切换只出现在 **10/30** 个独立来源订单，区分度有限；O2b 应按**独立订单**报告，不能把 30 道机会题当 30 个独立样本。
3. 语言模板、属性、规则目录和状态筛选已在本轮开发被查看，**未来正式 test 必须另取来源并冻结新模板族**，不能复用本开发验证集声称“未见表达”或 VLM 增益。

---

## 分歧及处理

- **两名真人**：尚未安排；本报告为 Agent 独立技术复查，**不构成人工签认**。
- Agent 独立审查发现：**0 条分歧、0 条勘误**；12 + 180 条全部 `confirm`。
- `proposed_corrections.csv`：**不生成**（无确认的标签错误，勘误表按教程仅在存在错误时写入）。
- 未修改任何冻结原始产物（`EXP_1C_*`、`EXP_OPT_V2_PILOT_20260929_04`、O2a `_01/_02`、O1b `_03` 原始请求/响应/私有题目/指标均未改动）。

---

## 验收状态

| 阶段 | 自动核验 | 本次独立复查（Agent） | 双人人工签认 |
|---|---|---|---|
| O2a | PASS（独立程序交叉核验） | **confirm 12/12** | **PENDING** |
| O1b | PASS（发布后独立核验 180/180，0 失败） | **confirm 180/180** | **PENDING** |

- 人工维护工时：**未知**（`maintenance_cost_template.csv` 仍未填；Agent 不推测历史工时，未知保持 `null`，**不填 0**）。
- 明确声明：本报告是**单名 Agent 的独立技术复查**，不能单独证明 VLM 优势，也不是新 test 结果；正式人工 PASS 仍需两名真人的独立记录与仲裁，不能在 `reviewer_a_name / reviewer_b_name` 或 `reviewer_1 / reviewer_2` 栏填虚构人员。

### 下一步处理建议

1. 安排两名真人独立复核，各自复制 `o2a_review_rows.csv` / `o1b_ast_review_rows.csv` 并独立重填，再对齐 `request_id` 合并；Agent 的 `confirm` 可供聚焦，但不能替代。
2. 补齐 `maintenance_cost_template.csv` 工时（由真正参与规则/Parser/提示词开发的人填写）。
3. 在不等待人员的同时，可推进 O2b 受限 AST 输出、同权限强 Parser 与公开解析结果驱动的业务屏障（用于修复 O2a 两道“无可行候选仍误提交”与两道“有解仍误选”的问题）。
