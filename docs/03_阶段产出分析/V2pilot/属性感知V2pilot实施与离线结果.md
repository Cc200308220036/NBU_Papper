# 属性感知 V2/pilot 阶段产出与实验进展

> 更新：2026-10-06。本文根据本地代码和 `EXP_OPT_V2_PILOT_20260929_04` 的原始记录整理。实验只使用 validation 开发数据，不是未见 test 的论文结论。本文此前“Flash 未运行”的描述已失效，现以真实调用记录为准。

## 当前进度

阶段 1C 的 V1 固定候选实验已保留。本轮完成 O0（V1 原始产物复核）、O1（独立属性评价器、规则 AST、13 个手算微场景和 60 道 V2 固定题）以及 O2 小规模矩阵的 **60 次真实 DeepSeek Flash Direct-Text 调用**。离线工程检查通过；远程请求均有记录，但模型协议合法率为 **52/60＝86.67%**，低于预设的 ≥98% 门槛。在这批规范化指令题上，Flash 的业务结果弱于同权限公开规则解析器，尚无“VLM 改善属性放置”的证据。

这轮实质改进是将物理安全、业务硬约束与软偏好分层，并记录每步载荷、接触、重箱位置、优先级遗憾、可行候选覆盖和无效响应。实验仍是**固定候选逐题选择**；尚未验证完整订单的在线布局收益。

## 代码与数据链路

新增代码均位于 `semantic_pallet_planner/src/semantic_pallet_planner/`。V1 的物理候选生成器和旧指标没有改写。

| 模块 | 本轮职责 |
|---|---|
| `evaluation/attribute_metrics_v2.py` | 由位姿独立重建支撑关系、间接载荷、面接触与属性原始量；记录 before/after/delta，分开物理承重与业务限载。 |
| `evaluation/policy_v2.py`、`schemas/policy_v2.schema.json` | 冻结规则 AST，评价易碎箱累计业务限载、电子品/重箱禁止接触、重物低位与靠中心的两级优先级；计算可行集合、等价最优集合和 regret。 |
| `selectors/instruction_parser_v2.py`、`selectors/policy_executor_v2.py` | 从公开指令解析同一批规则并确定性执行；提供同权限强 Parser 对照。 |
| `vlm/pilot_protocol_v2.py`、`schemas/pilot_request_v2.schema.json` | 构造 Text 请求、扫描泄漏；严格绑定 request_id、state_hash、policy_digest，只允许选择展示编号或 abstain。 |
| `runners/pilot_micro_v2.py` | 13 个带手算期望值的微场景，核对直接/间接载荷、接触对、旧违规恶化、等价解、无目标、无可行解和政策切换。 |
| `runners/attribute_pilot_v2.py` | O0/O1/O2 生成与执行，原始请求/响应留存、指标、Schema、泄漏、独立物理检查、回放及续跑校验。 |
| `evaluation/replay_values_v2.py` | 修复 Python 3.13/3.11 浮点末位差导致的误拒绝：仅有限浮点用绝对容差 1e-9，绑定字段、类型、数量、顺序和 N/A 仍精确比较。 |

实际链路：**validation 来源订单 → 真值物理状态（buffer_size=1）→ 原生成器 Top-K≤16 → 两条不同公开指令共享状态/候选/展示编号 → 六方法选择或 abstain → 独立评价与回放**。非特权方法均用相同的公开状态、属性、候选关系事实和指令；隐藏 AST、Oracle 分、未来箱体、真实候选 ID 映射不进入模型请求或公开解析器。语义属性和承载能力是合成/派生值，不代表实测损伤概率。

Git 父提交为 `ec680ed48614adb2cf6c1392e5d5faae59de118c`。新增 V2 源码、测试和本文目前仍是未跟踪文件，`outputs/` 被 `.gitignore` 忽略；**本次新产出尚未提交或上传 Git**。`_04/manifest.json` 的逐文件 SHA-256 和 `_04/code_snapshot/` 才准确标识这批结果的工作区代码版本，不能只用父提交代表新增代码。

## 实验目录与 O0 复核

| 目录 | 用途与状态 |
|---|---|
| `EXP_OPT_V2_PILOT_20260928_01`、`_02` | 开发检查；`_02` 留存早期 pytest 同名文件收集失败。 |
| `EXP_OPT_V2_PILOT_20260928_03` | 首个完整离线 pilot；跨 Python 版本精确浮点回放曾误报失败，保留原产物。 |
| `EXP_OPT_V2_PILOT_20260929_04` | 从 `_03` 兼容分支建立，冻结数据及初始决策逐字节相同；本次真实 Flash 调用和分析的主目录。 |

O0 从 `EXP_1C_DEEPSEEK_FLASH_FINAL_V1` 的原始 steps、逐题 CSV、配置、manifest、验收和回放报告确认 **360 题、6 方法、2160 条决策**。原 utility 与 Oracle 排序复算通过，V1 全目录 **5059 个文件未变**。事后诊断单独保存在 `_04/o0/`，不覆盖旧结果。V1 的 `fragile_protect` 是软语义分，不能等同于 V2 的累计业务限载成功率。研究者人工签认尚未完成。

## O1 数据与候选覆盖

本轮共 **30 个不同物理状态、60 道双政策固定题**，但这些状态只来自 **10 个来源订单**，未达到原计划的 30 个独立来源订单。同一物理状态的两题共享 Candidate Set 和展示编号，仅指令、request_id 和 policy_digest 不同。划分审计未发现跨划分来源重合，所有题在调用模型前保留，不按答案筛题。主要统计按来源订单聚类，不能把 60 题当 60 个独立订单。

| 候选覆盖分层 | 题数 | 含义 |
|---|---:|---|
| 有语义机会且候选内可满足 | 38 | 可比较选择器是否利用指令。 |
| 无语义机会 | 12 | 目标不存在或候选等价；不能证明语义能力。 |
| 全枚举有解而 Top-K 漏解 | 0 | 此类生成器截断错误本轮未出现。 |
| 当前生成器全枚举无解 | 10 | 必须保留为无法满足，不代表连续空间必然无解。 |

有适用业务硬约束的 34 题中，仅 24 题在 Top-K 内有业务可行项，覆盖率 **24/34＝70.59%**；这是按全 34 题计算硬约束成功率的候选内上限。来源、公开请求、冻结私有标注与覆盖审计见 `_04/data/` 和 `_04/metrics/coverage_report.json`。私有标注只用于评价和特权参考。

## O2 六方法同题结果

下表来自 `_04/metrics/summary.json`。最优等价命中以 42 道有可行解且软目标适用的题为分母；政策配对以 26 组有比较意义的双政策状态为分母。N/A 不记成功。真值规则与 Candidate Oracle 读取隐藏真值，只作**特权参考**。

| 方法 | 60 题输出状态 | 硬约束满足（34题） | 等价最优命中（42题） | 政策配对成功（26组） | 比较成功（52题） |
|---|---|---:|---:|---:|---:|
| Geometry-Greedy | 选 60 | 22/34，64.71% | 14/42，33.33% | 5/26，19.23% | 14/52，26.92% |
| 固定属性启发式 | 选 60 | 24/34，70.59% | 35/42，83.33% | 15/26，57.69% | 35/52，67.31% |
| 公开 Parser＋Executor | 选 50、abstain 10 | 24/34，70.59% | 42/42，100% | 21/26，80.77% | 42/52，80.77% |
| DeepSeek Flash Direct-Text | 选 51、abstain 1、无效 8 | **17/34，50.00%** | **14/42，33.33%** | **6/26，23.08%** | **14/52，26.92%** |
| 真值规则、Candidate Oracle | 各选 50、abstain 10 | 各 24/34 | 各 42/42 | 各 21/26 | 各 42/52 |

“比较成功”是 pilot 冻结的综合选择判定，与硬约束满足率不同，定义及 N/A 见 [指标规范](../../01_技术原理与数据规范/metrics_v2_spec.md)。在 24 道**确有业务可行候选**的硬规则题上，Flash 满足 17 道（70.83%），公开 Parser 和固定属性策略均为 24 道。Flash 在 27 道有定义的“可避免新增违规”题中有 7 道新增违规（25.93%）；该分母受无效/abstain 影响，不宜直接与其他方法的条件均值比较。Flash 实际提交的 51 个选择均通过独立物理复核，物理违规为 0；无效响应没有提交，也不能算成功。

以**来源订单**为簇的探索性配对 bootstrap：Flash 相对公开 Parser 的硬约束成功差为 **−26.04 个百分点**，95% 区间 **[−54.17, −4.17]**（34 题、8 个适用来源组）；比较成功差为 **−53.70 个百分点**，区间 **[−74.07, −31.48]**（52 题、9 组）。它先按来源组汇总，所以未必等于上表题级百分比之差。来源组少、每题远程模型仅调用一次、属于 validation 开发期且未做正式多重比较校正；这些区间用于诊断，不是未见 test 的确证推断。

可复查个案：`V2_PILOT_005_0/1` 中 Flash 两题都命中等价最优，而 Geometry 两题均未命中；`V2_PILOT_003_1` 在当前候选无业务可行项时，Flash 与公开 Parser 都 abstain；`V2_PILOT_003_0` 同样无解，但 Flash 多输出字段而被协议拒绝。逐题值及 regret 见 `_04/metrics/per_decision.csv`，案例索引见 `_04/audits/case_audit.csv`。个案不能替代整体统计。

## 远程响应、用量与失败原因

Flash **实际请求 60 次，60 次均有模型记录**；其中 52 次符合严格协议，8 次 `invalid_response`，本轮无自动修复或几何回退。8 次错误包括：6 次多输出协议禁止的 `type` 字段，2 次 JSON 语法错误。原始响应的 `finish_reason` 均为 `stop`，没有证据指向 token 截断。原文及错误类别可在 `_04/selector_inputs/flash_direct_text/<request_id>/response.raw.json` 和 `error.json` 核对。协议校验保证错误绑定或新坐标不会直接执行；后续若改受限 JSON 输出或增加一次修复，须另起 validation 版本，分别报告原始与修复后合法率。

本轮输入 **688,778 token**、输出 **15,162 token**，合计 703,940；单次时延 p50 **1.49 秒**、p95 **2.09 秒**。实验未保存可核实单价或账单，`actual_cost` 与 `estimated_cost` 均为 `null`，**不可记作 0 元**。调用读取环境变量 `DEEPSEEK_API_KEY`，密钥没有写入文件。用量和时延见 `_04/metrics/cost_summary.json`。

## 验收与研究结论

`_04/validation_report.json` 为 PASS：13 个手算微场景、60 题 Schema、360 行六方法指标回放、882 次候选独立物理检查、30 组双政策检查，泄漏命中 0；预续跑回放和最终完整性检查也为 PASS。Python 3.11 兼容修复后 **93 项 pytest 通过**；旧误差有 550 处浮点末位差，最大 `1.1369e-13`，无非数值差异，修复未新增 API 请求或改写 V1。实际命令与日志见 `_04/checks/commands.json`、`replay_fix_status.json`。

`_04/acceptance_report.json` 的 `offline_engineering_status=PASS` 表示离线数据/代码/回放检查通过；`O2_remote_status=COMPLETE` 只表示请求完成，**不表示模型达标**，因为 `model_response_98_percent_gate=false`。O0 人工签认仍待完成；O1 的 30 个独立来源订单要求未满足。研究层面：公开 Parser 在当前规范语法和候选集内达到特权参考上界，而 Flash Direct-Text 本轮没有相对强同权限基线的优势。H1/H2 正式状态仍为**证据不足**；H3 在线布局、H4 视觉、H5 记忆均未测试。不能把这批题推广到自由语言、未见政策或真实机器人执行。

下一步优先：① 补至少 30 个**独立来源订单**的 validation 数据，构造规范语法之外但公开可解释的组合/例外与政策切换，保持强 Parser 对照；② 在新目录验证受限输出协议和一次修复，解决 6 次额外字段和 2 次 JSON 错误；③ 对有效但选错的 Flash 响应归因到指令解析、载荷/接触/距离数值推导、优先级和候选覆盖。只有确认数值推导是主要瓶颈，才增设“Flash 解析受限 AST＋确定性执行器”的独立对照。旧 60 题上的调后结果不能当未见测试。

正式试验的样本量、重复数和预算**尚未冻结**。`_04/formal_test_recommendations.json` 用仅 8 个适用来源组的方差，按 5 个百分点目标和简化正态近似粗估 **482 个独立组**；它与文件中的 60–150 组暂拟预算情景不一致，现有来源数和每题一次调用不足以可靠估功效或重复方差。60/100/150 组 × 两政策 × 1/3 次远程重复，对应 **120–900 次**请求，仅供预算讨论，实际金额未知。先在新的独立 validation 来源组估计效应、失败率和组间/重复方差并核实单价，再于观察任何新 test 前冻结主终点、组数、重复次数、阈值及预算。

## 原始产物入口

以下文件相对仓库根目录，实验目录当前只在本机、受 Git 忽略规则保护。

| 内容 | 入口 |
|---|---|
| 指标定义 | [metrics_v2_spec.md](../../01_技术原理与数据规范/metrics_v2_spec.md) |
| 代码版本与来源哈希 | [manifest.json](../../../semantic_pallet_planner/outputs/EXP_OPT_V2_PILOT_20260929_04/manifest.json) |
| V1 复核与保护 | [verification.json](../../../semantic_pallet_planner/outputs/EXP_OPT_V2_PILOT_20260929_04/o0/verification.json)、[v1_preservation.json](../../../semantic_pallet_planner/outputs/EXP_OPT_V2_PILOT_20260929_04/o0/v1_preservation.json) |
| 来源/划分与候选覆盖 | [split_audit.json](../../../semantic_pallet_planner/outputs/EXP_OPT_V2_PILOT_20260929_04/data/split_audit.json)、[coverage_report.json](../../../semantic_pallet_planner/outputs/EXP_OPT_V2_PILOT_20260929_04/metrics/coverage_report.json) |
| 逐题与案例审计 | [per_decision.csv](../../../semantic_pallet_planner/outputs/EXP_OPT_V2_PILOT_20260929_04/metrics/per_decision.csv)、[case_audit.csv](../../../semantic_pallet_planner/outputs/EXP_OPT_V2_PILOT_20260929_04/audits/case_audit.csv) |
| 方法汇总与配对比较 | [summary.json](../../../semantic_pallet_planner/outputs/EXP_OPT_V2_PILOT_20260929_04/metrics/summary.json)、[paired_cluster_ci.json](../../../semantic_pallet_planner/outputs/EXP_OPT_V2_PILOT_20260929_04/metrics/paired_cluster_ci.json) |
| 费用、验收与回放 | [cost_summary.json](../../../semantic_pallet_planner/outputs/EXP_OPT_V2_PILOT_20260929_04/metrics/cost_summary.json)、[acceptance_report.json](../../../semantic_pallet_planner/outputs/EXP_OPT_V2_PILOT_20260929_04/acceptance_report.json)、[validation_report.json](../../../semantic_pallet_planner/outputs/EXP_OPT_V2_PILOT_20260929_04/validation_report.json) |

`_04/pilot_report.md` 与 `_04/compatibility/README.md` 仍保留远程调用前的“尚未调用”历史表述；当前远程状态请以其后的原始指标、验收文件和本文为准。冻结实验目录不为修正文案而改写。
