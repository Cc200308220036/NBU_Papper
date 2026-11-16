# GP0 数值、配置、输入及运行合同草案

日期：2026-11-16（Asia/Shanghai）。上位设计：geometry_candidate_upgrade_design_v1。
本文件在本次交付范围冻结设计细节，交独立质检；不修改上位历史方案，不代表生产注册或算法实现。所有拟议版本须在实际接入前再次查重。GP0仅做静态和保存事实核对。

## 设计名称与集中接入

旧后端e2_original_v1，拟议新后端ems_surface_hybrid_v1；拟议运行jev_packaging_geometry_compare_v14；config/candidate_bundle/decision_context/selection_result/checkpoint分别使用独立v14合同。比较计划、执行包装和结果使用geometry_compare_plan_v1 / geometry_compare_execution_v1 / geometry_compare_run_v1。空间、审计、比较分别为geometry_space_index_v1 / geometry_generation_audit_v1 / geometry_comparison_v1。

静态扫描生产包py/json没有这些后端/运行v14名称冲突（详baseline_inventory）。这些是设计冻结名称，不在packaging_versions、contracts或运行路由注册。本包JSON是配置和字段合同草案，禁止直接作为现有生产配置运行。

未来集中位置：packaging_versions集中登记；contracts显式Schema允许列表和版本路由；config增加独立generator_config_for式解析，保留generator_config()旧入口；candidate_backends统一返回结构；packaging_geometry_protocol准备/校验新plan、execution、run并接公共episode。context、selector、monitor、checkpoint、metrics同时识别新版本；不能只把v14加进is_packaging。所有未知组合拒绝，不能从未知后缀自动推断支持。

## 坐标、数值、动作与排序

长度mm、质量kg；容器水平中心为原点，x向右、y向后、z向上。空间顺序固定[xmin,ymin,zmin,xmax,ymax,zmax]，区别于oracle.bounds的[xmin,xmax,ymin,ymax,zmin,zmax]，必须具名转换。内部角点(x0,y0,z0)与发布底面中心pose的转换为(x0+l/2,y0+w/2,z0)，反向为(x-l/2,y-w/2,z)。yaw不再二次交换已定向尺寸。

新增几何内部从原JSON数字词素解析十进制并转精确有理数，比较/切分/包含/排序不用epsilon。禁止从float反推丢失词素；GP0输入快照须与原保存字节以Decimal解析比较，字段来源仍指原文件。发布pose各轴按0.001 mm、HALF_EVEN一次规范化，-0归0；尺寸保持源尺寸，不量化尺寸。计算事实、拒绝原因及统计使用同一规范化动作身份；不以1 mm容差合并动作。

与既有物理函数边界仍为原int/float接口：仅在调用边界转换binary64，有限值及正尺寸检查；不改原检查容差。不得用浮点转换吸附接触。发布后的float经原检查输出再次round3所得pose必须与拟发布pose一致；不一致为POSE_REPRESENTATION_REJECTED。源状态的接触/载荷重建沿原domain.restore_placed语义复用，不能写另一套物理规则；GP0不调用此函数。内部精确几何和旧物理接口转换风险留GP1—GP2构造验证，不能宣称已验证可行。

语义动作键固定为(item_id, oriented_l, oriented_w, oriented_h, yaw, x_center, y_center, z_base)。数值按数学值比较，文本序列化为最短有限十进制、去尾零和负零；复合键按上述顺序升序，字符串ID按Unicode码点。四角/中心的重复提案合并，方箱0/90正式动作仍区分，几何等价统计另列。新candidate_id建议哈希backend_version、observation_digest和语义动作键；ID及Cxx均不得跨后端匹配。

空间按六边界数值字典序排序；已放箱仅在几何私有副本按边界、item_id排序，不修改提交顺序；space_id由规范边界决定，来源不改变几何ID。逐箱以arrival_index排序，逐yaw为0、90，逐space按边界，提案顺序为左前、右前、左后、右后、中心；最终每箱输出按动作键排序，再按缓冲到货顺序联合。

## 提案、规范化与host

三维六向slab、去重/包含消除及表面补充遵循上位设计5.2—5.3；允许空间相互重叠，不能求和当自由体积；上表面不得删除下方空腔。空间不是全局最大空闲体的完备枚举，也不是路径可达性证明。

为消除“表面角点”实现歧义，草案固定：在事件顶点逐相邻容器内种子单元/向内象限检查，seed_z为该单元上表面。跨顶点相邻x边和y边的两个单元高度均与seed_z不同时才是该象限角点；容器外邻居视为墙、视为不同；只单轴高度变化的直线内部事件点不算角点。四象限分别检查，重复(seed位置/象限/高度)去重；不额外stair变换。按x后y、y后x两个轴序，每轴负再正扩一完整事件条带，每次新增单元均<=seed_z才扩；失败停该方向，完成轴序不循环。此为本项目原高度图角点的明确判定约定，尚未实现或验证；质检若认为与主方案意图不符，应先退回合同修订，不在GP1悄改算法。

每箱0/90；每个可容纳host在zmin提出底面四角和一个中心，最多5次，zmin只能为保存地面或箱顶精确高度；无下落、抬升、偏移、50/100间隙或未来箱探测。候选上界每箱16、联合48，缓冲容量3不变。

检查顺序：原精确提案evaluate_pose通过 → 规范化发布pose → host重新包含检查 → 发布pose转回角点再次evaluate_pose → 对该次生成的发布事实调用独立check_candidate。规范化不得让原来物理拒绝的点变为可接受；原始拒绝保留原原因。改变接触高度、失去全部host、转换不能保持发布pose或规范化后原检查拒绝记POSE_REPRESENTATION_REJECTED。发布evaluate_pose通过而oracle失败记PHYSICAL_CHECK_DISAGREEMENT并使整个后端ERROR；不能悄删动作继续。

动作按发布语义键去重，来源集合和全部有效host引用取并集。同一规范化动作的不同原提案，只有通过原提案与发布复核者贡献来源；被拒提案不污染host。host只有完整包含发布AABB才保留；代表host为最小体积，再按边界字典序，其他host全部审计；不称最大可用空间。来源仅EMS_STYLE_3D和SURFACE_CORNER。兼容ems字段只作旧式标签，不冒充真实host边界。

## 统计与压缩

raw_point_attempts：逐箱按来源空间/yaw/点的每次实例化尝试，含重复中心/角点、重复来源；先检查计数再计算或入队，尺寸/高度不适配空间单独计space_skips，不伪计为已实例化点。unique_actions：所有可表示发布动作按语义键去重后的数量（含随后物理拒绝）；unrepresentable_proposals单列。raw_valid_candidates：通过原提案检查、发布检查及oracle的唯一动作池。final_candidates：多样性压缩后的唯一池。physical_candidates在bundle中仍仅指final池；selectable筛选后必须完全相等，不把原始有效池塞入正式请求。

唯一动作各阶段计数与逐提案拒绝计数分开；同一动作多来源不重复计raw_valid。因为原提案检查发生在合并路径上，统计保留proposal_rejections与unique_action_outcomes两张表，不要求attempts减rejects等于unique。各项必含分母、所用定义版本；旧E2 attempts/public_enriched_physical_count按旧口径，不能直接与新attempt相减。

压缩冻结为joint-group规则：先为每个非空(yaw,floor/upper)选几何分数最高者，最多4；同分按动作键。每动作的覆盖键集合为{(yaw,精确z,水平四象限,排序支撑ID集合,source_type)}，多来源提供多个完整联合键；不是把五种维度拆成五个独立标签。地面支撑集合为GROUND，坐标0归非负象限。此选择明确采用主方案“分组键”的联合元组解释。其后贪心最大化未覆盖联合键数，同分按原几何分数降序、动作键升序；全覆盖后按同样分数/动作键补齐16。保存入选顺序和最终规范输出顺序。不得PCT预评、按监测排序或附加旧收益；除首步外不保证所有层/支撑均被保留。

## 冻结预算与原子失败

配置原值：活动空间4096；空间包含比较2000000；表面事件单元16384；表面扩展单元检查2000000；每箱去重前点尝试32768。未调整，未测性能或验证充分性。

- 活动空间为当前3D集合、切分/清理待处理队列、表面待处理和保留空间记录的同时存活峰值总数；缓存同一记录的ID引用不重复计，但复制记录计；旧空间尚未释放时新slab也计。先查预算再分配；不可只限制最终去重池。
- 每一次有向空间包含谓词计1，含提前退出、不成立、所有来源/清理分支；几何相交谓词另审计、不冒称包含比较。相同体先去重，避免互删。
- 表面事件单元为(nx-1)*(ny-1)，分配前检查；各象限/两个轴序/正负方向每次访问待扩区域单元计1，含失败和重复访问；相同计算如实际复用则记缓存命中，不能假造未做检查。
- 所有来源空间合并到上述活动空间上限；每箱raw attempts累计两来源/两yaw/全部点分支，去重不能重置预算。3D/表面空间、包含及扩展预算按单状态，多个箱共享，不得逐箱重置单状态预算。GP1不引入跨步空间缓存。
- 刚好等于上限允许；下一次操作会超限前停止。墙钟仅观察，无墙钟内容截断。预算只约束列明操作，不声称覆盖所有Python工作、解析和独立物理检查耗时。

OK_EMPTY仅完整枚举后无有效动作；生成ERROR包括非法/非有限输入、非法尺寸/ID/原状态矛盾、数值错误、PHYSICAL_CHECK_DISAGREEMENT及GEOMETRY_BUDGET_EXCEEDED。任一箱失败使整个新后端ERROR；已形成的部分池撤销，仅保留错误审计，不能提交/展示部分候选。未知backend也ERROR。禁止返回空池伪装STOP_NO_PHYSICAL_CANDIDATE，禁止静默回退E2。

## F0、选择、监测、提交和身份

F0沿当前public_facts/build_context的QUESTION/OBJECTIVE、匿名箱体、候选pose/尺寸、geometry_score、支撑率/余量/对象/分载、放后高度/体积利用率、载荷变化字段；memories=[]。backend、来源、host、压缩理由、旧成绩、PCT标签/反力不入请求。bundle审计侧车不自动投影。F1后置，GP0不实现。

正式新旧比较都在同一个新运行协议，不拿历史旧job对新job归因。保持display_order_seed=20261102；同状态两后端使用相同request_id/state_hash，不把backend/job/candidate_id混入seed；先按(x,y,z,yaw,匿名箱体)排序再现有洗牌。Cxx可以变化；按动作匹配。max_request_bytes=96000，超限技术错误，不能删候选/裁字段。本阶段不构造新请求或证明请求大小。

后续运行：保存选择SELECTED → 独立状态副本上只监测已选精确动作 → 保存MONITORED → STABLE时原commit_physical复核提交一次；UNSTABLE为PREDICTED_STATIC_INSTABILITY停单，UNASSESSABLE和ERROR分列；singleton共用入口。现行新路线指定exact_freeze/ exact_adapter.assess_candidate / pct_exact_pose_network_v3；通用freeze历史v2不能误接。开关唯一且关闭记DISABLED，不记STABLE；需要监测的新执行计划应显式启用并冻结，不静默关闭。

已存选择不重发，已存监测不覆盖，已提交不重放。UNKNOWN_SEND保持技术状态停止，无隐式重试。backend/配置/预算/源码/物理/监测/数据/依赖身份变化拒绝恢复，不改旧checkpoint版本、不重签摘要。比较输入仅当前公开状态，不是可执行旧checkpoint。旧冻结运行在源码变化时仍可拒绝；不能为兼容豁免身份。GP0文件位于outputs和docs，未进入experiment.source_manifest范围；GP1新增生产py/json将改变宽范围身份，即使不改旧函数。

## 封闭合同核心字段草案

以下每行列出的字段均必填，顶层additionalProperties=false；nullable/NA也须显式保存。未来生产Schema须对每个嵌套对象分别封闭，不能用任意object接纳未知字段。现阶段是字段合同，不声称完整生产Schema通过验证。旧Schema均不修改。

| 合同 | 必填核心字段（列名为拟议） | 摘要与边界 |
|---|---|---|
| config_v14 | version, candidate_backend, generator_config_digest, geometry_version, numerical_profile, budgets, reducer, buffer_capacity, yaw_degrees, per_item_top_k, joint_top_k, feature_profile, feature_version, prompt_version, display_order_seed, max_request_bytes, selector, memory_mode, stability_monitor, runtime_identity | backend只允许旧/新；16/48、3、0/90、F0固定；config摘要覆盖全部语义配置，不含运行耗时 |
| generator draft | config_snapshot.new_generator_draft全部字段 | 本GP0草案字段封闭；不是可由旧load_config读取的生产配置；authorization固定全0 |
| candidate_bundle_v14 | version, observation_digest, candidate_backend, generator_config_digest, physical_candidates, physical_digest, generation_counts, selectable_pool, selectable_candidates, selectable_digest, policy_digest, experiment_protocol, business_mode, geometry_audit_digest, geometry_audit_ref | physical为TopK，空池合法；<=16/48；候选核心保留旧字段；两池摘要、audit摘要分开；侧车引用不能泄露到F0 |
| geometry_generation_audit_v1 | version, observation_digest, input_digest, backend, config_digest, geometry_version, numerical_profile, spaces, proposal_counts, unique_action_counts, rejections, raw_valid_candidates, final_action_keys, coverage, budget_usage, outcome | space子项必须id/bounds/source_types；action子项必须action_key/sources/host_ids/representative_host；GP4原始池完整导出，其他阶段可用受版本约束的侧车引用；observations耗时在独立文件不入语义摘要 |
| comparison input | version, point_id, decision_id, current_public_state, public_observation, input_scope | 本包inputs实际封闭形状；每个叶子在input_manifest绑定source SHA/pointer；不得新增未来订单、selection、monitor、见证；不等同checkpoint |
| comparison_plan | version, point_ids, input_manifest_digest, backend_config_digests, source_identity, feature_profile, budgets, action_key_version, outcomes, figure_limit, authorization | 本包comparison_plan是GP0计划草案；GP4实际生产plan按此合同重新封闭，不借旧plan派发 |
| geometry_comparison_v1 | version, plan_digest, input_digest, backend_identities, states, denominators, action_intersections, generation_vs_reduction, coverage, observations_ref, errors, figures | 每状态/箱/后端均有状态和分母；方箱等价另列；没有运行不填0指标；耗时独立观察 |
| geometry_compare_execution_v1 | version, plan_digest, job_id, task_digest, config_digest, method, backend, allowed_sends, source_identity, physical_identity, monitor_identity, data_identity | 本地allowed_sends=0；方法只含两个既有本地方法及后续待授权jev_no_memory；GP0不签发执行实例 |
| decision_context_v14 / selection_result_v14 | 现有F0结构全部必填字段及新版本，local_binding包含新runtime_identity；selection绑定local_binding_digest和完整映射 | GP3按当前v13封闭结构独立新增；不携带记忆，不改变模型字段 |
| checkpoint_v14 | version, job_id, method, task_digest, config_digest, state, cursor, decision, events, reason, phase, pending_event, runtime_identity, record_digest | SELECTED/MONITORED/COMMITTED/TERMINATED不变；新独立验证入口，不落到v5，不把历史checkpoint迁移进来 |
| geometry_compare_run_v1 | version, plan_digest, execution_digests, statuses, ledger_refs, checkpoint_refs, summaries, source_identity, stopped, errors | 完整运行/发送分母；GP0不存在可派发实例 |

统一摘要规则：文件身份为原始bytes SHA256；JSON语义为UTF-8、sort_keys、无空白分隔、禁NaN；精确几何数使用规范十进制文本并有独立数值版本，不将原始文件摘要当语义动作键。自身record_digest排除自身字段。运行观测时间、路径位置与环境观察独立保存；源码/依赖身份不能从语义摘要中省略。侧车语义摘要覆盖边界、来源、动作、host、拒绝、覆盖和预算计数；耗时不参与。delivery_manifest排除自身摘要，明确外部docs范围，避免循环。旧源文件摘要与历史清单不重新签署。

## GP0输入核对及边界

input_manifest从源码必需字段出发，逐叶保存原episode文件SHA及JSON pointer；五状态固定，不替换。原prefix/pool/A1输入按清单SHA核对；原pool与同一事件bundle相等，prefix按原export_public字段投影相等；context的request/state/observation/pool绑定一致。只读取before、observation和必要的历史pool/context绑定，不读取未来task来补字段，不用分支收益。

保存supported_load_kg/support_fractions逐值保留，空列表是原保存事实，不新补0；未重新求接触、分载或稳定性。prefix缺支撑边/slot，到原事件公开状态取，不经F-S几何投影。缺字段NOT_COMPARABLE_MISSING_INPUT，摘要/身份冲突ERROR_IDENTITY_CONFLICT，均留五状态分母。GP0只证明可定位和保存关系，不认证历史全部执行、不证明当前重跑输出一致或物理正确。输入已具备不等于GP4已执行。

GP5/GP6未授权、未制定派发实例。完成A00开发端自验后交独立质检并停止；A01—A06全部NOT_RUN。
