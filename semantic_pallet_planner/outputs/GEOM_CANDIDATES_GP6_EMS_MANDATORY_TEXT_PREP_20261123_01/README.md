# EMS＋Jev 强制顺序文本对照：仅准备，未运行

状态：`DRAFT_AWAITING_SEPARATE_RUN_AUTHORIZATION`。本包不含真实执行入口，不创建准入或运行账本，不读取凭证。上一轮真实执行授权不延伸到本轮；启动仍等待用户另行授权。

## 文本

- `mandatory_instruction.txt`：用户本轮英文原文。
- `base_selection_instructions.txt`：归档关闭承载G01的原有基础选择指令。
- `full_selection_instructions_DRAFT.txt`：基础指令＋两个换行＋本轮强制顺序英文；不含上一轮“Build the stack outward…”偏好文字。尚未发送，不能称实际发送记录。
- `prompt_policy.py`：版本 `gp6_mandatory_lexicographic_text_v1`，只接受尚未追加文字的基础请求；深复制并仅替换选择指令字段，保留state、criteria和所有Cxx。遇到已经追加旧文字的请求会报错，不盲目重复追加。无网络或传输器。
- `experiment_spec_DRAFT.json`：新对照草案、保护项、核对口径与NOT_RUN结果；不是正式运行计划或许可。

## 逐步核对口径 v1

`audit_rules_v1.py` 是**事后只读核对器**，不接在线选择、候选发布、监测或提交回调。数学上的分层“保留”仅用于报告合规标签集合，不修改候选池，不重排，不改选，不补发。每一步用原保存context实际发布的criteria标签及display_mapping取得候选，不把未发布的物理候选加入比较；检查候选digest与原选择映射。

坐标沿用container_bottom_center。候选已包含旋转后的 `[L,W,H]`，中心 `(x,y)`，底面z：

1. `z_base_mm` 最小。只比较底面，不比较 `z_base_mm + H`。
2. 仅在规则1并列者中，最小化 `(x - L/2 + pallet_length/2) + (y - W/2 + pallet_width/2)`，即沿最小X、最小Y方向的两个箱底边净距之和。不是中心到角落的距离，也不是平方/欧氏距离。双边接触为0。
3. 仅在规则1、2并列者中，最大化与**决策前已放箱体**的接触面积（mm²）：四个侧面接触矩形并集面积之和＋受支撑底面接触矩形并集面积。同一面取并集，不重复计数。面积使用轴对齐几何交集，不能用支撑率替代。托盘不是“已放箱体”，不计托盘接触；不计候选顶面，口径明确限定为四侧面及受支撑底面。空托盘跳过此规则。

长度比较绝对容差 `1e-6 mm`，面积绝对容差 `1e-6 mm²`，仅为离线核对浮点相等口径，不修改候选器或监测容差。不采用加权打分；更大接触面积不能补偿更高底面或更大角落净距。

提供 `--request-ledger` 时，还会逐步核对保存选择、选择摘要、基础正文摘要、transport摘要、原始响应字节摘要及TypeSafe原始 `answers.next_action.choice`；不相等即拒绝。未提供时标为 `NOT_CHECKED`，不能声称核实了原始响应。

每步保留原发布顺序与全体指标，记录原始Cxx、候选ID、每一层存活Cxx、首个违反规则编号、该层合规Cxx及最终前三条合规Cxx。单候选自动执行明确标为 `AUTOMATIC_SINGLETON_NOT_JEV`，不能当作指令约束模型的证据。缺失/非法原选择单列，空池停单无模型选择，不记为违规。首个实际放置及最终结果还须结合正式运行保存的提交、监测和metrics核对，不能只凭尝试选择称已放置。

### 末级并列边界

用户原文“most useful contiguous free space”没有指定有用性评分、计算高度层或狭缝阈值。本轮不自行引入空闲面积/窄缝/未来可装箱数评分。前三条最终唯一者可以明确判断通过；若原选择通过前三条但仍有多个标签，状态为 `NO_HARD_RULE_VIOLATION_FINAL_TIE_UNASSESSABLE`，不能宣称全部文字规则通过。所有并列者保留，等待必要时人工核对或用户进一步定义。

## 未来真实运行交接（本次未执行）

保持CPU、jev-1.14.0、订单NEW_00100027_controlled_base、包装限载关闭、原到货/缓冲/发布/种子/监测。用户另行授权后，准备新正式计划、独立新账本、新运行目录与单EMS入口；冻结最终文本和核对脚本身份。保存每次实际发出的完整canonical JSON和完整instructions，以及基础正文摘要、线上正文摘要、决策ID和文本策略身份；它们须与账本对齐。不能仅把本包DRAFT文字当作已经发送。

事后调用核对器示例（路径占位，不是启动命令）：

```bash
python3 -I -B audit_rules_v1.py --checkpoint NEW_RUN/jobs/G01/checkpoint.json --metrics NEW_RUN/jobs/G01/metrics.json --request-ledger NEW_LEDGERS/requests.json --output NEW_RUN/offline_rule_audit.json
```

核对器只验证几何规则，输出 `instruction_delivery_verified=false`，**不能独自证明这段文字送达**。真实运行交接必须再逐份核对实际wire正文中的完整新指令、state/criteria未变及账本原选择，不能把基础context中的旧正文当成实际请求。若违反，保留原选择及真实轨迹；不得按核对结果改选。

结果交接须区分：首个提交箱是否靠角；每次Jev原选择违反哪条以及合规Cxx；末级并列不可判；候选为空/技术失败；最终装箱数、固定容器利用率、停单原因、实际发送次数及选后监测。所有新实验结果目前NOT_RUN。

## 本机离线验证

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -I -B -m pytest -q semantic_pallet_planner/outputs/GEOM_CANDIDATES_GP6_EMS_MANDATORY_TEXT_PREP_20261123_01/test_offline_policy.py
```

目标机既有Anaconda python3：11 passed，0.09秒。覆盖底面/顶面区别、优先级不得倒置、接触面积及并集、空托盘跳过、未发布候选排除、浮点并列、原选择/映射篡改、输入不修改和文本替换。初次直接pytest因自动加载ROS插件缺lark而未收集测试；使用隔离模式并禁用第三方插件自动加载后通过，未安装依赖或改CPU环境。

`historical_diagnostic_NOT_NEW_EXPERIMENT.json` 仅把上一轮“偏好靠角”已保存轨迹送入新核对器作CLI烟测，没有重放引擎：其首步C17若按本轮规则衡量，会违反规则2，前三条合规标签是该历史候选池的C08/C11/C12/C13/C20/C26。这不是新文本真实选择，不能填入本轮成绩，也不能将这些标签硬编码进提示词。烟测包含4次历史选择和1次空池记录。历史轨迹和文件哈希保持不变。

补充原始响应烟测见 `historical_raw_choice_diagnostic_NOT_NEW_EXPERIMENT.json`：4次历史选择均与账本及原始TypeSafe响应一致；第5项是空池、没有选择。第11项测试验证即使替换后的保存选择及其摘要彼此一致，也仍会被原始响应比较拒绝。
