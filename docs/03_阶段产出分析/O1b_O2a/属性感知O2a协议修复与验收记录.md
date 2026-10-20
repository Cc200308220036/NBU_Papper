# O2a 协议修复与验收记录

> 2026-10-08。依据本机 `EXP_OPT_V3_PROTOCOL_PILOT_20261008_01`、`_02` 的冻结输入、原始响应和核验报告。**自动工程检查与真实同题调用已完成；人工双人复核仍待签字，因此 O2a 全部验收尚未完成。** 本轮数据是从原 train 来源预留的开发验证子集，不是原 validation，更不是未见 test。

## 为什么要修

V2 `_04` 的 Flash Direct-Text 共60次请求：51次选候选、1次 abstain、8次协议无效，首答合法率86.67%。对24道有业务可行候选的硬规则题，17道成功、4道有效选择但违反业务硬约束、3道协议无效。8次协议错误中6次输出多余的`type`字段，2次JSON语法错误。旧题不重跑、不覆盖；本轮将全部60题自动归因，并把8条协议错误与4条有效硬误选放进[人工双人复核队列](../../../semantic_pallet_planner/outputs/EXP_OPT_V3_PROTOCOL_PILOT_20261008_02/audit/reviewer_signoff_template.csv)。其中3条协议错误同时发生在有可行候选的硬规则题。[独立程序交叉核验](../../../semantic_pallet_planner/outputs/EXP_OPT_V3_PROTOCOL_PILOT_20261008_02/checks/old_critical_crosscheck.json)对12条逐一从公开指令重解析规则、重算候选关系与可行见证，并重解析原始响应，结果12/12通过；这不是人工签认。

新增协议保留同一公开JSON、真值状态、buffer_size=1、原物理生成器与Top-K≤16。首答仍必须恰好7字段，三项绑定值一致，动作只允许给定C编号或abstain；最多一次修复。修复请求只附同一公开请求和固定错误代码，**不回传不可信的模型原文**。旧 Prompt 和新 Prompt 同题同候选，各调用一次首答；修复额外请求单独计数。V2代码与旧实验数据没有修改。

## 两次冻结开发对照

`_01` 在第一批10个来源订单、20道双政策题上运行。旧Prompt首答19/20合法，新Prompt首答18/20，后者修复两次后20/20。复盘表明两次新Prompt首答错误只是`reason`为205/163字，超过新协议人为设置的160字限制；JSON、绑定及候选编号本身正确。该限制比V2原协议更严且无安全必要，因此**没有改写 `_01`**，另建 `_02` 将上限恢复为V2的3000字。

`_02` 选用另一批10个来源订单、20道双政策题，与 `_01`、V2 `_04` 及所有 test 来源订单均无重合。两版题目都从原 train 来源预先抽出并冻结，不能宣传为原 validation 或独立论文测试。

| `_02` 方法 | 首答合法 | 修复后合法 | API调用 | 适用硬约束满足 | 全尝试属性成功 | 物理违规 |
|---|---:|---:|---:|---:|---:|---:|
| 旧Prompt | 18/20（90%） | 18/20 | 20 | 5/8 | 8/12 | 0 |
| 新Prompt（O2a第二版） | **20/20（100%）** | 20/20 | 20，修复0 | 6/8 | 10/12 | 0 |
| 公开Parser | 不适用 | 不适用 | 0 | 6/8 | 10/12 | 0 |

`_02` 新Prompt的**观测**首答合法率达到≥98%门槛，但样本只有20题，不能据此保证未来请求的真实合法率≥98%。它在业务硬约束上达到当前候选内6/8的上限，然而有两道全枚举无业务可行候选题（`V2_PILOT_119_0/1`）仍选择了候选，没有正确 abstain；因此协议改进不等于无解处理或语言理解问题已解决。下一阶段必须加入公开规则解析后的业务屏障，并分别报告模型提议与实际提交。旧Prompt较新Prompt少一次硬规则成功，同时其两次协议无效也计入全尝试失败；这批开发题不能作为新test上模型优势证据。

原始 token：`_01` 两个远程方法合计输入354,756、输出8,853，含2次修复；`_02` 合计输入285,860、输出8,553，修复0次。`_02` 新Prompt单独输入142,500、输出4,319 token，p50/p95时延约1.83/4.55秒。API响应未保留缓存命中token拆分或账单，**实际费用仍为null**。按[DeepSeek官方价格](https://api-docs.deepseek.com/quick_start/pricing/)计算的全缓存低峰至全未缓存高峰费用情景，分别为 `_01` 约0.0064–0.1171美元、`_02` 约0.0060–0.0960美元；仅作上下界情景，绝不当作已扣费金额。[`_01`费用情景](../../../semantic_pallet_planner/outputs/EXP_OPT_V3_PROTOCOL_PILOT_20261008_01/checks/price_scenario.json)、[`_02`费用情景](../../../semantic_pallet_planner/outputs/EXP_OPT_V3_PROTOCOL_PILOT_20261008_02/checks/price_scenario.json)。

## 验收逐项状态

| O2a验收项 | 状态与证据 |
|---|---|
| 新目录、版本化Prompt、原始/修复响应、token及费用状态 | **PASS**。两版输出各有manifest、代码快照、逐题输入/响应/错误/成本；实际费用诚实标为未知。 |
| V1、V2原始产物不变 | **PASS**。V1 5059文件、V2 `_04` 612文件的目录哈希在实验前后相同；详见[`_02`完整性报告](../../../semantic_pallet_planner/outputs/EXP_OPT_V3_PROTOCOL_PILOT_20261008_02/checks/historical_integrity.json)。 |
| 严格协议、至多一次修复、分开首答/最终合法率 | **PASS**。`_01`首答18/20、最终20/20，修复2次；`_02`首答20/20、修复0次。首答低于98%的`_01`未被最终合法率掩盖。 |
| 旧60题自动分类与12条关键错因 | **自动审计及独立交叉核验PASS，人工签认PENDING**。12/12关键题的公开规则、候选关系、原始响应与可行见证复核一致；双人独立核对不能由模型自述或自动程序冒充。 |
| 新来源同题对照、Schema/泄漏/物理/独立回放 | **PASS**。`_02`10来源、20题、60行方法记录，40次远程原始响应核验通过，物理违规0；详见[独立核验](../../../semantic_pallet_planner/outputs/EXP_OPT_V3_PROTOCOL_PILOT_20261008_02/checks/independent_verification.json)与[验收状态](../../../semantic_pallet_planner/outputs/EXP_OPT_V3_PROTOCOL_PILOT_20261008_02/acceptance_report.json)。 |
| O2a整体完成 | **PENDING**。两位人工复核者尚未按模板独立签认；真实账单金额也未获得，因此费用只报告官方价格情景与未知实际值。 |

用户当前无法安排两名复核者，因此这项保持待办；不以自动核验替代两人签认，也不将 O2a 标为全项通过。复核者日后须按[复核说明](../../../semantic_pallet_planner/outputs/EXP_OPT_V3_PROTOCOL_PILOT_20261008_02/audit/review_instructions.md)独立填写签认模板，不能复用同一人的两份签名。若意见冲突，先记录争议并由研究负责人仲裁。收到签认后仅更新独立验收记录，不修改旧实验原始响应。

本轮新增代码为 `vlm/protocol_o2a.py`、`runners/protocol_o2a.py` 、独立核验器 `runners/protocol_o2a_verify.py` 及旧题交叉核验器 `runners/protocol_o2a_critical.py`；相关单元与集成测试位于 `tests/unit/test_protocol_o2a.py`、`tests/integration/test_protocol_o2a_integration.py`。运行 `PYTHONPATH=semantic_pallet_planner/src python -m pytest semantic_pallet_planner/tests -q`，当前完整测试结果为103 passed。模型API密钥只通过运行进程的无回显标准输入设置；新输出中未发现密钥形态字符串。
