# O5 Direct-Text：pallet_vlm 文本预检与 D0 Pilot

2026-10-28。新协议 `o5_direct_text_v1`，独立入口 `o5_direct_text`。本轮交付离线工程及具体计划，真实文本预检和 D0 Pilot 均未执行。不使用旧 `o5_deepseek` 图文预检结果来放行本协议。

详细契约见 [Direct-Text修订与开发验收规范](../../02_阶段实施方案/O5/O5DirectText独立协议修订与开发验收规范_20261028.md)。沿用已有 DeepSeek Flash、API地址和 `DEEPSEEK_API_KEY` 环境变量；不需要重填配置或密钥。专用配置为 `semantic_pallet_planner/configs/o5_direct_text_deepseek_flash.json`，不覆盖旧图文profile。

## 1. 已完成的准备与绑定

最终02号纳入“预检中断后发送下一请求前先重验已完成探针”的恢复保护。先前01号仅为开发中零网络准备，未发送API，原件保留；活动源码已漂移，应使用02号。已在 pallet_vlm 中零网络生成 `20261028_02` 号独立文本计划。计划绑定当前全部活动Python源码（含快照）、依赖、规范副本/摘要、DATA03、前八单私有完整任务、原物理配置及文本profile。物理配置保留原冻结版本，仅作为不变的几何规则；外层协议和公共请求使用新文本版本。文本计划不依赖字体文件或图片资产。

|产物|仓库内路径|
|---|---|
|真实文本预检计划（尚未运行）|`semantic_pallet_planner/outputs/PLAN_O5_DIRECT_TEXT_PREFLIGHT_20261028_02`|
|绑定摘要、命令、预检阶段记录|`report/analysis/O5_DIRECT_TEXT_HANDOFF_20261028_02/`|
|用户运行后产生的真实预检|`semantic_pallet_planner/outputs/EXP_O5_DIRECT_TEXT_PREFLIGHT_20261028_02`|
|预检与Pilot共享账本（尚未创建）|`semantic_pallet_planner/outputs/CAMPAIGN_O5_DIRECT_TEXT_20261028_02`|
|预检通过后才创建的Pilot计划/运行|`semantic_pallet_planner/outputs/PLAN_O5_DIRECT_TEXT_PILOT_20261028_02` / `EXP_O5_DIRECT_TEXT_PILOT_20261028_02`|

阶段记录把已有用户授权与具体plan/profile/account/campaign关联；用户手动执行远程命令才发送请求。准备不执行预检，预检不执行Pilot，Pilot不启动S3。

## 2. 先零网络复核，再由你执行真实文本预检

以下可在已配置好API的本地终端复制运行。第一条Python命令零网络，核查封存与依赖：

```bash
conda activate pallet_vlm
cd /home/cyw/NBU_Papper
python -B -m semantic_pallet_planner.runners.o5_direct_text validate-plan --id 20261028_02
```

应返回 `READY_FOR_USER_TEXT_PREFLIGHT`、空gaps、`protocol_version=o5_direct_text_v1`、`real_api_attempts=0`。随后由你明确执行这条**会调用API**的命令：

```bash
python -B -m semantic_pallet_planner.runners.o5_direct_text run-preflight --id 20261028_02
```

预检固定使用开发集第一单的两个公共状态：空托盘当前第一箱、原G0放置一箱后的当前第二箱。每个请求均为完整的容器/当前箱/已放箱/候选JSON文本，不传图片，不做识图探针。允许选当前候选或STOP，不指定最优候选；PLACE进行独立物理校验。各状态原始一次＋最多一次格式修复，共最多4次请求；无服务重试，无静默回退。输出≤256，输入保守上界≤12000；金额unlimited，未知费用为null/UNKNOWN。

然后零网络复核及出具预检记录：

```bash
python -B -m semantic_pallet_planner.runners.o5_direct_text verify-preflight --id 20261028_02
python -B -m semantic_pallet_planner.runners.o5_direct_text report-preflight --id 20261028_02
```

报告保存到 `report/analysis/O5_DIRECT_TEXT_PREFLIGHT_20261028_02/verification.json`。只有全部固定文本任务完成、保存响应与绑定重建一致、无未知调用及halt，才返回PASS；应同时确认 `test_double=false`。离线替身结果即使PASS也不能准备真实Pilot。

## 3. 真实文本预检PASS后，才准备并手动执行Pilot

先运行零网络准备；程序核验真实文本预检及同一campaign后，封存具体Pilot计划并生成其阶段记录：

```bash
python -B -m semantic_pallet_planner.runners.o5_direct_text prepare-pilot --id 20261028_02
```

真实文本预检未通过、仅有离线替身或存在绑定漂移会被拒绝，不得跳过门禁。确认后由你执行这条**会调用API**的命令：

```bash
python -B -m semantic_pallet_planner.runners.o5_direct_text run-pilot --id 20261028_02
```

仅冻结开发集 `development_001`—`development_008`，G0/D0共16条记录，原八单145箱、完整订单分母；D0最多290次尝试，G0为0。共享campaign继续保留预检消费和失败。不会运行训练/正式测试集、R0/M0、经验生成或S3。

执行后零网络复核及报告：

```bash
python -B -m semantic_pallet_planner.runners.o5_direct_text verify-pilot --id 20261028_02
python -B -m semantic_pallet_planner.runners.o5_direct_text report-pilot --id 20261028_02
```

报告在 `report/analysis/O5_DIRECT_TEXT_PILOT_20261028_02/`，包含CSV/HTML与验证JSON。运行或verify的PASS表示记录可重建且计划完整，仍须按S2工程整数门槛和难度判断是否可封存D0：最终合法率≥98%、trace100%、物理违规0，八单只是Pilot，不能推断正式性能。现有报告主要给逐单描述；并未实现自动S3准入、完整三维回放或D0封存。提交完整run/campaign供后续复核，不只提交成功截图。

## 4. 中断、失败及版本变化

普通中断恢复使用相同ID和目录，按实际阶段选一条命令：

```bash
python -B -m semantic_pallet_planner.runners.o5_direct_text run-preflight --id 20261028_02 --resume
# 仅已启动Pilot需要恢复时使用：
python -B -m semantic_pallet_planner.runners.o5_direct_text run-pilot --id 20261028_02 --resume
```

reserved确定未发可继续同一attempt；receipt落盘可复用，不重复发送/提交；sent无receipt为UNKNOWN_IN_FLIGHT，停止campaign且禁止重发。HOLD不换题、不换ID反复找通过。缺账本/映射/检查点、改body/响应/源码直接拒绝。失败、早停和未运行任务均保留，不删除账本或把未知费用改零。

源码/规范/依赖实际变化且明确需要建立新版本时，在接触新结果前使用新ID零网络准备：

```bash
python -B -m semantic_pallet_planner.runners.o5_direct_text prepare --id 20261028_03
python -B -m semantic_pallet_planner.runners.o5_direct_text validate-plan --id 20261028_03
```

后续所有命令均使用同一新ID；prepare拒绝覆盖。此命令用于新版本准备，不能规避旧campaign未知请求或重复Pilot挑结果。不要在已交付01号目录上再次prepare。旧图文计划继续按原含义保存，其活动源码漂移拒绝是保护机制；文本通过不改判旧01号HOLD。

## 5. 离线验收复现

证据与零网络工程脚本在 [验收目录](../../../report/analysis/O5_DIRECT_TEXT_ENGINEERING_20261028_01/README.md)。`offline_acceptance.py`已运行并保存产物；它用显式 `test_double=true` 的可控wire测试两个真实公共状态，并以合成完整订单测试断点/恢复/verify/report，不是实际模型结果，也不是八单Pilot。重复运行该证据脚本会拒绝覆盖旧目录。

可重复运行风险与必要回归测试（不读取密钥，不发送HTTP）：

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -B -m pytest -q \
  semantic_pallet_planner/tests/unit/test_o5_direct_text.py \
  semantic_pallet_planner/tests/unit/test_o5_s1.py \
  semantic_pallet_planner/tests/unit/test_o5_s2_remote.py \
  semantic_pallet_planner/tests/unit/test_o5_deepseek.py \
  semantic_pallet_planner/tests/unit/test_o5_optional_amount.py \
  semantic_pallet_planner/tests/unit/test_o5_recovery_hardening.py \
  semantic_pallet_planner/tests/unit/test_o5_visual_probe.py \
  semantic_pallet_planner/tests/unit/test_o5_data_derivation.py \
  semantic_pallet_planner/tests/unit/test_geometry.py \
  semantic_pallet_planner/tests/unit/test_o4_buffer_state.py \
  semantic_pallet_planner/tests/unit/test_o4_buffer_search.py \
  semantic_pallet_planner/tests/unit/test_o4_e2_extensions.py
```

关闭第三方pytest插件自动加载是为了避开本shell的ROS插件缺少lark问题，未修改环境或被测校验。真实服务兼容、实时别名稳定性、实际usage及D0表现仍待本地真实执行验证。
