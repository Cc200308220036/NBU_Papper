# Jev J3：物理可行候选与业务软评价实验开发规范

日期：2026-10-29。设计版本：`jev_j3_physical_business_eval_v1`。状态：**开发设计，尚未实现、尚未执行J3实验**。

工程位置：`/Users/cyw/Desktop/NBU_Papper`；核对Git基线：`e540541a870973af034f030ce8cc0421a62f5e07`。J0/J1/J2新增文件尚需连同工作区一起冻结，不能只记录HEAD就认为已包含这些实现。

用户确认的原则：**物理可行性决定能否执行；业务要求交给Jev权衡；业务违规由独立评价器记录，不作为停止条件。** 本文将该原则落实到候选、输入、提交、统计及验收全过程。本文只交付开发规范，不修改当前运行配置，不产生新的API调用。

## 1. J3研究目标与完成定义

J3需要回答：在相同在线信息、相同物理候选生成机制和相同业务要求下，Jev直接选箱选位，能否在完成订单、利用空间和减少业务违规之间形成有价值的选择？

阶段完成必须满足：

1. 程序允许物理合法、业务违规的动作执行；存在违规或全部候选均违规时仍继续选择和码放。
2. 完整冻结来源订单、公开业务要求、属性、到货流、方法、输入特征、编号规则和评价口径。
3. 真实Jev与本地基线完成同任务对照；保留失败、未完成及未运行订单，不只展示成功案例。
4. 独立评价能区分物理失败、业务违规、订单未完成及API/程序失败；产物可断网重建。
5. 给出结果适用范围与不确定性；**工程通过不要求Jev胜出**。

本阶段不开发ReMe经验提炼、经验检索、模型训练、自主代码进化或真实机器人控制。`memory_mode=none`。J4再研究长期策略经验，并沿用J3建立的任务与评价接口。

## 2. 与J2的关键变化

| 环节 | 当前J2 | J3主实验 |
|---|---|---|
| 模型候选 | 物理TopK中业务检查通过的子集 | 全部物理TopK，不按业务结果删除 |
| 业务要求 | 程序实施硬屏障，模型在允许项内选择 | 模型应尽量遵守；程序不以业务要求拒绝动作 |
| 模型说明 | 所有候选已通过物理和业务检查 | 所有候选只保证物理可行，可能违反业务要求 |
| 业务可行项为0 | `STOP_NO_BUSINESS_CANDIDATE` | 只要物理候选非空，继续选择或singleton提交 |
| 提交 | E2 commit再次做业务拒绝 | 新物理提交接口，只保留物理与绑定检查 |
| 业务评价 | 提交后独立评价，但违规常被前置阻断 | 提交后独立评价，允许得到非零违规 |
| “0违规”解释 | 很大程度来自程序屏障 | 结合完成率、规则适用情况判断策略效果 |

J2结果保持原记录，不能改名为J3主结果。J3必须建立新协议版本、配置、计划和实验目录；禁止修改旧产物或重签旧清单来混用回答。

**不因违规终止，不等于取消业务目标。** Jev仍应尽量避免禁接触、业务禁压、业务限载、区域和相对位置违规；无法同时满足时，执行所选物理动作并如实累计评价。

## 3. 明确物理边界与业务边界

### 3.1 始终保留的物理检查

保持原E2几何后端、物理模型、阈值及评分权重不变，包括托盘边界、高度、碰撞、支撑比例、质心条件、总载荷、支撑箱`stackable`以及物理承载上限。各箱最多16项、缓冲最多3箱、联合最多48项，姿态为0°/90°。

这些是当前仿真模型中的物理条件；其中合成承载上限不是实际材料力学验证。

| 属性/规则 | J3处理 | 说明 |
|---|---|---|
| `stackable=false` | 仍作为物理不可堆叠限制 | 不通过放宽业务规则取消它 |
| `top_load_limit_kg_synthetic` / 公开物理承载上限 | 仍作为物理承载限制 | 与业务限载分别记录 |
| `labels.no_top_load=true` | 业务评价，不作为物理拒绝条件 | 可在物理可堆叠箱上定义，用于测量遵守业务要求的能力 |
| `labels.max_top_load_kg` / 作业单业务限载 | 业务评价 | 超过业务限载但未超过物理承载时允许执行 |
| 禁接触、指定区域、相对位置 | 业务评价 | 不参与候选删除和物理提交拒绝 |
| 类别、易碎、加固属性 | 公开事实，按声明规则解释 | 不额外添加未声明的隐藏物理/业务过滤 |

必须检查业务属性是否已被映射成物理属性。例如业务禁压箱同时被设为`stackable=false`，就无法观察“物理可行但业务禁压违规”的选择。诊断集应主动包含两类属性分离的案例；原始来源订单的物理属性不得为了增加违规而修改。

### 3.2 允许停止的情况

- `ALL_ITEMS_PLACED`：全部订单件放完。
- `STOP_NO_PHYSICAL_CANDIDATE`：当前全部缓冲箱的联合物理池为空；不等于连续空间全局无解。
- API失败、无效响应、未知发送、输入/评价/程序错误：分类保存，不伪装成业务受阻。
- 用户显式中断或有限预算模式耗尽：保留分母与未完成状态；本次默认授权使用unlimited。

J3主模式禁止以`business_rejection`、`STOP_NO_BUSINESS_CANDIDATE`、违规数量阈值或“已有违规未修复”为停止原因。也不能通过无限WAIT绕过规则：沿用fill_then_plan，缓冲已满且物理池为空时如实停止。

## 4. 主实验的候选与输入设计

### 4.1 全物理池，不做隐藏业务选择

建议新配置：`business_mode=evaluate_only`、`selectable_pool=physical_feasible`。

必须满足：

```text
selectable_candidates == physical_candidates
selectable_digest == physical_digest
```

相等应覆盖完整候选及顺序，不能只比数量。候选器不接收参考政策，不按照违规数、标签或规则优先级重新裁剪TopK。公开区域仍可按原E2算法参与几何采样，但不做区域业务合规过滤；“全集”仅指既有TopK全集，不是连续空间所有位姿。

0项停止；1项直接提交，即使它违反业务要求也提交，并记为singleton而非模型成功；2—48项由当前选择方法决定。不得增加“拒绝放置”选项或将旧`group.selected`作为完整模型候选池。

### 4.2 主特征版本：`features_facts_v2`

主实验向各方法提供相同公共事实：托盘、已放箱、当前缓冲箱及属性、公开区域、业务原文与确定性等价英文说明、目标、候选完整动作、几何分量、支撑关系、当前载荷和该候选的载荷变化等。

关键改动：

- 删除固定为true的`current_business_allowed`，并删除“All options passed ... business checks”说明。
- 不提供私有参考评价、参考允许集合、候选违规答案或未来订单。
- 主特征不直接提供逐候选`allowed`、违规总分、规则满足布尔向量、合规排名。
- 当前载荷与候选载荷增量可以由公开物理状态计算；业务标签阈值和规则优先级公开保留。
- J2的`effective_business_limit_kg`、`remaining_business_limit_kg`属于规则解析后的派生判断，主事实版不直接沿用。若研究其帮助，归入下述增强特征消融。
- 不将业务评价器完整输出或包含来源字段的环境对象直接序列化给模型。

候选载荷特征通过公开的一步物理转移计算，不查看后续到货，不运行完整未来订单，不调用独立参考评价器。主任务仍允许本地Parser维护内部规则表示，但不请求Jev生成AST。

建议固定英文问题模板：

> Select one complete box-and-placement action. Every option is physically feasible under the declared simulator checks, but some may violate business requirements. Aim to place the entire order, avoid business violations, and preserve useful space using only observed facts. Business violations are recorded and do not end the episode. Do not assume unseen arrivals.

请求字节上限继续显式检查，不等同于服务token上限。开发集需验证首步与较晚状态的代表性请求；超限记录REQUEST_TOO_LARGE/服务错误，不静默删候选或截断业务要求，且仍保留任务分母。

模板最终文本、英文业务说明、特征与配置摘要必须在测试集运行前冻结。改变目标措辞属于新实验版本，不能修改已运行测试集后继续声称是同一配置。

### 4.3 可选增强特征消融

另立`features_public_predicates_v1`，允许公开业务解释器生成逐候选的即时规则判断、业务载荷余量、当前/新增违规等。其来源只能是公开要求与当前公共状态，不能来自独立参考评价或未来订单。

增强特征必须提供给所有对照，仍保留全部物理候选，额外计算耗时单列。它衡量的是“有程序业务判断辅助时的候选选择”，不能与主事实版混为“Jev自行理解业务要求”的证据。

## 5. 对照方法与公平条件

### 5.1 主方法表

| 方法 | 选择方式 | 业务是否硬过滤 | 用途 |
|---|---|---|---|
| `shared_geometry` | 全物理池中几何分最高；姿态/公开到货次序确定性打破并列 | 否 | 不主动优化业务的几何参照 |
| `shared_business_lexicographic` | 根据公开规则比较新增违规、动作后违规，再按几何分及固定动作键选项 | 否 | 强业务启发式参照，检验是否仅需简单规则评分 |
| `jev_choice` | 同一公共上下文输入真实Jev，返回Cxx | 否 | 研究方法 |

业务启发式是方法自身对公开输入的运算，不调用私有参考评价器。实现时提供`PublicBusinessScorer.score(observation, public_policy, bundle)`：只接经验证的当前公共观测及其本地解析规则，按decision绑定后注入本地选择器；不能把完整task作为闭包输入。该程序解释过程属于基线算法，Jev仍接收语义相同的公开文本与事实，主事实版不注入评分结果。即使所有候选都违规，也选择其中一项，不能停止。固定建议排序键：`(new_violation_instances, after_violation_instances, -geometry_score, canonical_action_key)`；不在测试结果出来后调权重。

保留旧`shared_constrained_first`时，必须明确它原本统计的是业务过滤后的可行数。不能直接换成物理候选数后仍称为原方法；如开发箱体受限度基线，应命名`shared_physical_constrained_first`，单列定义。主实验至少包含上表三种方法。

### 5.2 相同信息、相同生成机制的准确含义

相同订单起点、到货机制、容量、物理候选器、TopK、特征版本、公开要求、空记忆和显示排列规则。相同状态下候选与模型事实必须完全一致。

不同方法选择不同动作后，其状态和后续候选自然分叉，不强求整条轨迹候选相同，也不强行恢复成Jev轨迹。方法自行计算公开规则代价属于算法差异，必须记录其耗时；不得把私有参考答案作为基线输入。

Jev与本地方法均不得从来源ID、split、旧1C答案、参考可行布局或完整到货流获取捷径。

### 5.3 单列消融，不并入主比较

- `hard_business_feasible`：程序业务硬屏障参照，可能业务空池停止，只能作为不同控制机制的消融。
- 增强业务判断特征：区分程序辅助与模型自身选择作用。
- 缓冲容量1：选位实验；容量3：联合选箱选位主实验。
- 选项顺序敏感性：固定相同物理状态，只改变冻结显示seed，比较恢复后的实际动作。

LLM直接选择、搜索增强和经验注入可后置；不以缺少这些扩展阻塞J3主闭环开发。

## 6. 数据来源、任务定义与划分

### 6.1 当前可用条件与默认数据路径

旧F输入快照仍缺失；J1的`e5_frozen_snapshot_v1`适配器不能凭空恢复它。仓库已提交V1数据，包括：

- `semantic_pallet_dataset_v1/tasks/scenarios/*.json`：几何、物理属性、原到货顺序与原作业单。
- `catalog/article_attributes.json`：商品属性来源。
- `splits/*.json`、`splits/group_manifest.json`：划分与物理/配对分组。
- `annotations/ground_truth_rules/*.json`：来源订单键及私有参考注释，仅用于离线溯源、划分和评价。

统计文件声明100个base scenario、140个可见scenario文件；存在语言及buffer3变体。它们不是140个独立来源订单。J3默认开发新适配器`dataset_orders_v1`，不把它称为旧E5/F完全复现；如未来恢复F快照，另设来源分层，不与新任务混用。

### 6.2 不直接冒充兼容原作业单

V1原作业单并不保证属于当前E2 Parser语法。例如SCN_0001原文涉及“电子产品与重物接触/支撑隔离”，不能直接假定E2现有模板已支持其全部语义。

J3首版采用受控派生任务：

1. 复用V1的几何、物理属性、容器及完整到货顺序，不截成前12件。
2. 新建版本化的**公开业务规格**，使用当前支持的业务规则族与公开商品属性。
3. 缺少的业务禁压、业务限载、加固标签，以固定seed和商品来源标识确定性生成；同一商品属性保持一致，生成规则预先冻结，标记为synthetic。
4. 公开作业单与参考规格从同一任务定义分别导出；在线只消费公开文本/公开字段，独立评价器下游消费参考表示。
5. 原作业单、原注释保留作溯源，但不得默默将原私有ground_truth转换成选择器的政策来源。新任务明确标记`business_spec_source=public_generated_v1`。

这验证的是“来源几何订单＋受控合成业务任务”。若后续要复现原作业单，另开发公开文本语义适配和独立验收，不能自动套入本首版。

固定业务配置建议两层：B1为禁接触/业务标签限载与禁压；B2在B1上增加区域/相对位置。具体模板、阈值、优先级、覆盖关系及属性生成分布在数据冻结阶段写入完整JSON，缺失时禁止进入正式实验，不根据Jev结果生成更容易的规则。

首版建议冻结以下默认规格；这是新任务定义，不是对真实商品属性分布的判断：

| 项目 | 默认定义 |
|---|---|
| 属性seed | 20261029 |
| 属性随机数 | SHA-256(canonical([规格版本, seed, source_article_id, 属性名]))前32位除以2^32；禁止Python随机hash和split/index作为属性来源 |
| 业务限载标签 | 从[2, 5, 10, 20] kg等概率确定性选一项，不改物理承载值 |
| 业务禁压标签 | 独立属性随机数小于0.20时为true |
| 加固属性 | glassware类别独立属性随机数小于0.50时为true，其他类别false |
| 业务限载与覆盖 | 默认标签限载priority=20；no_top规则priority=10覆盖标签；加固glassware且非no_top时限载2 kg、priority=0覆盖标签，沿用现有优先级语义 |
| B1接触要求 | food与household_cleaner禁止直接面接触；只评价，不过滤 |
| B2区域/关系 | 在B1基础上增加现有E5的L/R/F/B区域定义；以来源组key的独立SHA-256确定四种方向之一，对food相对cleaner规定50 mm边界间距，并使用对应区域 |

实现时将表格逐项写入public/business_spec.json及attribute_generation.json，验证字段含义后冻结。source_article_id缺失时不得静默按split补造商品身份；按预先声明的数据错误规则处理。规则覆盖率低或业务标签被物理限制完全遮蔽时如实报告，不根据测试模型表现调整标签。

派生订单的业务可满足性不预设为已证明：登记`witness_available/proven_infeasible/unknown`及证据。unknown不能当作已证可行，模型失败也不能直接证明规则无解；不得为得到更好结果事后剔除这些订单。

### 6.3 来源分组与独立测试

- 先核验source_order_key、base_physical_id、pair_group_id及变体关系。同源订单、同一物理场景和对应语言/buffer变体必须处于同一分区。
- 优先审核并复用原train/validation/ID/OOD划分。检测到跨区同源时必须先生成明确的新分组划分版本，不允许默默保留泄漏。
- 重新划分规则必须在任何正式模型调用前冻结，例如按来源连通分组和固定seed分配；保留原split并记录新split，OOD定义单独核验。
- train/validation用于任务和参数开发；独立测试运行前锁定提示、模板、阈值与方法。不得用测试集选择特征或筛订单。
- 本轮核对过目录和示例结构，但尚未完成全量来源去重；100个base、20个ID等数据集统计不能直接充当J3独立样本量。
- 源文件缺失、坏属性、无法解析等静态排除规则预先声明；记录全部入选/排除ID与原因。不能因模型失败、业务矛盾或低利用率事后排除。

### 6.4 诊断集与统计集分开

保留6个既有构造题，其中4个具有可行见证、2个具有业务矛盾证明。它们是工程/压力诊断，不用于估计来源订单泛化。

新增物理允许但业务违规的受控题：禁压、低业务限载、禁接触、区域、相对关系，以及先出现违规后继续码放的轨迹。需记录规则实际可触发性；若物理检查已阻断全部违规动作，该题不能作为业务选择能力证据。

规则矛盾题允许最终非零违规；不能要求“0违规”验收，但必须满足“不因业务停止”的流程标准。不得把“已证业务不可能全满足”解释成物理不可能全部放完。

## 7. 需要改动的代码与新增接口

全部新增生产代码、配置、Schema和测试继续留在`semantic_pallet_planner/src/semantic_pallet_planner/jev_select/`。保持业务模块平铺，不新增按日期复制的生产子包。

| 位置 | 当前问题 | J3具体开发任务 |
|---|---|---|
| `config.py`、`schemas/config.schema.json` | 仅v1配置与硬业务池 | 新增v2加载与模式组合验证；保留v1兼容，不原地改旧配置含义 |
| `candidates.py` | guard.filter删违规项；decision_route可业务停止 | 加模式分派；evaluate_only池与物理池完全相等；只按物理数量决定分支 |
| `context.py` | 依赖guard过滤一致性、allowed=true、旧QUESTION常量 | 按版本验证候选语义；新事实特征、模板、独立prompt_digest；不伪造业务合法标记 |
| 新增`execution.py` | 旧E2 commit会拒绝业务违规 | `commit_physical`验证绑定、原候选、独立物理检查，再调用buffer_state.place |
| `episode.py` | 直接调用旧commit，物理提交与业务反馈日志混在一段 | 按模式使用提交接口，违规不设置reason，保存已提交状态再做下游评价 |
| `selector.py` | 旧baseline语义依赖硬过滤 | 增加公开规则业务排序基线，禁止空业务集合拒放；新方法枚举与结果身份绑定 |
| `evaluation.py` | 只有最终违规、持续违规步数等，分层不足 | 新增违规事件身份、首次/持续/新增/最终指标、覆盖、时间和完整任务分母 |
| `experiment.py` | remote仅允许jev-smoke单方法；数据入口有限 | dataset适配、分组/任务清单、混合方法批量计划、按job选择本地或真实后端 |
| `replay.py`、`ledger.py` | 需绑定新增版本和任务登记 | 核对模式/特征/业务规格/完整registry；重建物理提交及独立评价，保持0网络 |
| `testing.py`、`tests/` | 旧测试主要针对硬业务模式 | 新增“主动选择违规候选后仍继续”的替身和所有新模式验收；旧v1测试不删除 |
| `cli.py`、README | 没有J3 profiles与batch registry | prepare/validate/preflight/run/replay实际帮助；标注拟议命令何时落地 |

建议接口（均为待实现契约）：

```python
class DatasetOrderAdapter:
    def load(self, dataset_root, *, spec_config, split_manifest): ...

def prepare_candidates(state, observation, config) -> CandidateBundle: ...

def commit_physical(state, regions, observation, bundle, context,
                    selection, config) -> dict: ...

def evaluate_committed_state(state, reference_spec, regions) -> dict: ...

def summarize_business_trajectory(events, *, planned_items, rule_registry) -> dict: ...
```

`commit_physical`必须：核对当前观测、job/decision、候选/配置/上下文摘要；恢复唯一原候选；不接受模型修改坐标或箱体属性；对当前原始状态做独立物理复核；通过后调用place。不得调用旧E2 commit后忽略异常，也不得将公开规则临时替换为空政策来伪装旧commit通过。

业务Parser与公开解释器可以保留，但在evaluate_only模式不能接入执行准入判定。独立参考评价器不参与prepare_candidates、排序、模型输入或提交。

## 8. 新版本与配置契约

建议新增`configs/jev_orders_business_eval_v2.json`，保留`jev_direct_v1.json`及原含义。下面仅列J3新增/变更项，**不是当前可执行的完整配置**：

```json
{
  "version": "jev_direct_choice_v2",
  "experiment_protocol": "jev_j3_physical_business_eval_v1",
  "business_mode": "evaluate_only",
  "selectable_pool": "physical_feasible",
  "candidate_backend": "e2_original_v1",
  "policy_source": "public_parser",
  "feature_version": "features_facts_v2",
  "prompt_version": "jev_business_eval_en_v2",
  "execution_version": "physical_commit_v1",
  "evaluation_version": "business_trajectory_v1",
  "memory_mode": "none",
  "buffer_capacity": 3,
  "per_object_top_k": 16,
  "joint_candidates_max": 48,
  "max_retries": 0,
  "confidence_policy": "record_only",
  "fallback": "none"
}
```

模型与原生接口沿用J2冻结配置；正式运行前核验官方版本/账户可用性和单价并冻结记录，不使用漂移alias。API预算归属plan而非模型请求；用户已授权不设人为上限，默认`--api-budget unlimited`，global/per-job记null。不得再次要求有限金额批准；仍保留次数账目和调用前reservation。

新增或分版本扩展CandidateBundle、DecisionContext、SelectionResult、plan/job、业务评价及metrics Schema。绑定至少覆盖protocol、business_mode、execution/evaluation版本、公开规格摘要、特征/提示摘要、数据/split/来源登记、空记忆、原有四项观测绑定及动作映射。Schema关闭未知字段，禁止v1/v2上下文交叉消费。

配置组合错误应在prepare时失败：例如evaluate_only配hard业务池、v2问题配旧allowed=true特征、旧业务commit配evaluate_only、参考评价派生特征混入主事实版。

## 9. 违规指标与空间指标

### 9.1 不用一个违规数混淆不同问题

令提交后独立评价得到的违规实例集合为V_t。整单从空托盘开始时V_0为空；固定状态诊断应使用真实初始违规集合。实例身份应规范化为`规则ID＋对象ID`或`规则ID＋规范对象对`，不能只数违反了几种规则。接触对可按无序对规范化，相对位置的subject/reference有方向，不能将反向约束合并。

| 指标 | 定义及用途 |
|---|---|
| `completed` | 已放件数等于计划件数；与违规无关 |
| `clean_completed` | 全部放完且轨迹中没有已评价的业务违规；严格合规完成 |
| `final_clean_completed` | 全部放完且最终V_T为空；用于区别曾违规后恢复的轨迹 |
| `final_violation_instances` | 最终已放状态的违规实例数 |
| `new_violation_events` | Σ\|V_t − V_(t−1)\|；持续存在的同一违规不会每步重复记为新产生，消失后再次出现算新事件 |
| `unique_violation_instances` | \|并集V_t\|；整条轨迹曾出现的不同实例数 |
| `violating_steps` | V_t非空的已提交步骤数；会随持续时间累积，不能称为新违规次数 |
| `new_violations_per_100_planned_items` | 100×new_violation_events/计划件数；与完成比例联合报告 |
| `rule_coverage` | 各规则被评价的对象/对象对数量，及deferred/not_applicable数量 |

保留原始违规字符串/结构与规范身份映射；不能只输出一个无单位的加权总分。按业务类型分别报告禁压/业务超载/接触/区域/相对位置；业务超载kg、区域越界或相对间距不足mm可作类型内严重度，不能直接跨单位求和。

未放箱、未到货箱及deferred关系不能算“已满足”；也不能直接当成实测违规。报告pending/unarrived、计划规则覆盖及unknown/deferred。提前停止的低违规不能解读为更好。

### 9.2 空间与完成情况

必须记录已放件数/计划件数、已放体积/订单总体积、固定托盘体积利用率、最终垛高、终止原因与物理失败。

同一订单全部放完且托盘尺寸相同，固定托盘体积利用率必然相同；不能用它声称布局更好。完成订单比较垛高，必要时比较占用包络利用率；包络定义、空状态处理和坐标范围算法提前冻结。未完成订单同时报告装入比例，不用低垛高掩盖少放箱。

空间与业务结果采用多指标/帕累托分析，不在结果出来后选择最有利权重。主表同时展示完成率、完整合规完成率、违规事件和装入比例；垛高比较应注明是否仅限方法共同完成的订单，避免成功子集偏差。

### 9.3 时间、成本与统计单元

记录API P50/P95、单步端到端、物理候选生成、事实特征、方法自身业务计算、独立评价、持久化及整单墙钟耗时。测量边界固定；回放复用原请求延迟，不把回放速度算作模型速度。

首次实现串行workers=1；冻结job顺序。报告缓存命中和冷/热条件，或用独立job进程形成可比较的计时环境，并把进程启动单列。不能让Jev默认享受基线预热缓存后声称推理更快。

Jev调用的自然上界为所有Jev job的计划件数之和（重复配置/seed按job计入），本地基线不消耗调用；实际次数取决于singleton、物理停止及服务失败。该上界不是另加的费用限制。

保存请求/响应字节、served_model、原始概率/confidence、usage、实际网络尝试与未知发送。usage缺失为null，总费用不完整时保持null，已知部分费用单列；unlimited不代表不记账。

按来源订单分组做配对差异，重复seed、业务配置及模型重复不是独立来源。建议来源级bootstrap区间，固定重采样seed；来源数太少时展示逐来源结果，不作强显著性结论。ID/几何OOD/语义OOD分层报告，并注明受控业务任务对原OOD标签的适用范围。

## 10. 状态机、批量执行与回放

主流程：到货 → 当前公共观测 → 全物理候选 → 公开事实/业务说明 → 方法选择Cxx → 重建绑定 → 物理提交 → 保存已提交状态 → 独立业务评价 → 下一次到货/选择。

业务评价结果不能进入下一步模型输入；下一步只根据当前公共状态重新计算其版本允许的事实。尤其不能将包含来源、参考诊断和未来信息的原始事件作为历史提示。

批量plan允许本地方法与Jev同表登记；本地job不调用API，remote job不能导入testing。正式运行前冻结全部job分母和来源数，运行中生成per-job状态：NOT_RUN/RUNNING/RECORDED/FAILED/INTERRUPTED。接口错误不删除job，不静默改为本地选择。

检查点需区分回答已保存、动作已提交、评价已保存。若评价失败，保存已经提交的动作/状态并标记EVALUATION_ERROR；恢复只补做评价，不重复请求和放箱。未知发送继续按J2规则不自动重发。

回放重新生成物理候选、重算事实、核对完整Cxx映射、解析保存回答、执行同一物理动作及独立评价。对映射、模式、违规事件、汇总、预算、registry、已提交检查点等篡改，即使重签文件清单，也应被派生关系检查拒绝。摘要不是抗恶意一致重写的数字签名。

## 11. CLI与产物契约（待实现）

以下是J3目标命令，当前J2入口尚不支持这些新增profiles/配置，不能当作现有功能执行：

```text
python -m semantic_pallet_planner.jev_select prepare
  --profile dataset-orders --dataset-root <V1目录>
  --business-spec <公开任务定义.json> --split-manifest <分组划分.json>
  --config <jev_orders_business_eval_v2.json>
  --methods shared_geometry shared_business_lexicographic jev_choice
  --mode remote --api-budget unlimited --output <新计划>

python -m semantic_pallet_planner.jev_select validate-plan --plan <计划>
python -m semantic_pallet_planner.jev_select preflight --plan <计划>
  --api-key-file <用户指定本地密钥文件>
python -m semantic_pallet_planner.jev_select run --plan <计划>
  --output <新实验> --remote --api-budget unlimited --api-key-file <密钥文件>
python -m semantic_pallet_planner.jev_select run --plan <同计划>
  --output <同实验> --remote --api-budget unlimited --api-key-file <密钥文件> --resume
python -m semantic_pallet_planner.jev_select replay --experiment <实验>
```

prepare/validate/replay为0网络；preflight不调用模型、不输出密钥。使用J2已支持的环境变量或显式本地文件凭证，继续忽略typesafe_api_key.md；密钥不进入源码、配置、原生体、源码快照及实验日志。原生接口不增加不受支持的Chat字段。

产物统一写入`semantic_pallet_planner/outputs/`，建议：

```text
PLAN_JEV_J3_<id>/
  plan.json / config.snapshot.json / source_manifest.json / code_snapshot/
  public/business_spec.json / public/attribute_generation.json
  private/input_snapshot.json / private/reference_specs.json
  input_manifest.json / split_audit.json / inclusion_exclusion.json
  task_registry.json / job_registry.json / feature_prompt_manifest.json
  delivery_manifest.json

EXP_JEV_J3_<id>/
  plan/ / manifest.json / audit/attempts.json / audit/jobs.json
  requests/ / mappings/ / checkpoints/ / episodes/
  metrics/rows.json / metrics/summary.json / metrics/by_rule.json
  metrics/by_source.json / metrics/timings.json
  replay_report.json / acceptance_report.json / delivery_manifest.json
```

文件路径只是组织示意，必须在实现中固定Schema和真实校验规则。所有计划和运行拒绝覆盖。J2旧计划依赖旧源码，新增生产代码后在当前环境校验旧产物可能报source_changed；旧证据保留，使用其冻结源码复现，不覆盖成J3产物。

## 12. 分阶段开发工作量与门槛

工作量为熟悉工程的单人估计，非交付时限承诺；不含等待API、数据缺失处理和论文撰写。

| 子阶段 | 工作量 | 具体任务 | 完成门槛 |
|---|---|---|---|
| J3.0 语义与执行改造 | 中，约2—3人日 | v2配置/Schema、物理池、事实输入、物理提交、非终止业务评价 | 违规候选实际可提交且下一步继续；旧v1保留 |
| J3.1 数据与来源冻结 | 中到高，约2—4人日 | dataset适配、公开业务规格/合成标签、来源分组、覆盖审计、静态排除清单 | 无未来/参考泄漏；任务与split可复算；缺失参数禁止正式运行 |
| J3.2 同池对照与指标 | 中，约2—3人日 | 业务启发式、轨迹指标、时间边界、混合job/remote解禁 | 三方法同初始条件；完整分母；错误分类/成本准确 |
| J3.3 离线验收与真实开发单 | 中，约1—2人日 | 全违规、持续违规、物理反例、恢复、篡改；开发集真实小批量 | 工程测试及0网络回放通过，真实回答已保存 |
| J3.4 正式冻结批量与分析 | 中，约1—3人日＋运行时间 | 锁定测试plan、真实Jev、配对/分层报告、案例分析 | 全job有状态、结果可复现，失败如实报告，不以提升为门槛 |

总体约8—15人日，主要不确定性是数据适配、业务/物理属性分离及批量恢复。J3.0先做，不应在仍有硬业务过滤时直接批量花费API。

## 13. 具体工程验收清单

| ID | 场景/检查 | 必须满足 |
|---|---|---|
| A01 | 业务合法与违规动作同时物理可行 | 两者都进入同一模型池，完整动作不变 |
| A02 | 全部物理候选均业务违规 | 不出现业务STOP；模型/基线必须选项 |
| A03 | 唯一候选违反业务 | 不调用API，自动物理提交，记录违规并继续 |
| A04 | 已有违规，后续另一个箱仍可放 | 不因after.allowed=false拒绝所有后续动作 |
| A05 | 业务禁压而物理可堆叠 | 选中堆叠可提交，评价报业务禁压 |
| A06 | 超业务限载但未超物理承载 | 可提交；超过物理承载则拒绝，两个原因不混用 |
| A07 | 禁接触/区域/相对位置 | 每种规则存在真实非零违规见证，提交不被业务拒绝 |
| A08 | 碰撞、越界、支撑不足、不可堆叠 | 无论业务模式均不能提交 |
| A09 | 一个缓冲箱无候选、另一个有候选 | 联合池非空，仍可选择另一个箱 |
| A10 | 全联合物理池为空 | 明确物理停止，非业务失败/非全局无解证明 |
| A11 | 模型输入 | 无allowed=true假标记、私有答案、原始来源ID、未来箱/数量/序列 |
| A12 | 主特征与增强特征 | 版本/提示/Schema不同，主事实版不含程序业务答案 |
| A13 | 物理提交与编号 | 实际箱体/位置等于Cxx对应动作，不调用旧choose覆盖 |
| A14 | 无效回答、超时、429/529 | 停止类别明确，账目保留，0自动改选/重试 |
| A15 | 下游参考政策改变 | 同一公共观测的候选/模型体/动作提议不变，仅评价改变 |
| A16 | 未到货订单后缀改变 | 当前候选、公共事实和原生请求完全不变 |
| A17 | 违规连续持续3步 | 1个新增事件、1个唯一实例、3个违规步骤，而非3次新违规 |
| A18 | 违规消失后再次出现 | 新事件再次计数，唯一实例按身份去重 |
| A19 | deferred/未到货/未完成 | 不算已满足；明确coverage与missing，不伪造低违规成功 |
| A20 | 订单完成但有违规 | completed=true、clean_completed=false；不伪装执行错误 |
| A21 | 三方法初始公共状态相同 | 物理池/事实/排列相同；分叉后按各自状态重算 |
| A22 | 业务启发式全项违规 | 仍返回动作，不变成硬屏障 |
| A23 | 数据来源、变体与切分 | 同源组不跨train/test；语言/buffer变体不当独立样本 |
| A24 | 原V1作业单与受控派生任务 | 公开来源标签不同，语义不兼容不静默转换私有GT |
| A25 | 日志与检查点恢复 | 回答后/提交前/提交后评价前/评价后中断，均不重复调用或放箱 |
| A26 | unknown发送与预算 | unlimited照样记账，unknown不重发；可选有限预算不被静默提高 |
| A27 | 无网络回放 | 不读密钥、不调用API；远程实验回放不导入testing，离线实验可校验冻结替身；派生结果一致 |
| A28 | 篡改并重签清单 | 模式、映射、响应、违规事件、汇总、registry、预算或检查点篡改被拒绝 |
| A29 | 计时、usage、费用 | 分清API/几何/特征/独立评价；缺失usage不填0；回放不新计费 |
| A30 | 多方法任务分母 | 失败/中断/NOT_RUN均保留，不能只统计成功订单 |
| A31 | v1/v2与历史产物 | 旧硬业务实验保留；新模式不能读取旧回答继续提交 |
| A32 | 打包与代码归属 | 新代码/资源/测试均在jev_select；wheel带资源不带tests；非cwd运行通过 |

A01—A32是工程门槛，不是模型性能门槛。真实开发单允许产生业务违规，但必须真实记录且不因该违规中断；不得为了得到0违规修改评价器或切回硬mask。

## 14. 研究结果验收与交付

必须交付：代码及包内README、v2配置/Schema、完整公开任务定义、属性生成与来源审计、冻结数据/方法/特征/提示/模型/价格、全部job登记、断网工程测试、真实开发单、正式订单逐来源结果、时间/成本与恢复/回放证据。

正式报告至少回答：

1. Jev是否提高装入/完成，代价是否是更多业务违规？
2. 在相同完成水平下，业务违规是否减少？在共同完成订单上垛高是否更好？
3. 与简单公开规则启发式相比，是否仍有收益，而不仅是胜过忽略业务的几何方法？
4. 收益/失败集中在哪些规则、属性组合、空间压力与来源分层？有多少规则实际上从未触发？
5. 哪些是物理池限制、服务问题、公开规则解析问题，哪些才是选择策略导致的后续受阻？

“同一状态选了另一个候选”不是长期策略更优的充分证据。案例分析需展示实际后续轨迹；如追加反事实分支，必须固定后续策略、模拟预算并仅用于离线分析，不将未来信息回灌当前模型。

如果Jev与业务启发式接近或更差，应如实给出负结果，并据此决定J4经验要优化哪些长期选箱/留空间策略；不能把本次工程接入重新包装成模型创新。

## 15. 工程依据与阅读入口

- [Jev总体开发规范](Jev直接候选选择接入开发与验收规范_20261029.md)
- [J1离线验收](../../03_阶段产出分析/O4/Jev_J1开发与离线验收_20261029.md)
- [J2真实接口与冒烟验收](../../03_阶段产出分析/O4/Jev_J2真实接口开发与冒烟验收_20261029.md)
- [包内README](../../../semantic_pallet_planner/src/semantic_pallet_planner/jev_select/README.md)
- [当前候选与过滤](../../../semantic_pallet_planner/src/semantic_pallet_planner/jev_select/candidates.py)
- [当前上下文与问题模板](../../../semantic_pallet_planner/src/semantic_pallet_planner/jev_select/context.py)
- [当前提交状态机](../../../semantic_pallet_planner/src/semantic_pallet_planner/jev_select/episode.py)
- [当前统计](../../../semantic_pallet_planner/src/semantic_pallet_planner/jev_select/evaluation.py)
- [旧E2业务commit：J3物理提交不能直接沿用](../../../semantic_pallet_planner/src/semantic_pallet_planner/o4/extensions/e2/planning.py)
- [buffer物理提交与守恒](../../../semantic_pallet_planner/src/semantic_pallet_planner/o4/buffer/buffer_state.py)
- [独立物理检查器](../../../semantic_pallet_planner/src/semantic_pallet_planner/evaluation/geometry_oracle.py)
- [V1数据集说明](../../../semantic_pallet_dataset_v1/docs/dataset_v1解析.md)

**J3的架构：当前公开状态与业务要求 → 全部物理可行候选 → Jev/同池基线选择 → 绑定与物理提交 → 独立业务评价、持续执行 → 完成/空间/业务/成本的整单对照。**
