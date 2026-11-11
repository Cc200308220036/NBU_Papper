# NBU_Papper：混合码垛规划与Jev经验增强研究

本项目研究具有**尺寸、实际重量和包装承载属性**的混合码垛：公共规划器生成可执行的“箱体＋精确位置”候选，Jev根据当前可观察状态作选择，公共静态稳定性监测决定提交或停单；再通过训练来源上的有限分叉构建案例与对比经验，研究经验能否改善后续选箱和布局。

**新智能体先读[AGENTS.md](AGENTS.md)，再读本文。** AGENTS规定协作、授权、证据与保护规则；本文解释项目目标、架构、技术路线和开发入口。阶段任务、实验额度和验收结论以对应规范、报告、handoff及manifest为准，不能从README推导出实验授权。

本文于2026-11-11依据代码与阶段材料更新，核对基线为`114ef898`。当前JM1-A1已交付构造工程，等待独立质检；JM1-A2/A3及新路线真实实验尚未实施。本次README更新只做文档与路径核对，没有重跑历史验收或实验。

## 1. 研究问题与技术边界

研究重点是当前选箱和位置对后续可装入量、空间紧凑性及承载资源保留的影响。目标不止是让当前箱子合法落位，还包括在有限缓冲与逐步到货条件下完成尽可能多的整单装载。

| 概念 | 在本项目中的含义 |
|---|---|
| 公共候选 | 原规划器按当前状态产生、通过原物理约束检查的完整动作；一个候选同时指定箱体和精确姿态。 |
| Jev | 从候选中选择标签`Cxx`的模型。标签经显示映射解析为不可变候选ID及精确动作；当前主线不让模型生成坐标或AST。 |
| 无经验选择 | 使用当前公开状态和候选，`memories=[]`。 |
| T案例 | 从已保存轨迹/分叉证据构建的可检索案例表示。 |
| E对比经验 | 文本LLM（已有路线使用DeepSeek）从对比证据提炼的条件化经验；须区分事实、推断、适用条件与反例。 |
| 分叉 | 从同一保存前状态和同一候选池出发，比较原动作参考、同箱换位/朝向及跨箱动作，随后采用同一后续策略。 |
| 经验增强 | 外部案例/经验检索与请求注入，不是模型权重更新或训练。 |

当前主线以结构化事实为输入，模型范围为轴对齐0/90度、均匀刚性箱和竖直准静态接触反力。几何尺寸使用mm，质量使用kg；坐标、姿态和内核转换以具体Schema及`stability/geometry.py`为准，不自行混用中心坐标与角点坐标。

包装承载参数包含合成属性，必须保留其来源说明。当前任务不默认启用旧业务区域、食品清洁品相容性或相对方位规则，也不涉及冲击、摩擦滑移、变形、真实坍塌动力学、机械臂控制或运动路径规划。仓库保留这些历史方向的部分代码，不代表当前任务授权使用。

## 2. 一次决策如何执行

```text
完整订单与到货序列
    ↓ 按公共规则填充有限缓冲
当前状态 → 原公共候选池 → 结构化公开上下文
                              ↓
                   无经验选择 / 冻结T或E注入后选择
                              ↓
                   Cxx → 不可变候选ID → 精确动作
                              ↓
                        保存 SELECTED
                              ↓
                    独立副本上的选后静态监测
                              ↓
                        保存 MONITORED
                              ↓
         STABLE → 原物理复核与提交 → COMMITTED → 下一步
         其他状态 → 分类停单，失败箱留在缓冲
```

公共候选器采用极值点/支撑层等现有几何枚举和TopK机制；现有公共配置每箱TopK为16、缓冲至多3箱，联合候选至多48个。它是有限采样池，`EMPTY_POOL`不能解释为全局无解。不得为改善成绩改变候选器、TopK、容差或包装参数。

选择器可见的是当前容器、已放箱体、缓冲箱体的公开属性、候选及允许注入的经验。完整任务虽然保存在本地供到货与评价使用，未来箱体、见证、参考动作、测试结果及监测预评不能进入模型请求或检索查询。

| 监测状态 | 提交与账目行为 |
|---|---|
| `STABLE` | 调用原`commit_physical`复核后提交一次，更新缓冲与装入账目。 |
| `UNSTABLE` | 记录预测静态失稳并停单；不放失败箱、不移出缓冲、不增加件数/体积/质量。 |
| `UNASSESSABLE` | 按监测适用范围或不可评价原因停单，不能混为预测失稳。 |
| `ERROR` | 按技术错误停单，保留诊断。 |
| `DISABLED` | 旧协议在显式关闭监测时的独立状态，不得写成STABLE；新JM构造首步要求监测开启。 |

监测仅作用于**已经选定的精确动作**：禁止用PCT预过滤/排序候选、向模型泄漏监测诊断、失稳后改选下一候选或静默回退旧算法。原边界、碰撞、支撑、stackable及包装承载检查继续生效；原面积分载账本和静态反力结果分别保存，不互相回写。

## 3. 代码架构与修改入口

主Python包位于`semantic_pallet_planner/src/semantic_pallet_planner/`。下表路径均相对于该包；当前研究开发主要集中在`jev_select/`。

| 模块/目录 | 职责与开发时的读取重点 |
|---|---|
| `planner/`、`domain.py`、`evaluation/geometry_oracle.py` | 原几何枚举、评分、物理属性与独立合法性检查，是公共物理基础。 |
| `o4/buffer/buffer_state.py`、`o4/extensions/e2/` | 缓冲状态、到货、放置、公开observation及精确动作转换；历史业务能力也在此树内。 |
| `jev_select/candidates.py` | `CandidateProvider`、公共候选池及物理候选完整性检查。 |
| `jev_select/packaging_runtime.py`、`context.py` | 包装数据运行视图、公开状态/特征、上下文构建、显示映射及绑定校验；本地替身也在runtime中。 |
| `jev_select/selector.py`、`transport.py` | 原生Choice解析、概率/标签校验、选择结果及传输边界；真实发送需专门授权。 |
| `jev_select/episode.py` | 公共`run_episode`订单循环、选择/监测/提交的阶段持久化及版本路由。新增能力优先接入这里，不能复制订单引擎。 |
| `jev_select/execution.py` | `commit_physical`原物理复核和提交入口，不接受模型绕过物理检查。 |
| `jev_select/packaging_remote.py`、`ledger.py` | 无经验远程选择、请求账本、文件持久化及单次发送保护；发送不明保留`UNKNOWN_SEND`等实际状态，不隐式重试。 |
| `jev_select/stability/` | 选后监测、冻结身份、几何桥接、静态接触网络与求解、监测凭据及恢复校验。 |
| `jev_select/packaging_orders.py`、`packaging_*_orders.py` | 完整订单计划、批次执行与实验协议编排；合成、精确位置和历史补充执行分别有专用模块。 |
| `jev_select/packaging_counterfactual.py` | 历史JN2分叉：后续固定为`local_geometry_test_double`，不能将其改名冒充新JM真实Jev后续。 |
| `jev_select/packaging_jev_forks.py` | 新JM1-A1：保存证据绑定、独立状态复制、同池强制首步；当前后续明确NOT_IMPLEMENTED，resume拒绝至A3实现。 |
| `jev_select/packaging_experience.py`、`packaging_contrast*.py` | 既有T案例、E事实包/生成/审核及快照工程；旧内容不自动获得新JM执行资格。 |
| `jev_select/packaging_pilot_memory.py`、`packaging_evaluation_memory.py` | 既有逐决策MemoryView、检索与注入凭据；当前缺陷和新方案要求须结合报告读取。 |
| `jev_select/packaging_source_*.py`、`packaging_synthetic_data.py` | 来源审计、正向来源证据及合成身份/关系；换种子或未命中重复检测不能证明独立来源。 |
| `jev_select/packaging_metrics.py`、`packaging_reanalysis.py`、`evaluation.py` | 完整分母指标、分支比较规则及公共评价路由。 |
| `jev_select/contracts.py`、`schemas/`、`packaging_versions.py` | 封闭Schema、摘要绑定和显式版本注册；另读所用`packaging_*_protocol.py`的具体方法注册与身份检查。 |

### 各模块的功能与重点实现

下面按运行和研究的数据流解释实现。除另行注明外，模块入口均位于`jev_select/`；“已有工程”描述可读源码，不代表其在新JM协议下已完成真实验收。

#### A. 数据适配与订单状态

**功能：** 将冻结任务转换为可逐步到货的运行对象，维护真实缓冲、已放布局和完整订单分母。

**实现：** `packaging_runtime.runtime_task`保留尺寸、质量、stackable和合成承载上限，并适配公共物理接口需要的属性字段。`o4/buffer/buffer_state.py`用`initial/receive/place`集中维护状态，记录`pending_items`、`placed_items`、`arrived_ids`、到货索引、计数与EOS；`invariant`检查“已到货箱体＝已放箱体＋待放箱体”、唯一ID、容量和计数一致性。状态变更使用独立副本。公共`run_episode`持有完整到货序列和cursor，选择器只收到当前observation。

**输出与边界：** 本地task、当前状态及公开observation是不同对象。修改到货/缓冲行为应沿公共状态机完成，不能通过向模型暴露完整task解决选箱问题。

#### B. 公共物理候选生成

**功能：** 将当前缓冲内所有可选箱体展开为可执行的精确位置候选，定义所有选择方法共同的动作空间。

**实现：** `candidates.CandidateProvider.build`逐箱调用现有E2候选生成链，复用`planner/`中的几何枚举、评分与TopK；每个候选再经过独立`geometry_oracle.check_candidate`检查。bundle同时保存完整物理候选、可选候选、生成统计和摘要。包装物理协议下`PublicBusinessGuard.filter`保持物理候选完整进入可选池，不引入旧业务筛选。`validate_bundle`核对observation绑定、摘要、候选唯一性与子集一致性。

**输出与边界：** 输出`CandidateBundle`，候选包含箱体ID、姿态和朝向尺寸。候选数决定空池停止、单候选自动执行或多候选选择；PCT不参与此处生成和排序。新增selector应消费这个bundle，而非另造候选空间。

#### C. 公开事实、承载描述与标签映射

**功能：** 把运行对象转成模型可理解且可审计的结构化状态和候选描述。

**实现：** `packaging_runtime.public_facts`为当前箱体生成局部别名，投影容器、已放/待放箱体、质量、尺寸、位置和承载资源。`layout_facts`按实际接触矩形面积形成支撑分配，沿高度从上向下累计已有载荷；`resources`计算有效上方承载许可、当前顶载和剩余承载。候选的`load_changes`通过在副本上应用精确候选后计算，用于描述原物理账本的增量，**不是提前运行静态稳定性监测**。

显示顺序由配置种子和当前请求/状态身份确定，形成`C01…Cxx`；`display_mapping`逐项绑定candidate ID、箱体ID及候选摘要。`build_context`将公开状态、criteria、请求正文与本地绑定封装为`DecisionContext`，`validate_context`检查这些对象相互一致。分叉复用保存映射，不重新洗牌。

**输出与边界：** 模型收到公开状态和完整criteria；完整task、私有来源、未来到货与PCT诊断不进入请求。候选标签只在本次上下文有效，不能把“选C02”保存为通用经验。

#### D. Jev选择、响应校验与发送账本

**功能：** 在同一公开上下文中选择一个已有动作，并明确区分真实调用、本地替身和自动执行。

**实现：** `selector.parse_response`严格解析原生Choice JSON，核对模型、问题键、候选标签、完整概率键、数值范围、概率和以及所选项是否为最大值；按具体协议处理允许的舍入，不修复非法选择。`resolve_display_id`将标签还原为原候选，选择结果保留上下文绑定摘要和原始响应身份。单候选普通路径自动执行，不发送模型请求。

`packaging_remote.RequestLedger`按job/decision保存请求意图、发送中、响应已存和选择已存等阶段，配合独占写锁和文件持久化限制重复发送。发送结果不明时保存UNKNOWN_SEND等实际状态并停止；已有合法响应可用于后续解析，不重新请求。不同实验协议通过专用工厂和账本校验config、方法及预算身份。

**输出与边界：** 输出`SelectionResult`和请求/响应证据，不直接修改布局。无效响应、提供方失败和未知发送不能由几何方法代选。JM1-A2所需的独立后续账本仍待实现，不能直接将已有账本称为新JM验收完成。

#### E. 选后静态稳定性监测

**功能：** 判断已选动作与当前垛体在限定准静态模型内是否可接受，提供带身份绑定的提交凭据。

**实现：** `stability.monitor.monitor_selected_action`通过`geometry.py`转换当前状态与精确动作，并按冻结算法显式派发。v3的`exact_adapter`在选定姿态上寻找正面积接触矩形，检查越界、重叠、悬空和退化支撑；不通过模拟自由下落改变动作。`balance_network.solve_network`将接触矩形角点上的非负竖直反力作为未知量，对每个箱体建立竖直力与水平力矩平衡，使用线性规划检查可行性、保守支撑凸包和内部裕量，并校验反力及守恒残差。不可行结果须有经检查的证据才能归为预测失稳，边界/范围与数值问题分别分类。

监测记录绑定前状态、候选、action、selection、context、bundle、config及运行身份；`validate_monitor`只核对保存凭据，不重新求解。原面积分载数据继续由原物理链维护，不用求解反力覆盖它。

**输出与边界：** 输出STABLE/UNSTABLE/UNASSESSABLE/ERROR及证据，交回订单引擎决定提交或终止。监测失败不得生成新的选择，也不能把求解器诊断反馈给当前选择器。

#### F. 公共提交、阶段恢复与批次编排

**功能：** 将选定且获准的动作提交到唯一状态机，保证选择、监测和账目沿同一条链路衔接。

**实现：** `episode.run_episode`负责填充缓冲、决策、持久化阶段、评价和终止；`execution.commit_physical`在提交前重核当前observation、bundle、context、selection、监测凭据及原物理检查，最后调用公共`place`。失败动作不扣减缓冲。checkpoint共同保存状态、cursor、decision、已完成事件和pending event，避免用零散文件推断是否已提交。

已有监测协议按SELECTED复用选择、MONITORED复用结果、COMMITTED补完下游评价的原则恢复；具体校验入口依版本而定。`packaging_*_orders.py`在公共引擎外冻结任务/方法矩阵、管理job、预算、状态及剩余未运行分母，不另建物理模拟器。

**输出与边界：** 输出事件、checkpoint、终止原因、布局和指标。新增协议必须逐阶段验收恢复；JM1-A1当前拒绝resume，不提供跨调用或跨窗口恰好一次承诺。

#### G. 同起点分叉与动作干预

**功能：** 在可审计的同前缀、同池条件下比较动作差异，构建后续案例/经验的原始证据。

**实现：** 历史`packaging_counterfactual.restore_training_fork`读取保存材料并校验前状态、到货进度、池和映射；旧执行后续固定为几何替身。新`packaging_jev_forks.freeze_start`把父receipt、文件SHA256、JSON指针、task和snapshot绑定成起点；`bind_branch`只接受保存映射已有标签，绑定新分支ID、原候选及精确action，并区分原动作参考、同箱不同姿态和跨箱选择。

`bootstrap`深复制状态、cursor、缓冲与原池，创建新SELECTED检查点；强制选择使用独立版本凭据和`FORCED_FROM_FROZEN_POOL`来源，计强制动作一次、模型调用零次。首步仍沿公共监测/提交；成功后停在`JM_CONTINUATION_NOT_IMPLEMENTED`，失败即停分支。

**输出与边界：** A1输出绑定和构造首步证据，只允许构造起点执行；归档起点不获执行准入。采点器、真实无经验Jev后续、独立发送账本和完整恢复分别属于后续单元，不能把它们当作现有能力。

#### H. T案例与E对比经验构建

**功能：** 将原始轨迹与分支结果转换成可追溯、可审核的外部记忆，保留收益、代价、失败和适用限制。

**实现：** `packaging_reanalysis`先从同起点参考/替代记录构建比较；`packaging_experience`通过文件摘要、JSON指针和取值摘要连接私有证据，再用白名单投影生成公开案例片段，以局部动作角色及归一化几何描述历史条件。完整私有轨迹不直接放入请求。

既有`packaging_contrast`构建带fact ID和value digest的事实包，生成请求只提供冻结事实、允许的声明语法及输出Schema。生成结果可拒绝提炼；`fact_audit`检查逐声明依据、条件、成本和限制是否完整，`semantic_review`执行独立的确定性规则审查，再渲染卡片并冻结快照。这套旧审核是受限语法审核，不等于JM规划中的真实双人内容审核；旧E也不是任意自由文本经验。

**输出与边界：** 输出带provenance、公开片段、检索描述和审核身份的T/E快照。新JM要求共同特征、非空历史投影、动作角色与FACT_CASE/CANDIDATE_MEMORY/EXECUTION_ELIGIBLE分层，相关改造未因旧快照存在而完成。

#### I. 经验检索、MemoryView与请求注入

**功能：** 每一步只从冻结库中选择允许公开的适用内容，并证明究竟检索到什么、实际注入了什么。

**实现：** 已有检索将缓冲占用、垛体占用、尺寸/质量/承载均值、可堆叠比例及候选高度等组成九维公开特征；采用归一化特征的平均绝对距离，按`1/(1+d)`计算分数，阈值0.5、最多一条，并排除配置中注册的来源/分叉。字符和UTF-8预算按整条内容检查，不截掉条件或限制凑长度。这是既有实现，特征口径和适用门控不足已有分析记录。

`packaging_pilot_memory.MemoryDriver`从当前公开state/criteria生成query，输出显式`MemoryView`与retrieval receipt；`build_context`验证快照、query、view和注入内容摘要后填入`memories`。none模式始终为空。恢复路径验证保存query/view/receipt的关系，不重新检索；评价协议还支持无关E对照，保留参考检索与实际注入的区别。

**输出与边界：** 库非空、检索非空、视图非空、实际请求发送非空分别统计。新JM的阶段/动作角色/公开前提/冲突/执行白名单门控属于计划中的R1，尚不能将旧距离检索描述为已具备这些判断。

#### J. 来源隔离、指标比较与证据交付

**功能：** 约束数据泄漏和结论范围，使工程结果与研究结果可以分别复核。

**实现：** `packaging_source_audit`用原始身份/别名、允许0/90旋转的尺寸质量多重集和近重复关系形成保守连通分组；`packaging_source_provenance`另检查来源声明与正向证据，未发现重复不等于来源独立。JM的六用途分区及祖先关系要求还须按冻结合同单独验证，旧静态checker不足不能作为生产准入证明。

`packaging_metrics`等从完整task和保存提交状态计算装入分母与结果；`packaging_reanalysis.evaluate`先检查配对task/data/分母、有效终止类别和指标一致性，再按“稳定完整完成 → 体积装入比例 → 件数/质量Pareto → 装入等价后的高度/包络Pareto”逐层比较，保留反向代价与技术无效配对。报告、source identity、handoff与manifest把结果连回实际源码、配置、数据和运行记录；viewer用这些保存证据解释动作和经验命中。

**输出与边界：** 输出完整分母指标、比较标签及证据链，不以统一PASS掩盖部分完成/失败，也不把共享素材、多次注入或多方法槽位计成独立来源。收益是否成立必须回到冻结对照与实际结果判断。

### 协议版本必须配套使用

运行协议、Schema、方法、数据及监测算法有各自版本，不能用一个“最新版本号”替代全部身份。

| 协议/算法 | 定位 |
|---|---|
| 包装运行v4 / 监测v5 / 远程Choice v6 | 包装属性主链逐步接入的基础协议，旧行为继续保留。 |
| T v7 / E v8 / 逐决策记忆订单v9 | 已有经验表示与运行协议。 |
| 统一评价v10 / 合成v11 / 精确位置v12 | 不同实验合同；v12通过`packaging_exact_protocol.py`使用精确位置监测。 |
| `pct_contact_network_v2` | `stability/balance_adapter.py`与`balance_contracts.py`的修正版静态内核。 |
| `pct_exact_pose_network_v3` | `stability/exact_adapter.py`与`exact_contracts.py`；按选定精确姿态建立真实接触，不把动作改成垂直下落后的另一姿态。 |
| `jev_jm_fork_start_v1` / `jev_jm_fork_binding_v1` / `jev_jm_forced_selection_v1` | 新JM分叉起点、绑定与强制选择协议；适配保存的v6/v12包络，不替换旧分叉或放宽旧Schema。 |

`stability`根包的旧`assess_candidate`入口不是当前精确位置监测入口，禁止自动回退。静态内核仍有严格内部反力、保守支撑凸包及退化情况的不可评价边界；STABLE不等于真实世界不会坍塌。

公共引擎已具有`SELECTED → MONITORED → COMMITTED/TERMINATED`阶段语义，但**某一新协议的恢复是否开放须单独验收**。例如JM1-A1仅支持构造首步，不能因为公共引擎有恢复代码就宣称新JM的完整恢复和重复槽位已完成。

## 4. 技术路线、当前状态与证据边界

项目从确定性几何规划、O3/O4语义规则编译，演进到Jev直接候选选择和包装承载研究。旧路线保留复现价值；当前开发应从Jev阶段文档进入，不直接沿旧O4或通用CLI的历史默认配置开展新实验。

| 路线/阶段 | 已有事实与下一边界 |
|---|---|
| 早期确定性规划、O3/O4 | 建立候选、规则解析/AST、独立评价、缓冲与实验基础；历史结论按原报告读取，当前包装主线不默认启用旧业务规则。 |
| Jev J1—J4、JN0—JN3 | 已有原生Choice、完整订单、包装属性、选后监测、分叉与T/E真实注入工程；不同阶段和版本的证据不能合并成统一效果结论。 |
| JN4—JN5 | 已交付合成路线限定实验与分析。主分析中T相对无经验有改善也有退化，E未建立一致收益；共享素材、小样本与缺少重复限制泛化结论。 |
| JM0-A/B | 已交付接口/来源审查、研究与准入合同；JM0-B独立质检只准入A1构造工程，未授予真实来源或实验执行资格。 |
| JM1-A1 | 已交付分叉绑定、状态复制和`FORCED_FROM_FROZEN_POOL`首步；首步构造验收见下方报告，等待独立质检。 |
| JM1-A2 / A3 | 待实施：A2负责真实无经验Jev后续路由和独立账本，A3负责完整阶段恢复、未知发送及重复槽位。 |
| JM1后续—JM6 | 规划路线：训练采点/有限分叉 → 场景特征及新T/E → 适用性检索与准入 → 同状态内容对照/开发先导 → 冻结留出评价 → 分析交付。每单元分别授权、验收和停止。 |

新路线拟让所有分支在强制首步后统一使用**无经验Jev**，不能沿用旧几何后续构建“新Jev经验”。原动作参考也必须接同一后续策略；同起点局部改善不证明全局最优。

JM-plan-v2区分`FACT_CASE`、`CANDIDATE_MEMORY`、`EXECUTION_ELIGIBLE`：保存事实、可研究的候选经验、可用于执行的经验分别过门。T和E应同源；先检查公开特征口径、非空垛体投影、动作角色、适用条件、证据与反例，再验证相关内容相对无经验、无关内容及通用提醒的增量。ReMe等文献提供方法借鉴，当前JM合同未采用直接运行时集成、embedding或在线LLM重排；相关新能力仍以实际交付为准。

**开发前必读入口：**

- [JM-plan-v2分阶段方案](docs/02_阶段实施方案/Jev/Jev经验构建检索与无经验Jev分叉改进分阶段开发方案_20261109.md)：当前后续路线、子单元分工、验收和预算。
- [JM1-A1交付报告](docs/03_阶段产出分析/Jev/Jev_JM1-A1分叉绑定状态复制与强制首步验收_20261111_01.md)及[handoff](semantic_pallet_planner/outputs/JEV_JM1_A1_20261111_01/handoff.json)：已实现接口、构造范围、未实现后续及下一接口。
- [JM0-B独立质检与A1限定准入](docs/03_阶段产出分析/Jev/Jev_JM0-B独立质检与JM1-A1限定准入_20261111_01.md)：合同设计与数据准入校验覆盖不足的区别。
- [JN5最终限定分析](docs/03_阶段产出分析/Jev/Jev_JN5合成路线限定分析与证据整理验收_20261107_03.md)及[经验负收益分析](docs/03_阶段产出分析/Jev/Jev_JN4经验沉淀检索与负收益现象分析_20261109.md)：为什么要改造经验机制。
- [JN0—JN5公共规范](docs/02_阶段实施方案/Jev/Jev新数据完整订单与经验增强分阶段开发规范_20261103.md)：完整订单、公共物理/监测合同和指标定义。

这份状态概览只帮助定位。开发时继续从[验收索引](docs/03_阶段产出分析/Jev/README.md)检查是否已有后续报告，不把本段永久当作最新阶段台账。

## 5. 数据、产物与研究结论怎么读

| 仓库位置 | 用途 |
|---|---|
| `semantic_pallet_dataset_v1/` | 历史数据集与场景/任务资料，见其[说明](semantic_pallet_dataset_v1/README.md)。 |
| `semantic_pallet_planner/outputs/` | 当前主要数据交接、冻结计划、运行、验收及代码快照。 |
| `outputs/` | 部分历史产物，不能与planner下同名目录混用。 |
| `docs/02_阶段实施方案/Jev/` | 阶段合同与后续方案；文内拟议API不等于已实现接口。 |
| `docs/03_阶段产出分析/Jev/` | 阶段交付、质检、问题与研究分析；较早Jev报告仍保存在O4目录。 |
| `report/` | 汇报、离线分析和可视化；[JN4决策回看](report/visualization/Jev_JN4_六方法决策回看_20261107/README.md)可辅助理解已保存选择与经验注入。 |
| `raw/`、`Online-3D-BPP-PCT/` | 原始材料及第三方参考；文件存在不等于来源已准入，不自动更新或改写。 |

初始包装数据入口为`semantic_pallet_planner/outputs/DATA_JEV_PACKAGING_LOAD_20261102_02/`。进入具体任务先核对`manifest.json`、`handoff.json`、`source_manifest.json`、split和`data_identity`。既有16任务涉及已暴露来源及其变体，不能直接作为独立未见测试；同原始订单、近重复、包装变体、分叉与共享素材关系须按来源隔离。

读取一次交付时，先看报告的范围与限制，再沿handoff定位实际数据/源码/策略/监测/快照身份和delivery_manifest。运行包通常还包含task/config快照、请求账本、选择与监测阶段、checkpoint、动作、指标及最终布局；具体文件结构按该协议收据核对，不假定所有历史包一致。

必须分别表述**报告声明、代码实现、归档证据、本机复验**。工程链路通过、经验真实注入、研究收益成立是三个不同结论。高注入率、公共硬过滤得到的零违规、少装后的低垛高都不能单独证明选择策略更优。

整单评价同时看完成状态、件数/体积/质量装入比例、固定容器利用率、垛高/包络利用率、预测静态失稳进度、不可评价/技术失败、时延与成本；分母包含完整订单和全部注册槽位。未知或未实现指标记录UNKNOWN/NOT_RUN/NOT_IMPLEMENTED及适用NA，不补虚假0值。完整订单全部装入时，固定容器利用率本身不能区分布局质量。

## 6. 新智能体如何开始开发

1. 在已有工程根目录读取AGENTS和本README，检查目标树补充约定、`git status --short`及相关提交；保留其他窗口修改，不重新克隆或清理工作区。
2. 明确用户指定单元。从当前方案、最新报告、handoff和manifest建立基线；先核对实际文件与实现，不依据文件名日期或一个PASS判断准入。
3. 沿“公共候选 → 上下文 → selector → 监测 → commit → checkpoint”阅读相关源码，再定位具体`packaging_*_protocol.py`及封闭Schema。按上表复用公共链路。
4. 将拟议能力、已有实现和待补证据分开；新增协议显式版本化与集中路由，保留旧保护、历史失败、数据和快照身份。
5. 仅在已授权范围内实现并选择必要构造/公共回归。交付中文报告、证据、manifest/handoff及索引，达到该单元停止条件后停止。

Python包配置见[pyproject.toml](semantic_pallet_planner/pyproject.toml)，要求Python ≥3.11；基础依赖包括NumPy、Matplotlib、Pillow、jsonschema和PyYAML，测试使用pytest。静态求解可选依赖在`stability` extra中固定NumPy/SciPy版本，运行还冻结算法和依赖身份；不要未经任务授权安装或升级现有环境。

以下命令均从仓库根目录执行。先检查解释器与工作区：

```bash
git status --short
git log -5 --oneline
python3 --version
```

在已授权构造验证、现有依赖可用时，可运行A1相关测试；它使用冻结构造候选和监测stub，禁止真实模型、凭证加载及求解派发：

```bash
PYTHONPATH=semantic_pallet_planner/src python3 -m pytest -q \
  semantic_pallet_planner/tests/unit/test_packaging_jev_forks.py
```

通用形式是`PYTHONPATH=semantic_pallet_planner/src python3 -m pytest -q <相关测试文件>`。测试分布于`semantic_pallet_planner/tests/`和`semantic_pallet_planner/src/semantic_pallet_planner/jev_select/tests/`；先读测试与fixture，不能假定所有测试都只做文件校验或不调用求解器。文档任务只检查路径、链接和一致性，无需运行上述行为测试。

真实运行应使用所选阶段专用入口与冻结计划；根通用CLI、`jev_select/__main__.py`及子模块中的命令覆盖不同历史协议，不存在可以无条件代表当前研究的“默认整单运行”命令。凭证读取、模型调用、真实订单、历史回放或求解实验须有对应任务授权；保存证据检查也不能借用会重建候选或重算监测的旧replay入口。

## 7. 进一步导航

- [文档总导航](docs/README.md)：全部研究资料、规范、报告与运行手册。
- [Jev方案索引](docs/02_阶段实施方案/Jev/README.md)与[Jev验收索引](docs/03_阶段产出分析/Jev/README.md)：当前开发入口。
- [规划器历史说明](semantic_pallet_planner/README.md)与[Jev早期说明](semantic_pallet_planner/src/semantic_pallet_planner/jev_select/README.md)：早期命令和协议背景；其中日期与状态属于对应历史阶段，使用前对照当前报告。
- [精确位置监测修复验收](docs/03_阶段产出分析/Jev/Jev_JN4精确位置稳定性修复与29项补充实验验收_20261106.md)：v3/v12与旧v2的区别及执行范围。
- [O3/O4历史技术与结果](docs/03_阶段产出分析/O4/O4D_V2真实冒烟与固定题结果分析_20261025.md)、[旧代码数据速览](docs/00_总览与指导/semantic_pallet_planner代码数据与评测现状速览.md)：保留旧路线证据，不将其“最新/待执行”措辞作为当前状态。

维护约定：根README保持框架、关键边界和入口清晰；详细进度、测试数量、实验矩阵与费用留在阶段材料中。旧合同、报告和摘要保留原身份，新增开发不通过重签历史记录消除差异。
