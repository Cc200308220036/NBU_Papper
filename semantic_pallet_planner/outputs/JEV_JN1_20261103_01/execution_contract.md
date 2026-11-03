```Markdown
请以目标模式实施NBU_Papper项目的JN1-A：
协议适配、请求账本与最小真实调用。

依据最新分阶段规范第6.4节完成A01—A07，交付后停止。
本次不实施JN1-B，不运行真实完整订单。

所有路径均相对于NBU_Papper根目录。

一、必读材料与启动核对

读取：
1. AGENTS.md
2. docs/02_阶段实施方案/Jev/Jev新数据完整订单与经验增强分阶段开发规范_20261103.md
   重点：1.1、3.2、第4节、6.2—6.4、第10—13节。
   第6.5节仅用于了解JN1-B交接，不实施。
3. docs/03_阶段产出分析/Jev/Jev_JN0补验收与JN1准入确认_20261103.md
4. semantic_pallet_planner/outputs/JEV_JN0_20261103_02/中的：
   full_order_readiness.json
   handoff.json
   monitor_scope_review.json
   plan/plan.json
   delivery_manifest.json

检查Git状态、相关实现和适用子目录AGENTS.md。
保留已有修改，特别是尚未提交的最新阶段规范及索引。
不重新克隆，不自动commit/push。

区分报告声明、代码实现、归档证据和本次复验。
历史测试通过不能直接写成本次通过。

二、目标与父基线

JN0已完成N01—N04，工程状态为PASS_IN_DECLARED_SCOPE。
补验收8个job：6 EMPTY_POOL、2 UNASSESSABLE，无技术错误；
累计JN0实际启动9次，其额度已经用尽，不重新运行JN0矩阵。

两次不可评价为POSE_HEIGHT_MISMATCH：
原候选允许下方空隙静态位置，
PCT按从上方落箱得到更高落点。
JN1沿用这一保守停止边界，不顺带改造模型。

本目标只验证：
新包装公开状态 → 真实Jev请求 → 响应解析
→ 当前候选标签映射 → 精确动作保存
→ 公共选后监测 → 提交或合法停单。

不能只验证HTTP200，不能用一次调用宣称完整JN1完成。

三、开发范围与接口

源码目录：
semantic_pallet_planner/src/semantic_pallet_planner/jev_select/

重点审计：
packaging_protocol.py
packaging_experiment.py
packaging_runtime.py
packaging_metrics.py
selector.py
context.py
episode.py
ledger.py
contracts.py
cli.py
现有transport、配置、Schema和相关测试。

1. 新协议与方法注册

新增统一远程协议适配和selector工厂依赖注入。
新方法暂用jev_no_memory，在注册时冻结：
origin、真实model及config/context/selection/metrics版本。

逐项说明新执行/计划/运行版本是否需要变化，
不强行所有模块升级，不只删除packaging拒绝语句。
旧本地v1/v5继续按原合同工作，
保留对未注册方法和协议扩展的拒绝保护。

保留本地方法进入同一新协议的能力，供JN1-B对照使用，
但本阶段不执行整单对照。

复用现有订单、候选、监测、原物理提交及恢复机制，
不复制订单引擎。

2. 显式依赖注入

显式传入transport和请求账本，
分离：
凭证加载、请求编码、单次发送、原始响应解析、
标签映射、监测与提交。

校验job_id、decision_id、state、mapping和body身份。
交付可注入的远程selector工厂和集中版本路由。
接口名称和Schema以实际实现为准，区分拟议与已实现。

3. 无经验公开输入

复用包装属性上下文，提供当前公开：
容器、已放箱、缓冲箱、尺寸、实际质量、
stackable、包装承载、剩余承载、
候选几何与原面积载荷信息。

memories必须为空。

禁止输入：
私有完整task、未来箱体、来源答案、布局见证、
参考动作、PCT标签、证书、反力和稳定性预评。

输出为当前Cxx标签，映射到保存的candidate_id和精确动作，
不生成AST，不编造模型解释。

四、官方API与凭证授权

开发端提供：
typesafe_api_key.md
deepseek_api.md

本次授权安全读取真实Jev所需凭证，
用于本目标真实决策请求。
先核实文件名及已有配置，不打印内容定位密钥。

优先使用现有凭证加载方式。
不得将密钥、鉴权头或凭证内容写入终端输出、
请求产物、配置快照、源码快照、日志或报告。
配置只保存凭证引用方式。

本阶段不调用DeepSeek，不提炼经验，
无需要不读取deepseek_api.md。

实际发送前查阅服务官方文档，核实：
endpoint、模型标识、鉴权、原生Choice请求、
响应字段、标签/概率语义、usage及错误行为。
保存官方链接、访问日期与脱敏请求样例。

概率仅保留服务端真实字段与原始精度；
排名不可得则明确标记。
不将概率当物理置信度，不添加生成式解释冒充理由。

五、请求账本与恢复

账本区分：
请求意图/未发送、发送中、响应已存、选择已存、
发送结果不明及明确失败阶段。

收到持久化响应后，恢复仅解析或复用，不重新发送。
已有选择不重发，已有监测不覆盖，已有提交不重复执行。
发送不明记UNKNOWN_SEND并停止，不隐式重试。

真实origin、model、实际请求数、可得usage、
请求耗时及费用如实记录。
不能将真实请求标为LOCAL_TEST_DOUBLE_NOT_JEV，
不能将实际请求数硬编码0。
费用不可得记UNKNOWN。
单候选自动执行不调用API。

非法标签、未知标签、异常JSON、超限响应及网络错误须拒绝；
不调用本地方法代选，不换候选补救。

六、本地测试

真实调用前完成：
- 成功响应及精确候选映射；
- 非法/未知标签、异常JSON、超限响应；
- 超时、明确发送失败、发送结果不明；
- 响应已存后的恢复不重发；
- 已存选择/监测/提交不重复执行；
- 单候选真实调用数为0；
- memories为空，未来信息及监测信息不泄漏；
- origin、调用数、usage及错误阶段账目；
- 新版本路由与旧本地协议保护；
- 必要包装、监测和恢复回归。

本地transport替身和构造任务必须明确标记，
不能替代真实API证据。
不为增加测试数量重跑全部历史实验。

七、限定真实实验

本阶段累计最多发送1次真实Jev决策请求。
先检查是否已有本阶段请求记录；
换窗口或修复代码不重置额度。

不额外发送连通性测试、探测请求或自动重试。

在一个已暴露开发订单中，
按事先固定规则定位至少2候选的状态，
建议选择最早CHOICE_REQUIRED。
不得依据PCT预评、模型结果或历史成功率挑状态。

请求前冻结：
父收据摘要、任务与来源、
状态/候选/映射摘要、
定位规则、模型、提示、协议、源码及监测身份、
一次调用上限和停止条件。

到达该状态所需的本地前缀独立标记，
不能称Jev前缀，不重放旧请求。
不读取私有未来数据影响选择。

实际请求一次，保存脱敏请求、原始响应、选择及映射；
随后必须执行公共选后监测：
- STABLE：原commit_physical复核并提交一次；
- UNSTABLE：不放失败箱、不移出缓冲、不增加装入量，
  记PREDICTED_STATIC_INSTABILITY并停止；
- UNASSESSABLE/ERROR：独立停单，不当预测失稳。

该决策闭环后立即停止，不继续第二次模型决策。
请求失败或发送不明时保存失败，不换状态、不自动再发。

POSE_HEIGHT_MISMATCH等合法范围停单可支持接口范围内验收，
但必须保留未提交证据及限制；
未实际发生的真实STABLE提交不能声称已经验证。

八、A01—A07验收

A01：
JN0父身份和准入范围已核对；
新远程协议注册完整，旧v1/v5保护保留。

A02：
官方Choice合同与请求样例可查；
公开包装属性完整、memories为空，无未来或监测泄漏。

A03：
成功响应精确映射到保存候选动作；
非法、未知标签和异常响应拒绝，不代选。

A04：
账本区分未发送、已响应、发送不明；
恢复不重发已有结果，单候选调用为0。

A05：
本地成功、错误、恢复合同及必要旧回归通过；
鉴权内容不进入产物。

A06：
最多1次真实多候选请求，
响应、选择、监测及提交或合法停单证据完整。
HTTP成功不代替后续执行校验。

A07：
交付jev_api_readiness.json、
源码/环境身份、命令、逐项验收与handoff。
真实调用失败则PARTIAL，JN1-B不准入。

九、交付与停止

输出到全新目录：
semantic_pallet_planner/outputs/JEV_JN1_<实施日期>_<新序号>/

交付：
- 官方API合同核对；
- 新协议、Schema、方法注册及工厂接口；
- 本地测试结果；
- 真实冒烟预注册和请求账本；
- 标准化DecisionRecord；
- 真实响应、精确选择、监测与提交/终止记录；
- 保存记录与恢复校验；
- engineering_acceptance.json；
- jev_api_readiness.json；
- delivery_manifest.json；
- handoff.json。

DecisionRecord绑定当前候选池、标签映射、选中candidate_id、
精确动作、请求/响应摘要、监测与执行结果，
为JN1-B提供稳定接口。

handoff包含：
stage、status、parent_receipt_digest、
data/source/config/algorithm identities、
实际接口与Schema、任务/调用账本、逐项验收、
限制及JN1-B准入或缺口。

新增验收报告到：
docs/03_阶段产出分析/Jev/
更新相关索引，保留已有用户修改。

N05—N07由JN1-A和JN1-B共同支撑。
本次只报告A01—A07及对应覆盖，
明确JN1-B完整订单未运行、完整JN1尚未完成。

不改候选器、数据、监测算法或容差；
不预过滤、不重排、不泄漏监测结果、不失稳改选；
不做经验、分叉、未见测试或历史全量回放；
不启动子代理，不自动commit/push。

自主完成已授权范围内的代码、必要测试和限定真实实验。
完成JN1-A交付后停止，不自动进入JN1-B。
```