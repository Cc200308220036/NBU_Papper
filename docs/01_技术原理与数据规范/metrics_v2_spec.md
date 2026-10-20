# 属性感知 V2/pilot 指标与冻结协议

版本`attribute_v2_pilot_1`，2026-09-28。本规范是开发期协议，不是新test的预注册结果。V1原始utility及文件保持不变。

## 数据、权限与范围

- 使用V1 validation全部30状态，按ID固定顺序，不因模型表现筛选；每状态两条政策，共60题。
- 状态不是来源订单：主CI按`source_order_key`聚类；30状态CI仅补充，不改ID制造独立性。
- 真值位姿、buffer_size=1、冻结ExtremePointGenerator/diverse_v1、Top-K=16；全枚举只用于覆盖审计。
- 所有非特权方法获得同一公开状态、指令、属性、候选及公共关系；真实候选ID、映射、隐藏AST、Oracle分数、全枚举、未来箱体不进入请求。
- policy_digest=SHA256({grammar版本,instruction_text})；state_hash绑定物理状态。无响应缓存、每题一次、无自动修复/重试。非法/错误不改成几何成功。
- 非特权方法：Geometry、固定属性、公开Parser、Flash Direct-Text；特权参考：真值规则和Candidate Oracle，均非全局episode上界。

## 规则与公开语法

物理检查仍采用原独立geometry_oracle，包括支撑≥0.70与物理承载上限。业务限载独立为1/3kg，与`top_load_limit_kg_synthetic`分开。

AST版本`pallet_policy_v2_pilot`：fragile_load_limit指定所有易碎箱累计载荷上限；forbidden_contact指定两类箱体不得直接面接触；heavy_low/heavy_center最多两级不重复软优先级。物理合法→硬可行→第一软优先级→第二软优先级→几何分→显示编号。

完整公开Parser语法：以分号顺序连接零或多条硬规则、一条阶段分隔、一至两条软优先级；允许空白/英文分号/末尾句号。

```text
易碎箱累计承载不得超过<N> kg
<对象>与<对象>禁止直接面接触
在满足硬约束后                   # 有硬约束
在物理合法范围内                 # 无硬约束
第一优先级：重箱尽量放低          # 或重箱尽量靠中心
第二优先级：重箱尽量靠中心        # 或重箱尽量放低
```

对象支持易碎箱、重箱、中等重量箱、轻箱、类别[ASCII类别码]；N为0～1000非负小数。未消费文本、未知谓词、重复优先级拒绝。公开Parser完整支持这些语法，不以本轮受限语法结果主张自由语言泛化。

## 独立重建

评价器不导入生成器或其result_state/load_increments。忽略输入旧载荷/支撑值，从位姿计算支撑重叠面积，支撑比例=面积/总接触面积，自高到低传播(自身质量+累计承载)×比例，包含间接下层载荷。

直接面接触：一轴面坐标差≤1e-6mm，另两轴交集均>1e-6mm；边/角接触不计。每条规则每无序箱体对一个实例。业务数值容差1e-6kg、语义等价容差1e-6，仅处理数值误差。

## 属性原始量与before/after/delta

|字段|单位与定义|适用性|
|---|---|---|
|fragile_load_by_item_kg|每易碎箱累计承载kg|无目标空映射；不是损伤概率|
|fragile_added_load_kg|所有已有易碎箱本步载荷增量之和kg|无已有目标null，有目标无新增0；新放箱不作已有箱|
|fragile_load_ratio_max|max(载荷/物理上限)，无单位|只取物理上限>0的易碎箱；无可计算目标null；不是业务限载比|
|heavy_mass_weighted_z_mm|Σ质量×底面高度/Σ重箱质量，mm|无重箱null；新增重箱改变集合，delta不是旧箱移动|
|heavy_center_distance_mm|Σ质量×sqrt(x²+y²)/Σ重箱质量，mm|托盘中心XY=0；不是整垛质心|
|contact_pairs|全属性直接接触无序箱体对|公共事实不含任务禁止标记|
|new_contact_pairs|after对集合减before集合|尚未应用隐藏规则|
|geometry_score|原冻结compactness/height/stability/balance加权分|越大越好；拒绝/未提交null|

公共关系保存before/after/delta。标量delta仅在两边都有适用值时定义，否则null；每箱增量仅针对已有目标。语义属性与物理上限标为synthetic/derived，不称为实测保护效果。

## 业务指标、分母与N/A

首版post采用**放置后全状态**定义，含原有违规，新增实例另外统计。该口径不同于方案中仅相关对象的提议，必须以指标版本区分。

|字段|定义|分母/N/A|
|---|---|---|
|hard_applicable|有易碎限载目标或至少一个类别关系对象对|无目标false，满足率N/A|
|business_hard_satisfied|已选择且post违规0|所有适用硬规则题；API错误/非法/abstain记false；未运行不是研究结果|
|all_attempt_success|提交且业务违规0|有任一适用硬/软目标题；纯软最佳性另报|
|conditional_hard_satisfaction|Top-K有业务可行项时正确选择可行项|适用硬且候选有解；无解N/A，真实系统错误false|
|new_business_violation_count|after规则实例集合减before集合大小|限载每规则每箱一个；接触每规则每对一个；abstain/失败null不冒充0|
|worsened_existing_violation_count|旧限载违规实例的超限程度增加的数量|旧违规被继续加压不算新实例，但单列恶化，并保留每实例before/after超限kg|
|post_business_violation_count|after全部规则实例数|含已有违规，不称新增|
|avoidable_new_violation|存在新增违规0的候选却选择了新增违规项|有适用硬规则且至少一候选新增0；未提交为N/A，系统失败率另报|
|oracle_equivalent_hit|命中业务可行且词典序软目标最优等价集合|有可行候选且软目标适用；无解/无目标N/A，实际调用失败false|
|comparison_success|提交、硬可行并命中全部适用软目标最优等价集合|至少一个目标适用；无目标N/A，实际失败false|
|priority_1_quality|low=1-z/H，center=1-d/托盘半对角线，截断[0,1]|无重箱或未提交null；不用test尺度|
|priority_regret|分级最优质量减所选质量|先硬可行；后级仅前级regret≤1e-6才适用，防止抵消|
|policy_pair_success_rate|同状态两指令均comparison_success=true|两题都有目标的完整状态对；不要求ID不同；blocked不进研究均值|
|physical_violations|独立物理检查返回错误数|未提交null；另报提交数；无动作不称安全成功|

APSR在此pilot为全部适用硬阈值满足率，因为纯软偏好未阈值化；不是Oracle正确率。全部计划60、已运行、适用、失败、N/A分开报告。远程未运行是阻碍，不伪作真实API失败；真实API失败计入业务失败分母。

## 覆盖诊断

业务Top-K覆盖分母为硬规则适用题；全枚举也报告可行数量。`topk_missing_feasible`表示全枚举有解而Top-K无解；`enumeration_no_feasible`只表示当前枚举空间无解。`no_semantic_opportunity`表示候选违规实例与适用软质量完全相同，`semantic_opportunity`表示有差异。主track以覆盖缺失优先，另保留是否存在语义差异，不因模型表现筛题。

## API、费用和统计

API合法率=严格字段/编号/request_id+state_hash+policy_digest校验通过题数÷真实尝试题数。合法abstain算协议合法，业务成功另判。无自动修复/回退，每题最多一次。保存供应商与传输失败、token及全部真实时延p50/p95。token和费用未知=null，不汇总成免费。实际费用需要账单；估算需要核验费率与缓存细分。

调用前预算60次、输出上限512token/次、输入字符粗估范围（非真实分词器结果）、费用null。冻结建议组数公式为ceil((1.96+0.84)²×订单聚类差值SD²/0.05²)，只是正态近似预算，不是精确二元配对功效。没有Flash数据时SD及估计组数=null。

配对差先按来源订单求均值，再固定种子5000次bootstrap；补充30物理状态聚类。不同任务分母分别报告，N/A不填1。单轮一次不能估模型重复方差，60/100/150独立订单×2政策×1/3重复仅预算情景；补独立开发订单并核验费用后，在任何新test之前预注册。工程检查通过不等于研究得到支持。

## 回放跨Python版本兼容（2026-09-29）

Python3.13生成与Python3.11回放的末位浮点差异最大约1.14e-13。复算数值使用绝对容差1e-9，无相对容差，仅适用于相同类型的有限float；整数、布尔、字符串、ID/哈希、N/A、列表顺序、字段集合及候选最优索引仍严格一致。这不是放宽业务阈值、物理容差或语义等价容差。原始数据与原记录不改写，兼容修复须通过--fork-from创建新目录并保留父manifest、失败报告和来源哈希。
