# semantic_pallet_planner：代码、数据与评测现状速览

> 更新：2026-10-19。O1b/O2b 固定题开发实验与 O3 在线框架、真实五方法安全模式、业务违规观察实验均已有产物。O3 本轮工程验收通过，Flash 相对强公开 Parser 的增量优势仍无证据；O4 视觉、O5 经验为后续阶段。旧实验、冻结快照与已查看 test 保持历史口径。

## 一句话理解项目

系统先在当前托盘状态下**生成物理上可放的候选位置**，再根据“保护易碎箱、禁止两类箱体接触、重箱放低”等业务指令选一个位置；选择后检查是否违规，并记录结果。O2b 比较固定的一步候选题；O3 已将“语言→规则 AST→确定性执行器”接入完整在线订单，各方法根据自己的实际提交状态生成下一步候选。O3 同时支持业务违规即拒放的安全模式和业务违规只记录、继续执行的观察模式，物理检查始终保留。

```text
BED-BPP订单尺寸/质量/顺序 + 合成语义属性
  → 场景与当前箱（真值状态，buffer_size=1）
  → 极值点/支撑层生成候选 → 物理过滤 → 多样化 Top-K=16
  → 同一公开请求：自然语言 + 属性 + 候选 + 可复算关系
  → O2b 六方法固定题 / O3 五方法独立在线轨迹
  → safe：业务违规拦截；observe_business：业务违规照常提交并记录
  → 独立物理复核、隐藏真值评价、before/after/delta 与回放
  → 在线模式进入下一箱，直到放完或有明确终止记录
```

## 1. 早期阶段做了什么：1A → 1B → 1C

这三个阶段依次解决了“实验能统一运行”“物理候选能可靠生成”“模型能在同一批候选中选位置”。它们均有自动验收通过的原始产物，但 **1C 仍是固定候选的一步决策**，没有证明模型能独立完成整个订单。

### 1A：统一平台与可回放数据链路

1A 将数据读取、当前状态、候选、选择器、执行提交、指标和日志接成统一接口。`FixedCaseRunner` 让不同方法面对**同一道题、同一候选集**；`EpisodeRunner` 按到货顺序逐箱执行，下一步基于已提交状态重新生成候选。公开请求与隐藏评价信息分开，非法候选 ID、过期状态和坐标注入会被协议检查拒绝。主要代码见 [`repository.py`](../../semantic_pallet_planner/src/semantic_pallet_planner/repository.py)、[`environment.py`](../../semantic_pallet_planner/src/semantic_pallet_planner/environment.py) 和 [`runners/`](../../semantic_pallet_planner/src/semantic_pallet_planner/runners)；阶段说明见[1A–1B 开发说明](../03_阶段产出分析/1A-1B/阶段1A-1B开发说明.md)。

[1A 原始验收](../../semantic_pallet_planner/outputs/EXP_1A_20260912_FINAL/acceptance_report.json)为 `PASS`：30 道 validation 固定题 × 4 方法＝120 条决策，并完成一个 10 箱在线冒烟订单。 [独立回放](../../semantic_pallet_planner/outputs/EXP_1A_20260912_FINAL/replay_report.json)覆盖 130 条事件，物理错误和请求泄漏均为 0。它证明了框架接口与复现链路可用；30 道固定题不能证明方法具有跨场景泛化能力。

### 1B：物理候选、几何基线与在线实验

1B 把极值点和已有箱顶支撑位置枚举、`yaw=0°/90°`、物理约束过滤、几何评分和多样化 Top-K 放进统一候选生成器。几何评分综合紧凑度、高度、支撑和均衡；通过 validation 上的 K=4/8/16/32 敏感性分析后，后续实验冻结 **Top-K=16**。还完成了旧版候选行为的回归、候选漏斗与耗时记录、布局图/动画，以及 `lowest`、`geometry_greedy`、`pareto_greedy` 三种在线几何基线。实现见 [`planner/generator.py`](../../semantic_pallet_planner/src/semantic_pallet_planner/planner/generator.py) 与 [`planner/constraints.py`](../../semantic_pallet_planner/src/semantic_pallet_planner/planner/constraints.py)。这是 EMS-style 实现，并非完整 GOPT 模型。

[1B 原始验收](../../semantic_pallet_planner/outputs/EXP_1B_20260912_FINAL/acceptance_report.json)为 `PASS`：360 道固定题 × 4 方法＝1440 条决策；100 个基础场景 × 3 种在线基线＝300 个 episode。几何贪心完成 **100/100** 个选定场景，`lowest` 为 **57/100**，Pareto 贪心为 **50/100**；[独立回放](../../semantic_pallet_planner/outputs/EXP_1B_20260912_FINAL/replay_report.json)覆盖 5728 条事件，物理错误和请求泄漏均为 0。这里的完成率只针对当时的订单和代理物理规则，尚未评价“不同属性箱体是否放得合适”。

### 1C：把 DeepSeek Text/Visual 接入固定候选选择

1C 冻结 1B 的物理候选，让随机、几何贪心、Handcrafted Rule、Flash Text、Flash Visual、Candidate Oracle 六种方法回答相同固定题。模型看到公开状态、业务指令和打乱后的 `Cxx` 候选编号；Visual 另看由公开状态渲染的图。适配器将返回编号映射到真实候选，检查响应格式及候选合法性，记录原始回复、修复/回退、耗时与重放结果。链路见 [`stage1c.py`](../../semantic_pallet_planner/src/semantic_pallet_planner/runners/stage1c.py)、[`selectors/vlm.py`](../../semantic_pallet_planner/src/semantic_pallet_planner/selectors/vlm.py) 与 [`candidate_mapping.py`](../../semantic_pallet_planner/src/semantic_pallet_planner/vlm/candidate_mapping.py)。

[1C 原始验收](../../semantic_pallet_planner/outputs/EXP_1C_DEEPSEEK_FLASH_FINAL_V1/acceptance_report.json)为 `PASS`：**360 题 × 6 方法＝2160 条决策**，[回放](../../semantic_pallet_planner/outputs/EXP_1C_DEEPSEEK_FLASH_FINAL_V1/replay_report.json)无物理违规或公开请求泄漏。历史 `soft_utility` 均值为几何贪心 **0.637921**、Flash Text **0.695990**、Flash Visual **0.698657**、Handcrafted Rule 和 Oracle 均 **0.765367**。这说明两种 Flash 输入在当时的固定题上高于几何贪心；Visual 相对 Text 的差值仅 **0.002667**，不能据此证明图像有独有信息。[协议记录](../../semantic_pallet_planner/outputs/EXP_1C_DEEPSEEK_FLASH_FINAL_V1/metrics/protocol_summary.json)显示 Text 最终合法 360/360，Visual 357/360，后者有 3 次回退。Handcrafted Rule 直接读取隐藏结构化规则，Oracle 直接读取候选内参考答案；两者命中 360/360 不代表从自然语言理解了规则，也不是同权限对照。旧 1C 已查看的 test 仅作历史回归，不作为 V2/O3 的未见测试证据。

## 2. 代码按什么顺序工作

| 环节 | 当前主要实现 | 实际做的事 |
|---|---|---|
| 读取数据 | [`repository.py`](../../semantic_pallet_planner/src/semantic_pallet_planner/repository.py) | 按 Schema 只读载入场景、固定题和候选；隐藏规则、Oracle 通过单独接口读取。 |
| 管理状态 | [`environment.py`](../../semantic_pallet_planner/src/semantic_pallet_planner/environment.py)、[`domain.py`](../../semantic_pallet_planner/src/semantic_pallet_planner/domain.py) | 当前只暴露一个到货箱；提交后更新已放箱体，下一步从实际新状态生成候选。此链路属于旧版在线框架。 |
| 生成候选 | [`generator.py`](../../semantic_pallet_planner/src/semantic_pallet_planner/planner/generator.py)、[`constraints.py`](../../semantic_pallet_planner/src/semantic_pallet_planner/planner/constraints.py) | 对 `yaw=0°/90°` 枚举地面和已有箱顶的极值点；过滤越界、碰撞、托盘超载、支撑不足、重心投影不合格、不可堆叠支撑和传播后物理承重超限；按紧凑、高度、支撑和均衡等几何量评分，返回多样化 Top-K。它是 EMS-style 独立实现，**不是完整 GOPT**。 |
| 公开关系 | [`attribute_metrics_v2.py`](../../semantic_pallet_planner/src/semantic_pallet_planner/evaluation/attribute_metrics_v2.py) | 不借用生成器的私有“放置后状态”，而从位姿重建支撑与间接载荷；计算易碎箱承载、重箱高度/中心距离、面接触对及 `before/after/delta`。 |
| 理解规则 | [`instruction_parser_o1b.py`](../../semantic_pallet_planner/src/semantic_pallet_planner/selectors/instruction_parser_o1b.py)、[`policy_protocol_o2b.py`](../../semantic_pallet_planner/src/semantic_pallet_planner/vlm/policy_protocol_o2b.py) | 公开 Parser 或 Flash 把指令转成受限 AST：硬约束、阈值、软目标优先级和可选的“若当前箱为重箱／否则”分支。未识别语法或非法 AST 明确失败。 |
| 选候选 | [`policy_executor_v2.py`](../../semantic_pallet_planner/src/semantic_pallet_planner/selectors/policy_executor_v2.py)、[`policy_v2.py`](../../semantic_pallet_planner/src/semantic_pallet_planner/evaluation/policy_v2.py) | 按 AST 逐候选计算：先保留业务硬约束可行项，再逐级比较软目标；同分时比较几何分和公开编号。安全模式没有可行项则终止；O3 观察模式在业务无解时采用已冻结的最少新增/加重违规排序继续选择。 |
| 调模型与校验 | [`deepseek_client.py`](../../semantic_pallet_planner/src/semantic_pallet_planner/vlm/deepseek_client.py)、[`protocol_o2a.py`](../../semantic_pallet_planner/src/semantic_pallet_planner/vlm/protocol_o2a.py) | API 密钥从环境变量取，不写入实验文件；Direct 返回公开 `Cxx` 编号，AST 方法返回受限规则。响应需匹配 `request_id/state_hash/policy_digest`，格式错误最多修复一次。 |
| 旧 1C 模型链路 | [`stage1c.py`](../../semantic_pallet_planner/src/semantic_pallet_planner/runners/stage1c.py)、[`selectors/vlm.py`](../../semantic_pallet_planner/src/semantic_pallet_planner/selectors/vlm.py) | 固定题中生成 Text/Visual 请求、打乱候选编号、解析回复并记录修复或几何回退；这是历史 V1 协议，不能与 O2b 的 AST 协议混作同一结果。 |
| 实验与复查 | [`attribute_o2b.py`](../../semantic_pallet_planner/src/semantic_pallet_planner/runners/attribute_o2b.py)、[`attribute_o1b_verify.py`](../../semantic_pallet_planner/src/semantic_pallet_planner/runners/attribute_o1b_verify.py) | 记录原始提议、屏障干预、实际提交和错误；独立重算候选评价、来源/Schema/泄漏检查及逐题回放。 |

**物理合法 ≠ 业务合规。** 例如把电子产品箱放在重箱旁边，可以不碰撞、不超载，却违反“不得直接面接触”。**Executor ≠ 业务屏障。** Executor根据规则找位置；屏障只拦住违规提议，不会替模型改选。

## 3. 数据集与固定题怎样构建

### 基础数据 V1

[数据集 V1](../../semantic_pallet_dataset_v1/README.md)以 BED-BPP 的订单、箱体尺寸、质量和到货顺序为骨架，附加可复现的**合成**易碎性、类别、可堆叠性和顶部承载值。它包含 100 个基础场景和 360 个固定决策案例；基础场景划分为 train 50、validation 10、test-ID 20、几何 OOD 10、语义 OOD 10。真实订单骨架不代表合成属性经过工业测量；目前的承载评价不是实测损伤概率。[原始统计](../../semantic_pallet_dataset_v1/statistics/dataset_summary.json)

### O1b 固定题开发集 `_03`

[`attribute_o1b.py`](../../semantic_pallet_planner/src/semantic_pallet_planner/runners/attribute_o1b.py)从原 train 的 50 个来源订单中，按固定排序取后 30 个，与此前 V2/O2a 和已查看的 test 来源隔离。每个订单先检查 3 个物理状态，按预先写定的**候选可行性和政策差异**规则留 1 个；所以是 **90 个状态尝试 → 30 个保留状态**。筛选发生在模型调用前，不能按 Flash 答得好坏再挑题。它是 *train 来源派生的开发验证集*，没有把原 validation 扩成 30 个独立订单，更不是新 test。

每个保留状态使用同一个物理候选集和同一个 `C01…C16` 映射，制作 6 道题：

- **A0/A1**：两条政策的规范表达，用于基本规则与政策切换检查。
- **B0/B1**：与 A0/A1 分别同义的改写，用于检查语言表述变化；这些改写已用于开发公开 Parser，不能称为该 Parser 的未见语言测试。
- **C0/C1**：公开的“若当前箱为重箱／否则”条件分支，交换两条政策的分支顺序；只使用已有规则原语。

合计 **30 个独立来源 × 1 状态 × 3 轨 × 2 政策＝180 题**，形成 90 组政策配对。不同政策题共享物理状态、Top-K 候选与公开编号，只改变指令和 `policy_digest`。私有文件保存真值 AST、完整候选评价与真实候选 ID 映射；[公开请求](../../semantic_pallet_planner/outputs/EXP_OPT_O1B_LANGUAGE_PILOT_20261009_03/data/public_requests/O1B_GROUP_004_A0.json)只包含当前公开事实，不能看到隐藏答案或未来箱体。

[O1b 验收报告](../../semantic_pallet_planner/outputs/EXP_OPT_O1B_LANGUAGE_PILOT_20261009_03/acceptance_report.json)记录：**168/180** 题 Top-K 内有业务可行候选；**12/180** 连当前全枚举空间也无满足解，需单列 `abstain` 诊断，不能计为业务成功。90 对中 30 对的最优等价集合因政策而变，但只来自 **10/30 个独立来源订单**；其余 60 对是控制组。180 题不能当成 180 个独立订单。O1b 自动检查通过，两名人工独立 AST 真值签认和维护工时仍按验收表记为待完成；Agent 技术审计不能冒充人工签认。


### O3 完整订单数据与代码

O3a 使用 3 个已见 train 来源订单及双政策；O3b 使用原 validation 的 10 个来源订单及双政策，每方法各 20 个任务、五方法共 100 个 episode。它是在线开发证据，不是新 test。P0 为易碎累计承载≤1 kg、电子产品与重箱不得面接触、先低位再中心；P1 改为≤3 kg 并交换软优先级。物料属性仍为 synthetic。

入口是 [`attribute_o3_online.py`](../../semantic_pallet_planner/src/semantic_pallet_planner/runners/attribute_o3_online.py)，公开请求与业务屏障见 [`o3_online_adapter.py`](../../semantic_pallet_planner/src/semantic_pallet_planner/runners/o3_online_adapter.py)。原始映射、隐藏规则只供独立评价或特权参考，不进入非特权选择器输入。

## 4. O2b 六种方法面对同一题怎样决策

| 方法 | 实际使用的信息 | 决策方式 |
|---|---|---|
| Geometry-Greedy | 公开候选几何事实 | 取几何分最高项，不按本题业务指令排序。 |
| 固定属性启发式 | 公开属性、候选关系；固定通用政策 | 用冻结的属性偏好选项，不根据本题文本改政策。 |
| Flash Direct-Text | 相同公开状态、指令、属性与候选事实 | Flash 直接回答 `Cxx` 或 `abstain`。 |
| Public Parser＋Executor | 相同公开事实与自然语言 | 编写的解析器产出 AST，共用执行器精确计算。 |
| Flash AST＋Executor | 相同公开事实与自然语言 | Flash 产出 AST，共用执行器精确计算。 |
| 真值 AST＋Executor | **隐藏真值规则**与候选 | 特权参考上界，不是同权限竞品，也不是全局在线最优。 |

所有非特权方法的请求须绑定 `request_id`、`state_hash`、`policy_digest`，只用公开显示编号。提交前对每个非特权方法运行同一个**公开解析规则业务屏障**：违规提议会被拦截为 `screen_abstain`，不会自动改选另一个候选。评价必须分别统计**原始提议**与**实际提交**。[具体 3D 案例与六方法流程](../../report/visualization/O2b_六方法同题3D案例解析.md)

## 5. 各阶段具体评测什么

| 阶段/对象 | 关键指标与分母 | 应怎样理解 |
|---|---|---|
| 1A/1B 几何与在线旧框架 | 物理违规、支撑率、Top-K/Pareto 覆盖、几何分；在线 episode 完成率、放置件数比例、终止原因、回放 | 衡量候选物理质量和旧版完整订单流程；物理安全不等于属性正确。 |
| 1C / V1 固定题 | `soft_utility`、唯一 Oracle ID 命中、语义/物理违规、调用合法率与回放 | 360 题六方法是历史基线；Handcrafted Rule 和 Oracle 可读取隐藏信息，不能用其命中率直接判断自然语言理解。 |
| V2 / O2a 协议 | 首答/修复后 API 合法率、绑定字段、错误分类、模型原始选择、`abstain`、屏障或回退记录 | **格式合法不等于业务正确**；修复和回退不能算模型首答正确。 |
| O1b 数据质量 | 独立来源数、跨划分重合、Schema/泄漏/独立重算、Top-K 与全枚举业务可行覆盖、政策机会配对数 | 测“试卷有没有真正区分度”；O1b 不调用模型，不能据此宣称模型优势。 |
| O2b 固定候选选址 | 下表所列业务、语义、协议、物理与统计指标 | 180 题 × 6 方法，每方法同题同候选；按**30 个来源订单**聚类比较。 |
| O3 已实现的在线属性码垛 | 无违规整单成功、完整订单完成率、已放数量/体积比例、新增或加重违规步骤率、最终违规实例、屏障记录、物理违规和回放 | 安全模式与业务观察模式分开报告；每方法 20 个 validation 政策任务来自 10 个独立订单。 |

O2b 的主要字段及正确分母（详细定义见[冻结指标规范](../01_技术原理与数据规范/metrics_v2_spec.md)与[运行汇总代码](../../semantic_pallet_planner/src/semantic_pallet_planner/runners/attribute_o2b.py)）：

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

**O2b 历史固定题结果。** [O2b 原始汇总](../../semantic_pallet_planner/outputs/EXP_OPT_O2B_AST_PILOT_20261009_05/metrics/summary.json)中的原始可避免硬违规：Geometry 27/111、固定属性 3/111、Flash Direct 21/111、Public Parser 0/111、Flash AST 0/111、真值 AST 0/111；最优等价命中分别为 81/168、129/168、93/167、168/168、168/168、168/168。Flash Direct 首答合法 178/180、修复后 180/180；Flash AST 首答 180/180 合法，但**严格完整 AST 结构一致仅 80/180**，不能把最终选址满分写成 AST 解析满分。实际提交物理违规为 0，[独立回放](../../semantic_pallet_planner/outputs/EXP_OPT_O2B_AST_PILOT_20261009_05/replay_report.json)为 1080/1080 通过。

这些只是已公布受限语法上的**开发集证据**：混合方法相对 Direct 更可靠，但 Public Parser＋Executor 已达到同一候选内上界，尚无 Flash 相对强规则系统的增量优势。本轮是 **Text＋JSON**，不是视觉贡献证明。[O2b 验收报告](../../semantic_pallet_planner/outputs/EXP_OPT_O2B_AST_PILOT_20261009_05/acceptance_report.json)记载工程检查通过、远程矩阵完成；完整验收仍待独立重复与统计功效设计，不是新 test 结果。

## 6. 最新 O3 结果与结论

O3a 安全试跑 30 个 episode、O3b 安全模式 100 个 episode、业务违规观察模式 100 个 episode 的自动验收均为 PASS。观察模式回放 100/100 通过，1277 条公开请求审计失败 0，已提交物理违规 0，所有有效提议均原样提交。

| 观察模式方法 | 完整放完 | 曾违规任务 | 新增/加重违规步骤率 | 最终违规实例数 |
|---|---:|---:|---:|---:|
| Geometry | 20/20 | 14/20 | 46/284＝16.20% | 44 |
| 固定属性 | 12/20 | 10/20 | 30/244＝12.30% | 33 |
| Public Parser | 11/20 | 9/20 | 26/238＝10.92% | 29 |
| Flash AST | 11/20 | 9/20 | 26/238＝10.92% | 29 |
| 真值 AST 参考 | 11/20 | 9/20 | 26/238＝10.92% | 29 |

Flash 实际调用 238 次，首答全部协议合法，修复 0。Flash 和 Public Parser 的全部 247 个对应步骤前状态、选择和后状态相同。较低违规与较低完成数量同时出现；无违规整单成功分别是 Geometry 6/20、固定属性 6/20、后三方法各 7/20。工程完成不等于证明 VLM 优于规则系统。

详见 [O3 业务违规结果分析](../03_阶段产出分析/O3/O3业务违规观察实验结果分析.md)、[观察模式运行手册](../04_运行与复核手册/O3业务违规率完整订单实验运行说明.md)、[完整订单 3D 案例](../03_阶段产出分析/O3/O3完整订单五方法3D案例说明.md)。原始证据：[业务观察验收](../../semantic_pallet_planner/outputs/EXP_OPT_O3B_BUSINESS_OBSERVE_20261016_REMOTE_01/acceptance_report.json)、[方法汇总](../../semantic_pallet_planner/outputs/EXP_OPT_O3B_BUSINESS_OBSERVE_20261016_REMOTE_01/metrics/summary.json)。

## 7. 后续阶段与证据边界

**2026-10-19后续开发更新：** 已完成[失败归因](../03_阶段产出分析/O3/O3失败归因与轨迹分叉诊断_20261019.md)及[布局保留机制与消融](../03_阶段产出分析/O3/O3布局保留机制开发与消融结果_20261019.md)。后者在10个已见validation来源订单、双政策、两模式、9变体共360个离线episode上工程PASS；完整四项评分未超过同预算几何对照。去地面项变体完整无违规12/20，原策略7/20，但采用显式新软预算，且较好变体仍待独立验证；不代表Flash、视觉或记忆收益，也未替换原默认策略。

1. **O4 视觉贡献验证**：建议优先明确图像独有信息、识别接口与公平消融；当前 O3 的 Text＋JSON 结果不能证明视觉贡献。详细实施文档尚待编写。
2. **O5 经验沉淀**：先明确经验如何影响候选选择，再比较同一选择器的 NoMemory、冻结检索和动态记忆。只向现有 AST 解析 Prompt 加经验，可能不会改变共同 Executor 的动作。O5 当前尚未实现。
3. **保留历史未结项**：O1b/O2a 原人工签认、维护工时和 O2b 完整统计设计仍按原报告记录；Agent 审计不等同于人工签认。这些历史未结项不应改写成已通过，也不作为新设的 O3 人工门槛。
4. **正式新 test 尚待冻结并运行**：根据开发数据确定独立来源、重复次数和判定方式，不用已查看的旧 test 调参；继续保留负结果和失败分母。

全部文档与推荐阅读顺序见 [文档导航](../README.md)。
