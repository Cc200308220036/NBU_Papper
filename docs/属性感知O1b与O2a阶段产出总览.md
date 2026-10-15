# 属性感知 O1b 与 O2a 阶段产出总览

> 更新：2026-10-09。用于快速同步开发状态。O1b 最终离线数据发布为 `EXP_OPT_O1B_LANGUAGE_PILOT_20261009_03`；`_01`、`_02` 是保留的开发迭代。O2a 以 `EXP_OPT_V3_PROTOCOL_PILOT_20261008_02` 为第二版真实调用对照。所有这些数据均为 **pilot/开发证据**，不是新方案的未见 test 结果。

## 目前能确认什么

| 阶段 | 已完成 | 尚未达到的验收 |
|---|---|---|
| O2a 协议修复 | 严格七字段响应、三项请求绑定、最多一次修复；两批同题旧/新 Prompt 真实调用，旧 60 题归因及 12 条关键错例独立程序交叉核验；V1/V2 原始目录哈希不变 | 两名人工复核者尚未签认；实际 API 账单金额未知。第二版 20/20 首答合法只是一批开发题的观测，不证明总体 ≥98% |
| O1b 语言与政策数据 | 新建 30 个独立来源订单的 **train 来源开发验证集**，每组 1 个物理状态，A/B/C 三轨各 2 条政策，共 180 题；冻结候选生成器、Top-K=16、真值状态和 `buffer_size=1`；Schema、泄漏、解析器一致性及独立重算通过 | 原始 `validation` 划分仍只有 10 个来源订单；本轮新增的是与旧 pilot/O2a/test 不重合的派生开发验证集。180 条 AST 尚未获两人独立人工核对；人工维护工时未获得；政策最优动作真正变化只出现在 10/30 个独立来源订单 |

**研究结论：** O1b 未调用远程模型，不能声称 VLM/LLM 取得收益；O2a 只说明协议稳定性在小批开发题上改善。O2a 两道无业务可行候选题仍误提交，后续需要公开解析结果驱动的业务屏障，并将模型提议与实际提交分开统计。

## O1b 代码与数据流

1. [`policy_o1b.py`](../semantic_pallet_planner/src/semantic_pallet_planner/evaluation/policy_o1b.py) 定义受限条件政策：仅检查公开的当前箱 `weight_class == heavy`，再分支到已有 V2 限载、禁止接触和重物低位/靠中心规则。条件不会读取未来箱体或隐藏标注；[政策 Schema](../semantic_pallet_planner/src/semantic_pallet_planner/schemas/policy_o1b.schema.json) 拒绝未发布字段。
2. [`instruction_parser_o1b.py`](../semantic_pallet_planner/src/semantic_pallet_planner/selectors/instruction_parser_o1b.py) 发布并解析三轨语法：A 为 V2 规范表达；B 是相同 AST 的新同义表达；C 用公开的“若当前箱为重箱／否则”选择两条 V2 原语政策。B 对旧 V2 Parser 是新模板，但已进入 **O1b 开发 Parser**，后续不能再把它称为该 Parser 的未见测试。C 没有引入新物理或业务原语。
3. [`attribute_o1b.py`](../semantic_pallet_planner/src/semantic_pallet_planner/runners/attribute_o1b.py) 从原 train 的 50 个来源订单中，按来源键固定取后 30 组；每组先审计 3 个现有状态，以预先写定的阈值/接触/软优先级目录选 1 个较有政策差异的状态。**筛选只依赖物理候选与形式化政策，发生在任何模型调用之前**。同一状态的 6 道题共享状态、Top-K 候选、显示编号和私有真实 ID 映射，仅公开指令与 `policy_digest` 改变。真值 AST、Oracle 评价和真实 ID 映射只保存在私有文件。
4. [`attribute_o1b_verify.py`](../semantic_pallet_planner/src/semantic_pallet_planner/runners/attribute_o1b_verify.py) 在发布后重新校验全部 180 条公开请求的 [Schema](../semantic_pallet_planner/src/semantic_pallet_planner/schemas/o1b_request.schema.json)、禁止泄漏键、来源、状态哈希、政策摘要和候选关系；从公开文本重解析政策并重算每个候选评价与最优集合。

[O1b 发布目录](../semantic_pallet_planner/outputs/EXP_OPT_O1B_LANGUAGE_PILOT_20261009_03/)包含 `manifest.json`、`code_snapshot/`、`data/source_manifest.json`、`data/split_audit.json`、`data/generation_audit.json`、180 个 `data/public_requests/*.json`、私有真值、`metrics/coverage.csv`、`metrics/policy_pairs.csv`、[独立核验](../semantic_pallet_planner/outputs/EXP_OPT_O1B_LANGUAGE_PILOT_20261009_03/checks/independent_verification.json)、[验收记录](../semantic_pallet_planner/outputs/EXP_OPT_O1B_LANGUAGE_PILOT_20261009_03/acceptance_report.json)及[逐项验收矩阵](../semantic_pallet_planner/outputs/EXP_OPT_O1B_LANGUAGE_PILOT_20261009_03/checks/o1b_acceptance_matrix.json)、[人工 AST 复核队列](../semantic_pallet_planner/outputs/EXP_OPT_O1B_LANGUAGE_PILOT_20261009_03/audit/ast_human_review_queue.csv)。原始属性仍是 synthetic，不可写成实测损伤或承载能力。

## O1b 数据与验收核对

| 检查项 | 结果 | 判定 |
|---|---:|---|
| 独立来源订单、跨原 validation/V2/O2a/全部 test 来源重合 | 30 组；重合均为 0 | 自动 PASS；明确是 train 派生开发验证，不改原划分 |
| 原始状态筛查与保留 | 90 个状态审计，按冻结规则保留 30、未选 60；所有来源订单均保留 | PASS；未按模型答题情况筛选 |
| 三轨与政策配对 | 180 题、90 组双政策；A/B 是同一 AST 的语言改写；每组共享状态、候选和编号 | PASS |
| 最优等价集合变化 | 30/90 组政策配对有差异，来自 **10/30 个独立订单**；60 组明确列为控制组 | 数据区分度有限；O2b 应按独立订单报告，不把 30 道机会题当 30 个独立样本 |
| 候选业务覆盖 | 168/180 题 Top-K 有可行解；12/180 题全枚举也无可行解；本版未观察到“全枚举有解但 Top-K 丢失” | PASS；无解题保留，不算模型成功 |
| 旧 V2 无解回归 | 10 题；旧 Flash：8 次选择、1 次 abstain、1 次协议无效；公开 Parser 与特权参考各 10 次 abstain | 已记录旧结果；O1b 未重跑模型 |
| 规则 AST 字段与人工维护代价 | 机器解析与生成真值 180/180 一致；双人签认与人员工时为空值 | **PENDING**；不能将机器一致率或空值解释为人工验收/零成本 |
| 发布后独立核验、原产物保护 | 180/180 请求、90/90 配对轨道核验通过，0 失败；V1、V2、两批 O2a 目录哈希前后相同 | 自动 PASS |

**O1b 状态：自动工程验收通过，人工真值与维护成本验收待完成；研究优势未测试。** 只有 10 个独立来源组产生政策最优动作切换，因而本数据适合作为 O2b 开发和失败归因的起点，不足以单独支持正式语言泛化结论。语言模板、属性、规则目录和状态筛选已被本轮开发查看，未来 test 必须另取来源并冻结新模板族。

## O2a 代码与数据

O2a 的直接选择协议在 [`vlm/protocol_o2a.py`](../semantic_pallet_planner/src/semantic_pallet_planner/vlm/protocol_o2a.py)，真实调用与产物在 [`runners/protocol_o2a.py`](../semantic_pallet_planner/src/semantic_pallet_planner/runners/protocol_o2a.py) 和 [第二版输出目录](../semantic_pallet_planner/outputs/EXP_OPT_V3_PROTOCOL_PILOT_20261008_02/)。独立响应回放与旧错例交叉核验分别由 `protocol_o2a_verify.py`、`protocol_o2a_critical.py` 完成。第二版 20 道开发题上，旧 Prompt 首答合法 18/20，新 Prompt 20/20；新 Prompt 的适用硬约束满足 6/8，与公开 Parser 持平。其结果不支持“直接模型优于充分开发的规则解析器”的结论。详见 [O2a 逐项验收记录](属性感知O2a协议修复与验收记录.md)。

具体复核流程、逐题记录字段和期望的报告格式见[O2a与O1b人工复核操作教程及报告模板](O2a与O1b人工复核操作教程及报告模板.md)。Agent 可以按该教程做独立技术复查，但不能冒充两名人工签认。

## 验证命令与接续工作

```bash
PYTHONPATH=semantic_pallet_planner/src python -m semantic_pallet_planner.runners.attribute_o1b \
  --output semantic_pallet_planner/outputs/EXP_OPT_O1B_LANGUAGE_PILOT_20261009_03
PYTHONPATH=semantic_pallet_planner/src python -m semantic_pallet_planner.runners.attribute_o1b_verify \
  --output semantic_pallet_planner/outputs/EXP_OPT_O1B_LANGUAGE_PILOT_20261009_03
PYTHONPATH=semantic_pallet_planner/src python -m pytest semantic_pallet_planner/tests -q
```

发布脚本拒绝覆盖已有目录；第一条是**新建发布**的复现命令，重跑时必须更换输出目录。实际已执行结果：生成通过、独立核验 180 题且 0 失败、全套测试 **107 passed**、`git diff --check` 通过，源码扫描未发现密钥形态字符串。代码基于 Git HEAD `d38f34c9` 加本轮尚未提交的 O1b 文件；精确源码 SHA 见发布 `manifest.json`。当前产物尚未作为正式测试冻结或提交远程仓库。

接下来应先完成双人 AST 复核与维护工时记录；在不等待人员安排的同时，可开发 O2b 的受限 AST 输出、同权限强 Parser 和业务屏障，先用这 30 组作开发对照。若要主张未见表达或 VLM 增益，须另建独立来源与语言模板的冻结测试集，并基于开发组间方差和真实费用决定样本量。`tray_yaw_stacking_plan.md` 属于机器人执行的另一条工作线，不混入当前属性语义实验。
