# semantic_pallet_planner：代码、数据与评测现状速览

> 更新：2026-10-14。本文以当前代码和已保存的 O1b `_03`、O2b `_05` 原始产物为准。O1b/O2b 是**开发集固定候选实验**；O3 在线属性码垛是下一阶段计划，尚不能写成已完成结果。旧 V1、V2 和 O2b 实验目录保持原样。

## 一句话理解项目

系统先在当前托盘状态下**生成物理上可放的候选位置**，再根据“保护易碎箱、禁止两类箱体接触、重箱放低”等业务指令选一个位置；选择后检查是否违规，并记录结果。现有代码已经能做旧版逐箱在线码垛；最新 O2b 的“语言→规则 AST→确定性执行器→业务屏障”仍运行在**固定的一步候选题**上，尚未接入完整在线订单。

```text
BED-BPP订单尺寸/质量/顺序 + 合成语义属性
  → 场景与当前箱（真值状态，buffer_size=1）
  → 极值点/支撑层生成候选 → 物理过滤 → 多样化 Top-K=16
  → 同一公开请求：自然语言 + 属性 + 候选 + 可复算关系
  → 六种方法各自提出 Cxx 或 abstain
  → 公开规则驱动的业务屏障：违规则拦截，不替方法重选
  → 独立物理复核、隐藏真值评价、逐题统计与回放
```

## 1. 早期阶段做了什么：1A → 1B → 1C

这三个阶段依次解决了“实验能统一运行”“物理候选能可靠生成”“模型能在同一批候选中选位置”。它们均有自动验收通过的原始产物，但 **1C 仍是固定候选的一步决策**，没有证明模型能独立完成整个订单。

### 1A：统一平台与可回放数据链路

1A 将数据读取、当前状态、候选、选择器、执行提交、指标和日志接成统一接口。`FixedCaseRunner` 让不同方法面对**同一道题、同一候选集**；`EpisodeRunner` 按到货顺序逐箱执行，下一步基于已提交状态重新生成候选。公开请求与隐藏评价信息分开，非法候选 ID、过期状态和坐标注入会被协议检查拒绝。主要代码见 [`repository.py`](../semantic_pallet_planner/src/semantic_pallet_planner/repository.py)、[`environment.py`](../semantic_pallet_planner/src/semantic_pallet_planner/environment.py) 和 [`runners/`](../semantic_pallet_planner/src/semantic_pallet_planner/runners/)；阶段说明见[1A–1B 开发说明](阶段1A-1B开发说明.md)。

[1A 原始验收](../semantic_pallet_planner/outputs/EXP_1A_20260912_FINAL/acceptance_report.json)为 `PASS`：30 道 validation 固定题 × 4 方法＝120 条决策，并完成一个 10 箱在线冒烟订单。 [独立回放](../semantic_pallet_planner/outputs/EXP_1A_20260912_FINAL/replay_report.json)覆盖 130 条事件，物理错误和请求泄漏均为 0。它证明了框架接口与复现链路可用；30 道固定题不能证明方法具有跨场景泛化能力。

### 1B：物理候选、几何基线与在线实验

1B 把极值点和已有箱顶支撑位置枚举、`yaw=0°/90°`、物理约束过滤、几何评分和多样化 Top-K 放进统一候选生成器。几何评分综合紧凑度、高度、支撑和均衡；通过 validation 上的 K=4/8/16/32 敏感性分析后，后续实验冻结 **Top-K=16**。还完成了旧版候选行为的回归、候选漏斗与耗时记录、布局图/动画，以及 `lowest`、`geometry_greedy`、`pareto_greedy` 三种在线几何基线。实现见 [`planner/generator.py`](../semantic_pallet_planner/src/semantic_pallet_planner/planner/generator.py) 与 [`planner/constraints.py`](../semantic_pallet_planner/src/semantic_pallet_planner/planner/constraints.py)。这是 EMS-style 实现，并非完整 GOPT 模型。

[1B 原始验收](../semantic_pallet_planner/outputs/EXP_1B_20260912_FINAL/acceptance_report.json)为 `PASS`：360 道固定题 × 4 方法＝1440 条决策；100 个基础场景 × 3 种在线基线＝300 个 episode。几何贪心完成 **100/100** 个选定场景，`lowest` 为 **57/100**，Pareto 贪心为 **50/100**；[独立回放](../semantic_pallet_planner/outputs/EXP_1B_20260912_FINAL/replay_report.json)覆盖 5728 条事件，物理错误和请求泄漏均为 0。这里的完成率只针对当时的订单和代理物理规则，尚未评价“不同属性箱体是否放得合适”。

### 1C：把 DeepSeek Text/Visual 接入固定候选选择

1C 冻结 1B 的物理候选，让随机、几何贪心、Handcrafted Rule、Flash Text、Flash Visual、Candidate Oracle 六种方法回答相同固定题。模型看到公开状态、业务指令和打乱后的 `Cxx` 候选编号；Visual 另看由公开状态渲染的图。适配器将返回编号映射到真实候选，检查响应格式及候选合法性，记录原始回复、修复/回退、耗时与重放结果。链路见 [`stage1c.py`](../semantic_pallet_planner/src/semantic_pallet_planner/runners/stage1c.py)、[`selectors/vlm.py`](../semantic_pallet_planner/src/semantic_pallet_planner/selectors/vlm.py) 与 [`candidate_mapping.py`](../semantic_pallet_planner/src/semantic_pallet_planner/vlm/candidate_mapping.py)。

[1C 原始验收](../semantic_pallet_planner/outputs/EXP_1C_DEEPSEEK_FLASH_FINAL_V1/acceptance_report.json)为 `PASS`：**360 题 × 6 方法＝2160 条决策**，[回放](../semantic_pallet_planner/outputs/EXP_1C_DEEPSEEK_FLASH_FINAL_V1/replay_report.json)无物理违规或公开请求泄漏。历史 `soft_utility` 均值为几何贪心 **0.637921**、Flash Text **0.695990**、Flash Visual **0.698657**、Handcrafted Rule 和 Oracle 均 **0.765367**。这说明两种 Flash 输入在当时的固定题上高于几何贪心；Visual 相对 Text 的差值仅 **0.002667**，不能据此证明图像有独有信息。[协议记录](../semantic_pallet_planner/outputs/EXP_1C_DEEPSEEK_FLASH_FINAL_V1/metrics/protocol_summary.json)显示 Text 最终合法 360/360，Visual 357/360，后者有 3 次回退。Handcrafted Rule 直接读取隐藏结构化规则，Oracle 直接读取候选内参考答案；两者命中 360/360 不代表从自然语言理解了规则，也不是同权限对照。旧 1C 已查看的 test 仅作历史回归，不作为 V2/O3 的未见测试证据。

## 2. 代码按什么顺序工作

| 环节 | 当前主要实现 | 实际做的事 |
|---|---|---|
| 读取数据 | [`repository.py`](../semantic_pallet_planner/src/semantic_pallet_planner/repository.py) | 按 Schema 只读载入场景、固定题和候选；隐藏规则、Oracle 通过单独接口读取。 |
| 管理状态 | [`environment.py`](../semantic_pallet_planner/src/semantic_pallet_planner/environment.py)、[`domain.py`](../semantic_pallet_planner/src/semantic_pallet_planner/domain.py) | 当前只暴露一个到货箱；提交后更新已放箱体，下一步从实际新状态生成候选。此链路属于旧版在线框架。 |
| 生成候选 | [`generator.py`](../semantic_pallet_planner/src/semantic_pallet_planner/planner/generator.py)、[`constraints.py`](../semantic_pallet_planner/src/semantic_pallet_planner/planner/constraints.py) | 对 `yaw=0°/90°` 枚举地面和已有箱顶的极值点；过滤越界、碰撞、托盘超载、支撑不足、重心投影不合格、不可堆叠支撑和传播后物理承重超限；按紧凑、高度、支撑和均衡等几何量评分，返回多样化 Top-K。它是 EMS-style 独立实现，**不是完整 GOPT**。 |
| 公开关系 | [`attribute_metrics_v2.py`](../semantic_pallet_planner/src/semantic_pallet_planner/evaluation/attribute_metrics_v2.py) | 不借用生成器的私有“放置后状态”，而从位姿重建支撑与间接载荷；计算易碎箱承载、重箱高度/中心距离、面接触对及 `before/after/delta`。 |
| 理解规则 | [`instruction_parser_o1b.py`](../semantic_pallet_planner/src/semantic_pallet_planner/selectors/instruction_parser_o1b.py)、[`policy_protocol_o2b.py`](../semantic_pallet_planner/src/semantic_pallet_planner/vlm/policy_protocol_o2b.py) | 公开 Parser 或 Flash 把指令转成受限 AST：硬约束、阈值、软目标优先级和可选的“若当前箱为重箱／否则”分支。未识别语法或非法 AST 明确失败。 |
| 选候选 | [`policy_executor_v2.py`](../semantic_pallet_planner/src/semantic_pallet_planner/selectors/policy_executor_v2.py)、[`policy_v2.py`](../semantic_pallet_planner/src/semantic_pallet_planner/evaluation/policy_v2.py) | 按 AST 逐候选计算：先保留业务硬约束可行项，再逐级比较软目标；同分时比较几何分和公开编号。没有可行项就 `abstain`。 |
| 调模型与校验 | [`deepseek_client.py`](../semantic_pallet_planner/src/semantic_pallet_planner/vlm/deepseek_client.py)、[`protocol_o2a.py`](../semantic_pallet_planner/src/semantic_pallet_planner/vlm/protocol_o2a.py) | API 密钥从环境变量取，不写入实验文件；Direct 返回公开 `Cxx` 编号，AST 方法返回受限规则。响应需匹配 `request_id/state_hash/policy_digest`，格式错误最多修复一次。 |
| 旧 1C 模型链路 | [`stage1c.py`](../semantic_pallet_planner/src/semantic_pallet_planner/runners/stage1c.py)、[`selectors/vlm.py`](../semantic_pallet_planner/src/semantic_pallet_planner/selectors/vlm.py) | 固定题中生成 Text/Visual 请求、打乱候选编号、解析回复并记录修复或几何回退；这是历史 V1 协议，不能与 O2b 的 AST 协议混作同一结果。 |
| 实验与复查 | [`attribute_o2b.py`](../semantic_pallet_planner/src/semantic_pallet_planner/runners/attribute_o2b.py)、[`attribute_o1b_verify.py`](../semantic_pallet_planner/src/semantic_pallet_planner/runners/attribute_o1b_verify.py) | 记录原始提议、屏障干预、实际提交和错误；独立重算候选评价、来源/Schema/泄漏检查及逐题回放。 |

**物理合法 ≠ 业务合规。** 例如把电子产品箱放在重箱旁边，可以不碰撞、不超载，却违反“不得直接面接触”。**Executor ≠ 业务屏障。** Executor根据规则找位置；屏障只拦住违规提议，不会替模型改选。

## 3. 最新数据集怎样构建

### 基础数据 V1

[数据集 V1](../semantic_pallet_dataset_v1/README.md)以 BED-BPP 的订单、箱体尺寸、质量和到货顺序为骨架，附加可复现的**合成**易碎性、类别、可堆叠性和顶部承载值。它包含 100 个基础场景和 360 个固定决策案例；基础场景划分为 train 50、validation 10、test-ID 20、几何 OOD 10、语义 OOD 10。真实订单骨架不代表合成属性经过工业测量；目前的承载评价不是实测损伤概率。[原始统计](../semantic_pallet_dataset_v1/statistics/dataset_summary.json)

### 最新 O1b 开发集 `_03`

[`attribute_o1b.py`](../semantic_pallet_planner/src/semantic_pallet_planner/runners/attribute_o1b.py)从原 train 的 50 个来源订单中，按固定排序取后 30 个，与此前 V2/O2a 和已查看的 test 来源隔离。每个订单先检查 3 个物理状态，按预先写定的**候选可行性和政策差异**规则留 1 个；所以是 **90 个状态尝试 → 30 个保留状态**。筛选发生在模型调用前，不能按 Flash 答得好坏再挑题。它是 *train 来源派生的开发验证集*，没有把原 validation 扩成 30 个独立订单，更不是新 test。

每个保留状态使用同一个物理候选集和同一个 `C01…C16` 映射，制作 6 道题：

- **A0/A1**：两条政策的规范表达，用于基本规则与政策切换检查。
- **B0/B1**：与 A0/A1 分别同义的改写，用于检查语言表述变化；这些改写已用于开发公开 Parser，不能称为该 Parser 的未见语言测试。
- **C0/C1**：公开的“若当前箱为重箱／否则”条件分支，交换两条政策的分支顺序；只使用已有规则原语。

合计 **30 个独立来源 × 1 状态 × 3 轨 × 2 政策＝180 题**，形成 90 组政策配对。不同政策题共享物理状态、Top-K 候选与公开编号，只改变指令和 `policy_digest`。私有文件保存真值 AST、完整候选评价与真实候选 ID 映射；[公开请求](../semantic_pallet_planner/outputs/EXP_OPT_O1B_LANGUAGE_PILOT_20261009_03/data/public_requests/O1B_GROUP_004_A0.json)只包含当前公开事实，不能看到隐藏答案或未来箱体。

[O1b 验收报告](../semantic_pallet_planner/outputs/EXP_OPT_O1B_LANGUAGE_PILOT_20261009_03/acceptance_report.json)记录：**168/180** 题 Top-K 内有业务可行候选；**12/180** 连当前全枚举空间也无满足解，需单列 `abstain` 诊断，不能计为业务成功。90 对中 30 对的最优等价集合因政策而变，但只来自 **10/30 个独立来源订单**；其余 60 对是控制组。180 题不能当成 180 个独立订单。O1b 自动检查通过，两名人工独立 AST 真值签认和维护工时仍按验收表记为待完成；Agent 技术审计不能冒充人工签认。

## 4. O2b 六种方法面对同一题怎样决策

| 方法 | 实际使用的信息 | 决策方式 |
|---|---|---|
| Geometry-Greedy | 公开候选几何事实 | 取几何分最高项，不按本题业务指令排序。 |
| 固定属性启发式 | 公开属性、候选关系；固定通用政策 | 用冻结的属性偏好选项，不根据本题文本改政策。 |
| Flash Direct-Text | 相同公开状态、指令、属性与候选事实 | Flash 直接回答 `Cxx` 或 `abstain`。 |
| Public Parser＋Executor | 相同公开事实与自然语言 | 编写的解析器产出 AST，共用执行器精确计算。 |
| Flash AST＋Executor | 相同公开事实与自然语言 | Flash 产出 AST，共用执行器精确计算。 |
| 真值 AST＋Executor | **隐藏真值规则**与候选 | 特权参考上界，不是同权限竞品，也不是全局在线最优。 |

所有非特权方法的请求须绑定 `request_id`、`state_hash`、`policy_digest`，只用公开显示编号。提交前对每个非特权方法运行同一个**公开解析规则业务屏障**：违规提议会被拦截为 `screen_abstain`，不会自动改选另一个候选。评价必须分别统计**原始提议**与**实际提交**。[具体 3D 案例与六方法流程](../report/visualization/O2b_六方法同题3D案例解析.md)

## 5. 各阶段具体评测什么

| 阶段/对象 | 关键指标与分母 | 应怎样理解 |
|---|---|---|
| 1A/1B 几何与在线旧框架 | 物理违规、支撑率、Top-K/Pareto 覆盖、几何分；在线 episode 完成率、放置件数比例、终止原因、回放 | 衡量候选物理质量和旧版完整订单流程；物理安全不等于属性正确。 |
| 1C / V1 固定题 | `soft_utility`、唯一 Oracle ID 命中、语义/物理违规、调用合法率与回放 | 360 题六方法是历史基线；Handcrafted Rule 和 Oracle 可读取隐藏信息，不能用其命中率直接判断自然语言理解。 |
| V2 / O2a 协议 | 首答/修复后 API 合法率、绑定字段、错误分类、模型原始选择、`abstain`、屏障或回退记录 | **格式合法不等于业务正确**；修复和回退不能算模型首答正确。 |
| O1b 数据质量 | 独立来源数、跨划分重合、Schema/泄漏/独立重算、Top-K 与全枚举业务可行覆盖、政策机会配对数 | 测“试卷有没有真正区分度”；O1b 不调用模型，不能据此宣称模型优势。 |
| O2b 固定候选选址 | 下表所列业务、语义、协议、物理与统计指标 | 180 题 × 6 方法，每方法同题同候选；按**30 个来源订单**聚类比较。 |
| O3 计划中的在线属性码垛 | Episode Attribute Success、完整订单完成率、已放数量/体积比例、最终属性布局、屏障干预、实际物理违规、轨迹回放 | 这些是下一阶段验收指标，目前没有 O3 在线结果。 |

O2b 的主要字段及正确分母（详细定义见[冻结指标规范](metrics_v2_spec.md)与[运行汇总代码](../semantic_pallet_planner/src/semantic_pallet_planner/runners/attribute_o2b.py)）：

| 指标 | 算什么 | 分母/注意事项 |
|---|---|---|
| `raw_avoidable_hard_wrong` | 有适用硬规则、Top-K 有业务可行位置时，方法的**原始提议**是否仍有放置后硬违规 | 本批 **111 题**；屏障随后拦截也不抹掉方法错误。 |
| `raw_optimal_hit` | 原始提议是否在“硬可行→第一软目标→第二软目标”的最优等价集合中 | 候选内有解题 **168 题**；Flash Direct 有一道未产生可计入的原始选址，因此其统计分母为 **167**。 |
| `all_attempt_success` | 对硬规则适用题，实际提交且放置后没有业务硬违规 | 本批 **123 题**，含 12 道无可行解题；拒放不算成功。它不同于“有解题中选对”的比率。 |
| `raw_new_business_violations` / `raw_post_business_violations` | 本步新增违规实例 / 放置后全状态违规实例 | 载荷按受影响易碎箱计，禁止接触按无序箱体对计；已有违规与新增违规分开。无原始选择为 N/A。 |
| `raw_priority_regret` | 所选候选相对最优候选在各级软目标的差距 | 仅适用目标有值时计算；第一优先级未达到最优，不用第二级成绩抵消。 |
| `screen_intervened`、`committed_label` | 屏障是否拦截，以及真正放了哪个候选 | `proposed_label` 不等于实际提交；拦截后 `committed_label` 为空。 |
| `ast_accuracy` | 条件、对象、阈值、硬软类型、优先级及完整 AST 与真值是否严格一致 | **规则解析质量**与**选址质量**分别报告；结构不同也可能在当前题执行出相同动作。 |
| `policy_pair_success_rate` | 同物理状态的两条政策都命中各自正确集合 | 只在真实政策切换机会组中评价；机会分布在 10 个独立来源订单，不能当成 30 个独立机会来源。 |
| `physical_violations`、API 合法率、token/时延、回放 | 已提交动作的独立物理检查、响应是否符合 Schema/绑定、调用情况及原记录能否重算 | 未提交不称为“安全放置成功”；O3 后续不把费用记录作为阶段要求，旧 O2b 费用未知仍为 `null`。 |

**最新已观察结果。** [O2b 原始汇总](../semantic_pallet_planner/outputs/EXP_OPT_O2B_AST_PILOT_20261009_05/metrics/summary.json)中的原始可避免硬违规：Geometry 27/111、固定属性 3/111、Flash Direct 21/111、Public Parser 0/111、Flash AST 0/111、真值 AST 0/111；最优等价命中分别为 81/168、129/168、93/167、168/168、168/168、168/168。Flash Direct 首答合法 178/180、修复后 180/180；Flash AST 首答 180/180 合法，但**严格完整 AST 结构一致仅 80/180**，不能把最终选址满分写成 AST 解析满分。实际提交物理违规为 0，[独立回放](../semantic_pallet_planner/outputs/EXP_OPT_O2B_AST_PILOT_20261009_05/replay_report.json)为 1080/1080 通过。

这些只是已公布受限语法上的**开发集证据**：混合方法相对 Direct 更可靠，但 Public Parser＋Executor 已达到同一候选内上界，尚无 Flash 相对强规则系统的增量优势。本轮是 **Text＋JSON**，不是视觉贡献证明。[O2b 验收报告](../semantic_pallet_planner/outputs/EXP_OPT_O2B_AST_PILOT_20261009_05/acceptance_report.json)记载工程检查通过、远程矩阵完成；完整验收仍待独立重复与统计功效设计，不是新 test 结果。

## 6. 接下来应补什么

1. **先接 O3a 在线属性链路。** 在已有 `PalletEnvironment`/`EpisodeRunner` 上新增版本化 adapter/runner，把 `policy_digest`、公开关系、AST 执行、业务屏障、属性 `before/after/delta` 接入每一步；各方法按自己真实提交后的状态重新生成 Top-K，保留完整终止原因和独立回放。不要把固定题逐题选择误称为完整订单能力。[O3 路线](属性感知O3在线码垛框架与论文创新验证路线.md)
2. **再做 O3b 在线开发对照。** 比较完整订单的属性安全成功、完成率和最终布局，保存成功及失败轨迹。新 validation 按独立订单分组；在新 test 前确定场景组数、重复次数和判定阈值，不能使用已查看的旧 test 调参。
3. **补齐未结验收。** O1b/O2a 原计划的两名人工独立复核签认及人工维护工时仍待落实；O2b 的独立重复和功效设计仍待完成。已有 Agent 审计和自动回放提供技术证据，但不替代原人工签认条件。
4. **寻找可检验的研究增量。** 当前语法已被强 Public Parser 完整覆盖，应在另立、冻结的未见表达/组合或政策变化在线任务中，与同权限 Parser 做对照；若规则系统仍持平，应如实报告适用边界。视觉独有属性、动态记忆、Gazebo/机器人属于独立后续工作，当前代码和结果尚不能证明这些收益。

阅读产物时建议按此顺序：[O1b 来源与划分](../semantic_pallet_planner/outputs/EXP_OPT_O1B_LANGUAGE_PILOT_20261009_03/data/split_audit.json) → [O1b 题目及覆盖](../semantic_pallet_planner/outputs/EXP_OPT_O1B_LANGUAGE_PILOT_20261009_03/data/coverage_report.json) → [O2b 六方法逐题 CSV](../semantic_pallet_planner/outputs/EXP_OPT_O2B_AST_PILOT_20261009_05/metrics/per_decision.csv) → [O2b 汇总](../semantic_pallet_planner/outputs/EXP_OPT_O2B_AST_PILOT_20261009_05/metrics/summary.json) → [验收与回放](../semantic_pallet_planner/outputs/EXP_OPT_O2B_AST_PILOT_20261009_05/acceptance_report.json)。
