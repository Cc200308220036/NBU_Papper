# jev_select

Jev直接候选选择的独立实现。**J0公共候选、J1离线闭环和J2真实Jev冒烟均已完成。** 已保存4次真实Choice回答；性能对照、未见订单及经验沉淀留待后续阶段。

开发规范：[Jev直接候选选择接入开发与验收规范](../../../../docs/02_阶段实施方案/O4/Jev直接候选选择接入开发与验收规范_20261029.md)。

## 运行

要求Python ≥3.11和工程依赖。独立环境位于`/Users/cyw/Documents/ChatGPT/课题分析/.venvs/jev-select`。源码运行先设置：

```bash
export PYTHONPATH=/Users/cyw/Desktop/NBU_Papper/semantic_pallet_planner/src
```

以下`python`应替换为该独立环境的Python，或安装了本工程的Python。

```bash
python -m semantic_pallet_planner.jev_select prepare --profile constructed-smoke --output <新计划目录>
python -m semantic_pallet_planner.jev_select validate-plan --plan <计划目录>
python -m semantic_pallet_planner.jev_select run --plan <计划目录> --output <新实验目录> --offline
python -m semantic_pallet_planner.jev_select run --plan <同一计划目录> --output <同一实验目录> --offline --resume
python -m semantic_pallet_planner.jev_select replay --experiment <实验目录>
```

`prepare`默认冻结旧工程的4个可行构造、2个矛盾构造，以及`shared_geometry/shared_constrained_first/jev_choice`三个方法，共18个job。计划中同时保存私有评价政策、订单流和生产源码快照；选择器只接收当前白名单上下文，不接收完整订单。构造题不能替代未见订单实验。

离线运行使用显式`--offline`；`jev_choice`在此模式使用测试替身，走真实原生请求编码和响应解析，但没有真实API调用。默认替身按几何特征选项，**不是Jev推理**。其他离线场景可在prepare时用`--offline-scenario`冻结：`pick_last/invalid_choice/wrong_model/wrong_probabilities/non_json/timeout/http_429/http_529`。

`--methods`可指定方法子集。`--global-attempts`和`--per-job-attempts`冻结尝试上限（默认128/32），J1统计的是离线尝试，不是付费API预算。首版每个决策最多一次尝试，无修复、无自动改选或重试。J2另提供显式`--remote`，必须与冻结计划模式一致。

`orders`、`orders-smoke`必须显式传`--input-snapshot <恢复的F输入快照>`，不依赖旧F硬编码目录。适配器核验12个来源、synthetic属性、到货顺序和摘要；`orders`保留每来源两套规则，`orders-smoke`固定取排序后前两个来源的四个任务。当前仓库缺少原F快照，真实来源对照未运行。`dataset_orders_v1`和固定决策题profile尚未开发。

原J0命令继续支持：

```bash
python -m semantic_pallet_planner.jev_select export-j0 --output <新目录>
python -m semantic_pallet_planner.jev_select validate-j0 --artifact <目录>
```

所有导出目录均拒绝覆盖，禁止写入源码/数据等保护目录。源码或资源改变后旧计划/产物会报`source_changed`，不能混用旧回答；应新建计划。历史J0产物保留原样。

## 代码组织与接口

| 模块 | 职责 |
|---|---|
| `config.py`、`configs/` | 版本化配置及冻结几何参数，包内资源不依赖cwd |
| `contracts.py`、`schemas/` | JSON快照、封闭Schema、摘要与错误类型 |
| `candidates.py`、`context.py` | 当前联合候选、公共过滤、白名单特征、编号恢复与绑定 |
| `selector.py` | 选择接口、原生Choice验证、同池基线和Jev选择适配 |
| `transport.py` | 原生UTF-8编码、单次HTTPS能力、拒绝重定向和错误分类；仅显式remote分支真实发送 |
| `testing.py` | 显式离线分支延迟加载的原生字节级服务替身 |
| `ledger.py` | 原子写、独占写锁、一次尝试账目、已存回答复用与未知发送处理 |
| `episode.py` | fill_then_plan到货、直接提交、不可变事件和检查点重建 |
| `evaluation.py` | 提交后独立参考评价、整单结果与分层汇总 |
| `experiment.py`、`replay.py` | 输入适配、冻结计划、运行恢复和只读重建 |
| `cli.py`、`__main__.py` | 唯一模块入口，只开放已完成命令 |
| `tests/unit/`、`tests/integration/` | 断网协议、错误、整单、中断与篡改测试 |

全部新增实现、配置、Schema、替身和测试留在本目录；只读复用原E2几何/规则/commit和独立评价器，不调用旧choose覆盖选择。`__init__.py`保持轻量，导入不联网、不读密钥、不创建输出。wheel携带资源与离线替身，不携带tests。

## 候选和选择约定

- 缓冲1/2/3箱；每箱物理TopK≤16，联合≤48，姿态0°/90°。默认`hard_business_feasible`保留TopK中全部当前公开业务合法动作；`legacy_soft_eligible`显式另列。
- 模型体只有`model/state/questions`；对象用B001别名，选项C01…C48表示完整选箱选位。原始ID、映射、摘要和本地规则AST不进入模型体。公开规则由本地Parser处理，不请求模型生成AST。
- 零物理、零业务分别STOP；单候选自动提交且不伪造模型概率。多候选只提交返回序号对应的动作；提交前重建上下文并复查。
- 响应核对服务模型、问题键、类型、序号、概率键/范围/和、最大概率选择、confidence及usage类型。无效响应停止；低置信度只记录；usage缺失保留null。
- 经验固定为空。当前业务合法不保证未来可完成；几何候选耗尽不证明连续空间全局无解。请求字节上限不等于服务token上限。

## 恢复与产物

计划包含`plan.json/config.snapshot.json/private/input_snapshot.json/source_manifest.json/code_snapshot/`及摘要清单。

实验包含：`requests/`原生体、`mappings/`完整绑定上下文、`audit/attempts.json`原始响应字节的base64/HTTP状态/延迟/预算、`checkpoints/`、`episodes/`、`metrics/`、回放/验收报告和摘要清单。私有输入与评价只在本地日志中保存。

每次尝试先写RESERVED，再保存原始响应，最后提交仿真状态与事件检查点。恢复会重建已提交前缀；已有回答不重新请求，已提交检查点不重复放箱。若只有RESERVED，转UNKNOWN_IN_FLIGHT并停止，不重发。这里的放箱是纯仿真状态提交；没有保证外部真实机器人命令恰好执行一次。

回放只消费保存的回答并重新解析、生成候选、提交和评价；不访问API和密钥。离线替身的字节回答还会独立重算。文件摘要用于一致性检查，不是数字签名，不能抵御将所有源码、计划和证据一致重写的恶意伪造。

## 验收

```bash
PYTHONDONTWRITEBYTECODE=1 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
python -m pytest -q -p no:cacheprovider \
/Users/cyw/Desktop/NBU_Papper/semantic_pallet_planner/src/semantic_pallet_planner/jev_select/tests
```

测试自动移除API密钥、阻断socket连接。完整验收内容与实测结果见J1阶段验收记录。工程PASS与订单是否完成分开记录，不代表模型性能通过。J2真实冒烟：1个构造订单、4/4箱、4次HTTP 200、jev-1.14.0、独立业务违规0；实际输入39977 token，按冻结单价估算0.001679034美元。


## J2真实调用

先冻结单个四箱构造订单，不依据模型表现筛选订单：

```bash
python -m semantic_pallet_planner.jev_select prepare --profile jev-smoke --mode remote --methods jev_choice --api-budget unlimited --output <新计划>
python -m semantic_pallet_planner.jev_select preflight --plan <计划> --api-key-file <本地密钥文件>
python -m semantic_pallet_planner.jev_select run --plan <计划> --output <新实验> --remote --api-budget unlimited --api-key-file <本地密钥文件>
python -m semantic_pallet_planner.jev_select replay --experiment <实验>
```

`preflight`零网络，仅检查首步多候选、请求字节、配置和凭证可读取状态。密钥可来自`TYPESAFE_API_KEY`环境变量，或显式`--api-key-file`指定的单行token/Markdown代码块/环境变量赋值文件。凭证只在需要发送的路径读取；不会写入计划、原生请求、响应账目或manifest。本地`typesafe_api_key.md`已加入Git忽略。

按用户2026-10-29授权，本次使用`unlimited`：计划中global/per-job上限均为null，表示没有人为调用上限，不表示0次。订单只有4箱且每步至多一次，故本冒烟自然上界为4次Choice。也保留显式正整数预算；冻结后运行不能偷偷提高。重试仍为0，未知发送不重发，失败不自动改选。生产remote路径及其回放不导入testing模块。

原始响应保存在`audit/attempts.json`的base64字节字段，包含对应HTTP状态、实际延迟、原始字节摘要和发送状态。解析后保存served_model、概率、confidence和usage。统计区分预约尝试、已观测网络尝试、未知发送及离线替身；usage不完整时总费用保留null，已知用量费用单列。HTTP错误响应体不落盘，避免代理回显凭证。

真实请求P50/P95为约0.603/0.660秒（4个样本）；这是该构造订单的传输调用耗时，不是机器人端到端耗时或稳定吞吐结论。未见订单泛化、几何/特征分项耗时和Jev相对LLM的收益未在J2验证。

工程验收记录：[J1](../../../../docs/03_阶段产出分析/O4/Jev_J1开发与离线验收_20261029.md)、[J2](../../../../docs/03_阶段产出分析/O4/Jev_J2真实接口开发与冒烟验收_20261029.md)。


## J3：物理准入与业务评价（开发验收中）

J3新增v2协议，默认配置为`configs/jev_orders_business_eval_v2.json`。全部物理TopK进入候选，业务不做硬过滤、不阻止物理合法提交、不因已有违规停止；物理碰撞、支撑、stackable和承载限制继续生效。主事实输入没有allowed标记、候选业务得分、参考答案或未来到货。

新增模块：`execution.py`负责物理提交；`dataset.py`负责V1来源订单与公开受控业务任务；`batch.py`负责冻结计划、混合方法批量运行与回放。`episode.py/evaluation.py`按版本保留v1并实现v2，旧配置与J2结果不被改名为J3结果。

统一入口示例（以下python需使用已准备的jev-select环境，源码PYTHONPATH指向本工程src）：

```bash
python -m semantic_pallet_planner.jev_select prepare --profile constructed-eval --mode offline --output <新诊断计划>
python -m semantic_pallet_planner.jev_select run --plan <诊断计划> --output <新诊断实验> --offline
python -m semantic_pallet_planner.jev_select prepare --profile dataset-dev --dataset-root <V1数据集> --mode remote --api-budget unlimited --output <新开发计划>
python -m semantic_pallet_planner.jev_select preflight --plan <开发计划> --api-key-file <本地密钥文件>
python -m semantic_pallet_planner.jev_select run --plan <开发计划> --output <新开发实验> --remote --api-budget unlimited --api-key-file <本地密钥文件>
python -m semantic_pallet_planner.jev_select prepare --profile dataset-orders --dataset-root <V1数据集> --mode remote --api-budget unlimited --output <新正式计划>
python -m semantic_pallet_planner.jev_select run --plan <正式计划> --output <新正式实验> --remote --api-budget unlimited --api-key-file <本地密钥文件>
python -m semantic_pallet_planner.jev_select replay --experiment <实验目录>
```

新profiles自动加载v2，默认三方法为shared_geometry、shared_business_lexicographic和jev_choice。remote计划中的本地基线不联网；仅jev_choice多候选步骤发送一次原生请求。`--methods`可显式指定子集，`--partitions`固定分层；`--source-limit`只用于dataset-dev，不能偷偷缩小正式集。dataset-validation用于原validation分区。

数据：100个基础场景、200个B1/B2任务、99个来源组。正式集保留40个场景、80个任务、240个三方法job，但来源统计单元为39组（ID20/几何OOD9/语义OOD10）；SCN_0088/0089共享一个原订单。语言和buffer3变体不增加独立样本。

原商品类别只有general/electronics。J3保留所有原物理属性与完整到货序列，另以公开固定商品级SHA-256生成受控业务类别和标签；electronics保留，general映射到food/glassware/household_cleaner/general。模型明确看到synthetic_controlled_v1标记。该任务不是原作业单语义复现，原注释只参与来源审计，不定义在线政策。

每步先保存回答，再物理提交并写COMMITTED检查点，最后独立业务评价；评价失败保留已提交状态，恢复只补评价。已有回答不重发，未知发送不自动重发。业务新增事件、唯一实例、持续违规步数和最终违规分别统计；未完成订单的低违规不解读成更好。

单步wall测量边界为准备公共观测开始至独立评价完成，不含最终测量记录写盘；跨进程提交后恢复的连续wall为null，已测阶段时长另列。job计时包含持久化及必要的恢复校验，缓存每job清空并记录命中。统计在任务配对后按来源组聚合，几何OOD仅9个来源组，不把重复配置当作新样本。

v2本地绑定含experiment_binding，覆盖冻结输入、job、模式、预算和源码身份；该摘要不会发送给模型。生产代码变化后旧计划报source_changed，需新计划。J3开始前的J0/J1/J2源码已留在outputs/DEV_JEV_J3_20261029_01/legacy_src，可在该冻结源码环境下复现旧产物。

完整要求见[详细规范](../../../../docs/02_阶段实施方案/O4/Jev_J3物理可行候选与业务软评价实验开发规范_20261029.md)。当前正式实验尚未执行，最终状态以验收报告为准。

J3开发集发现服务概率以两位小数返回，可能出现0.99单位和。v2新增显式strict_or_2dp_rounding_interval_v1兼容契约：严格单位和或存在符合裁剪半分位舍入区间的单位和向量才接受，保留原始概率，不扩大choice最大值容差。v1仍严格。原开发02的INVALID_RESPONSE记录与14次调用保留，后续使用新计划，不能用新解析器重签旧结果。
