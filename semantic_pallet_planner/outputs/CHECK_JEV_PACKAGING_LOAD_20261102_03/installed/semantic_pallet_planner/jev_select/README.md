# jev_select

2026-10-30后续开发：[J4公开业务要求经验增强开发与验收规范](../../../../docs/02_阶段实施方案/O4/Jev_J4公开业务要求经验增强开发与验收规范_20261030.md)。A0/A1/B0命令、v3空经验协议、训练导出和证据快照已实现；非空检索、真实提炼及ReMe仍待后续开发。最新真实开发诊断与逐步轨迹见[本地报告](../../../../report/analysis/JEV_PUBLIC_DEV_20261030_01/README.md)。

Jev直接候选选择的独立实现。**J0—J3已完成开发与当前交付。** J3正式80任务、240个方法运行全部结束；完整正式回放按用户要求免除。结果与使用入口见下方J3章节。ReMe经验学习尚未开发。

开发规范：[Jev直接候选选择接入开发与验收规范](../../../../docs/02_阶段实施方案/O4/Jev直接候选选择接入开发与验收规范_20261029.md)。

## 运行环境与J0/J1历史入口

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

`orders`、`orders-smoke`必须显式传`--input-snapshot <恢复的F输入快照>`，不依赖旧F硬编码目录。适配器核验12个来源、synthetic属性、到货顺序和摘要；`orders`保留每来源两套规则，`orders-smoke`固定取排序后前两个来源的四个任务。原F快照仍缺失，旧F来源复现未执行；J3已实现`dataset_orders_v1`并完成来源几何＋受控业务任务对照，使用`dataset-dev/dataset-validation/dataset-orders`及`constructed-eval` profiles，详见J3章节。

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


## J3：物理准入与业务评价（已交付，正式回放按用户要求免除）

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

完整要求见[详细规范](../../../../docs/02_阶段实施方案/O4/Jev_J3物理可行候选与业务软评价实验开发规范_20261029.md)。RC4工程及真实开发04已通过；正式80任务/240-job全部结束，必要记录核对及结果解析完成，完整正式回放按用户要求免除。

J3开发集发现服务概率以两位小数返回，可能出现0.99单位和。v2新增显式strict_or_2dp_rounding_interval_v1兼容契约：严格单位和或存在符合裁剪半分位舍入区间的单位和向量才接受，保留原始概率，不扩大choice最大值容差。v1仍严格。原开发02的INVALID_RESPONSE记录与14次调用保留，后续使用新计划，不能用新解析器重签旧结果。

最终数值边界修正只改selector.py的v2概率网格识别，容许最多8 ULP表示噪声，原始概率不变。RC3全套218项历史回归通过；当前全部单元155项与全部J3集成22项复测通过，不能称为当前222项全量重跑。开发04为24次真实HTTP 200且独立安装包断网回放通过。正式实验目录为outputs/EXP_JEV_J3_TEST_20261029_01，本次冻结源码与计划未改写；网络未知和无效响应均保留，未重发、未改选。

按用户最新交付要求，本次正式批量取消后续独立断网回放与末尾自动整轨迹回放；完成240个核心job后只做必要记录检查、指标汇总和文档分析。完整回放明确标记用户免除且未执行，不冒充PASS。既有replay功能和历史已完成证据保留，生产决策代码、冻结数据及评价口径不变。

### J3正式结果与交付

正式240个方法运行全部结束：27个完整放完、181个物理TopK空池、23个网络结果未知、9个响应校验失败；业务停止0。每方法80任务，Jev/公开业务启发式/几何完整完成6/13/8个，全程合规完成均为0。Jev730次网络尝试收到707次HTTP 200，698个有效远程选择提交，23次未知未重发。当前结果不支持Jev优于公开业务启发式。

按用户要求，正式全量回放未执行；`acceptance_report.json`仅证明必要记录检查，`replay_report.json`明确标记WAIVED_BY_USER_NOT_PERFORMED。全部job保存后为跳过自动回放主动停止CLI，退出130属于预期管理操作；后续汇总没有API调用、候选生成或环境重执行。查看已有metrics即可分析，勿把正式免回放产物当成已通过旧完整回放报告比较。

已知正式用量费用0.498038184美元，未知发送缺少usage，完整费用为null。最新说明与完整分析见[J3交付报告](../../../../docs/03_阶段产出分析/O4/Jev_J3开发验收与真实对照实验_20261029.md)。正式产物：`semantic_pallet_planner/outputs/EXP_JEV_J3_TEST_20261029_01/`；冻结计划同级`PLAN_JEV_J3_TEST_20261029_01/`；证据在`VERIFY_JEV_J3_20261029_01/`。

既有`run`入口仍保留默认末尾回放逻辑。本次已按要求在全部job落盘后取消该阶段，交付为记录级核对；查看已交付结果直接读取metrics，不需要重跑run或replay。

### Jev真实案例3D可视化

[打开独立页面](../../../outputs/JEV_J3_CASE_VIEWER_20261029_01/index.html)，或阅读[可视化源码与导出说明](viewer/README.md)。页面单独展示J0025订单的13次真实Jev选择，包含每步全部候选、3D状态、原始输入输出和独立业务评价。选择解释明确标为事后证据；只读已有记录，无新增模型调用或仿真执行。


## J4首轮：A0/A1/B0

已实现公开业务经验增强的基础工程：A0就绪/暴露审计、A1保存轨迹诊断与多方法过程页、v3空经验计划/执行/恢复、训练白名单导出和携带证据的不可变快照。B1非空检索、B2文本提炼、B3 ReMe及正式收益实验尚未实现。`prepare-j4`目前只允许G0/H0/D0；不接受非空记忆或将R0/M0伪装为已实现方法。

实际使用与验收范围见[运行手册](../../../../docs/04_运行与复核手册/Jev_J4_A0_A1_B0运行与验收手册_20261030.md)。J4运行默认只核对保存记录，不自动执行末尾全轨迹回放；旧J3入口和历史免回放状态保持原意。新增产物写入已忽略的outputs目录。

```bash
python -m semantic_pallet_planner.jev_select audit-j4 --repo <工程根> --output <新审计目录>
python -m semantic_pallet_planner.jev_select inspect-j4 --experiment <已封存实验> --output <新诊断目录>
python -m semantic_pallet_planner.jev_select prepare-j4 --profile constructed-dev --output <新计划>
python -m semantic_pallet_planner.jev_select preflight-j4 --plan <计划>
python -m semantic_pallet_planner.jev_select run-j4 --plan <计划> --output <新实验> --offline
python -m semantic_pallet_planner.jev_select export-memory --experiment <已封存真实训练实验> --output <新导出>
python -m semantic_pallet_planner.jev_select freeze-memory --store <导出目录/store> --output <新快照>
python -m semantic_pallet_planner.jev_select validate-memory --memory <快照>
```

当前没有`build-memory`命令；导出、冻结不会调用LLM或生成策略卡。旧计划可能因新增生产代码报source_changed，应使用原代码快照；不要重签历史清单。

## J4 B1-B：当前离线工程路径

B1-A 查询/门控/BM25 已接入现有 context、selector、episode 和 batch_j4。显式 `prepare-j4 --methods` 现在支持 G0/H0/D0/R0/M0 五个完整方法名；默认仍为原三方法。`--memory` 接收已冻结经验包，R0/M0 共享 corpus、分别使用其模式索引；D0/G0/H0 绑定空文本库。`--task-limit` 只选择确定性的诊断/开发任务前缀并冻结完整计划，不用于正式新源实验。

```bash
PYTHONPATH=src python -m semantic_pallet_planner.jev_select prepare-j4 \
  --task-limit 1 --methods shared_geometry shared_business_lexicographic jev_no_memory jev_raw_history jev_memory_cards \
  --memory <冻结经验包> --output outputs/<新计划>
PYTHONPATH=src python -m semantic_pallet_planner.jev_select preflight-j4 --plan outputs/<新计划>
PYTHONPATH=src python -m semantic_pallet_planner.jev_select run-j4 --plan outputs/<新计划> --output outputs/<新运行> --offline
PYTHONPATH=src python -m semantic_pallet_planner.jev_select validate-j4 --experiment outputs/<新运行>
```

恢复使用同一 run-j4 命令并加 `--resume`。DECISION_READY 在请求前保存检索；重启验证并复用原结果，不重新检索旧决策。COMMITTED 只补未完成评价；原始回答已存不再发送，未知发送不重试。`retrievals/` 保存完整审计，`metrics/` 保存实际条数、字节、门控/预算排除和来源集中度，`process/index.html` 可离线查看。validate-j4 是 records 级核对，不是独立全轨迹回放。

正式远程 prepare/预检/selector 拒绝 fixture。preflight 不读取凭证，只验证本地协议；它不宣称远程凭证就绪。源码内 `tests.demo_j4_b1b` 可生成明确标记的离线工程演示和六个硬重启案例；测试及演示模块不进入 wheel。当前真实两条训练轨迹仍为 0/24 可注入，未形成真实活跃卡；离线替身与 fixture 不证明经验收益。实际交付见仓库 `docs/03_阶段产出分析/O4/Jev_J4_B1_B开发与验收_20261030.md`。

### J4 B2-A generation and review (2026-10-30)

B2-A now provides `prepare-generation`, `generate-memory`, `prepare-memory-merge`,
`inspect-memory-review`, `import-memory-review`, `validate-generation` and
`freeze-generation`. These reuse MemoryStore, the shared ledger utilities and
B1 snapshots/retrieval. `advice` is the claim; v2 cards retain comparison basis,
exact request-scoped field evidence, hypotheses, limitations and independent
human review. Schema/fact checks do not establish semantic support.

```bash
python -m semantic_pallet_planner.jev_select prepare-generation \
  --store <verified-export-store> --experiment <sealed-real-training-run> \
  --mode remote_text --output <new-prepared-directory>
python -m semantic_pallet_planner.jev_select generate-memory \
  --prepared <prepared-directory> --request <request-digest> --store <mutable-store> \
  --mode remote_text --repo <repository-root>
python -m semantic_pallet_planner.jev_select validate-generation --store <mutable-store>
python -m semantic_pallet_planner.jev_select inspect-memory-review \
  --store <mutable-store> --output <new-review-directory>
python -m semantic_pallet_planner.jev_select import-memory-review \
  --store <mutable-store> --review <independent-human-review.json>
python -m semantic_pallet_planner.jev_select freeze-generation \
  --store <mutable-store> --output <new-snapshot-directory>
```

Only explicit `remote_text` execution reads `deepseek_api.md` and contacts the
DeepSeek official endpoint. Offline generation requires `fixture_only` exports
and `--fixture <service-response.json>`; fixtures cannot enter formal remote
plans. Preparation, validation, review and freezing never read credentials or
contact a provider. The frozen configuration/prompt are packaged JSON resources.

The fixed formal account is
`semantic_pallet_planner/outputs/JEV_J4_GENERATION_ACCOUNTING_V1/` under the repo.
B2-A/B2-B and different mutable stores share this account. One generation per
original training episode, at most two proposals; one merge per four episodes;
one structure-only repair per operation. Saved raw responses are reused and
unknown sends are never automatically retried. A changed directory, run name or
input digest does not authorize another generation for the same source episode.

The B2-A real smoke used request
`721a7052734be0bd519076d05451cbb56ab24afc453e0205bdd855e6baed8c2d`:
one official `deepseek-flash` generation succeeded, with no repair. Its single
raw proposal was rejected for historical decision identifiers in prose. Keep
that original and rejection; B2-B must reuse the response, without rewriting
or resending it to obtain a passing card. No real card is active. Two real
independent source groups and independent semantic review remain necessary;
ReMe and benefit experiments were not run. Full evidence and commands are in
`docs/03_阶段产出分析/O4/Jev_J4_B2_A开发与验收_20261030.md` in the repository.

### B2真实经验库后续（2026-10-31）

真实小试采用显式 `--export-version v2`、`--protocol v2`：新增两个训练来源组、四个D0 episode、四次DeepSeek生成，5条原始建议中3条合法candidate、2条保留单位拒绝。独立人工审核尚未完成，active=0，不能将这批工程当作真实非空M0或收益验收。

新增 `--protocol v3` 是离线修复合同：保留v2实际结果，另以 `context_units_v2` 解析数值severity的同级单位；本轮未发送任何v3真实请求。v1/v2/v3请求显式分派、旧请求摘要保持，正式账目仍按原episode身份限频；不能换协议重新生成已消费episode。

`prepare-training-sources --repo <仓库> --readiness <审计目录> --output <新目录>` 从递归暴露与传递去重后的固定前两来源冻结完整训练订单。它复用既有V1属性规范与B1/B2适配，不按运行结果选择。`prepare-j4 --task-ids ...` 可冻结已预登记任务子集。

新卡 `jev_memory_card_v3` 使用 `fact_links`、`memory_prose_v2` 渲染与 `jev_semantic_review_v2`；审核模板逐来源绑定卡、wire、raw和证据。`import-memory-review` 必须由实际具名独立人填写，不由开发代理接受。`prepare-memory-merge --additional-prepared <其他原准备目录>` 保留跨封存采集批次的原episode身份，仍须独立审核父卡及频次条件。

新R0为可逆 `decision_event_columnar_v2`，新索引 `jev_memory_index_v2` 绑定渲染合同；Top3、1600/4800字节和64活跃卡上限不变。当前完整真实池R0为0/38，不得将M0相对空R0解释为组织收益。

本批证据：`outputs/GEN_JEV_J4_B2_REAL_20261031_01/`，验证：`outputs/VERIFY_JEV_J4_B2_REAL_20261031_01/`。既有run须用其原源码快照或对应wheel复核，不修改旧source_manifest适配当前代码。

### 用户变更：开发代理语义核验与纠正准入

用户明确要求“取消独立审阅者这个角色，全权交给你开发即可”。新审核合同`jev_semantic_review_v3/developer_support_review_v1`记录`reviewer_kind=developer_agent`及`independent_review=false`，绑定原文、实际wire/raw和用户变更摘要；不把开发代理判断称为独立审核。两来源、非纯规则复述、冲突、范围、预算及原频次约束不变。旧审核和冻结包仍按原合同加载。

`register-review-authorization --store <store> --authorization <JSON>`保存实际用户角色变更；`inspect-memory-review --reviewer-mode developer_agent --authorization-digest <摘要>`生成新模板，`import-memory-review`导入已实际执行的核验。开发代理父卡的合并还需`prepare-memory-merge --compatibility <成对兼容性文件>`，仅同角色或关键词相同不能替代声明兼容。

`admit-unit-context-correction`只对原v2单位上下文假阴性进行离线纠正准入，生成显式`jev_memory_card_v4/jev_card_fact_validation_v2`并保留原raw、原拒绝及旧生成停止结论。它不能准入标识符拒绝，不能修改正文或放宽1600字节预算，也不增加生成机会。

`inspect-generation-gate`区分解析成功与技术通过；`generate-memory-batch`冻结请求顺序并在首次技术拒绝/失败后持久停止，剩余episode不预约、不发送。`generate-memory`的CLI退出码现在以技术门槛为准，处理状态另保存在processing_status；解析为PARSED不再自动显示PASS。批次恢复复用既有raw及正式账目。

本次实际核验4张卡，接受2、拒绝2；纠正准入1条，另一条1625字节继续拒绝。接受的两张分别是接触规则应用与载荷规则应用，尚无同一声明的两来源支持，active仍为0。新材料位于`outputs/GEN_JEV_J4_B2_DEV_REVIEW_20261031_01/`，不覆盖先前独立审核待办包。


## J4业务数据集v2（2026-11-01）

`build-dataset-v2 --repo REPO --output NEW_DIRECTORY`构建四个已暴露train来源×三难度×B1/B2的24任务快照；`validate-dataset-v2 --dataset DELIVERY`认证加载整包。两者均无凭证、无网络、无episode，不做候选枚举或效果试验。最终交付为`outputs/DATA_JEV_J4_V2_20261101_03`；现有目录拒绝覆盖。

`DatasetOrderAdapter.load(root, spec_config=business_spec_v2_path, difficulty="moderate")`显式启用`public_generated_v2`，loose/strict同理。旧v1默认、未知版本失败；闭合Schema、v1基规范摘要、四来源摘要和重算校准统计共同绑定配置。`prepare-j4`现已接通`--business-spec`和`--difficulty`；本次只检查参数接入，不创建实验矩阵。完整配置及attribute_map为本地材料，不能发送给策略。

实际命令和边界见仓库`docs/04_运行与复核手册/Jev_J4数据集v2构建与复核_20261101.md`，开发报告见`docs/03_阶段产出分析/O4/Jev_J4数据集限载与业务难度v2开发交付_20261101.md`。13项针对性检查通过，物理字段保持；未证明物理早停或实际违规率改善。

生成协议v4可通过`prepare-generation --protocol v4`显式启用；复用v3公共事实投影，独立冻结v4提示，四字段值目标200/300/400/400 UTF-8字节，含74字节字段名/换行目标1374，硬上限仍1600。旧v1/v2/v3协议和原提示保留；语义错误不可通过结构修复改写。v4仍使用原共享账目及技术拒绝停止门槛。

### 状态、动作、违规后果与前期替代方案案例

`inspect-decision-cases --experiment <封存训练实验> --output <新目录> --job J0000 --fork-mode first_violation --max-branches 4`离线提取实际状态、支撑链累计载荷、真实反馈和保存物理池的单步替代后果。固定真实动作前缀，在最多4个早期分支后使用同一本地策略自然运行到终止，分别报告放置量、终态分规则数量/严重度、过程违规实例步数和曾出现的不同实例。少放箱、同规则严重度恶化或过程指标恶化均不能判为支配；不同规则和单位不混成总严重度。

该入口不调用模型、不改经验库；模拟不能作为真实来源。输出结构化案例和文本预览，正式DeepSeek生成、卡片准入和Jev注入合同仍需后续接入。案例中同食品箱平移50mm使受控本地终态违规4→2，但载荷违规未改善。完整证据与命令见`docs/03_阶段产出分析/O4/Jev_J4状态动作与替代方案经验案例开发与验收_20261101.md`；交付目录`outputs/CASE_JEV_J4_STATE_ACTION_20261101_DELIVERY/`。
