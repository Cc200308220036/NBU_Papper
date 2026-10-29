# O5 DeepSeek Flash：pallet_vlm 本地运行命令

日期：2026-10-28。用户已明确使用本地配置好的DeepSeek Flash，真实API由用户执行；不再要求重复填写服务商、地址、模型、密钥或金额。本文件不表示真实预检已通过。

> 2026-10-28修订：01号真实预检HTTP200，模型正确返回红圆/蓝方，但原提示未明确字符串/嵌套结构，严格相等校验将其记为HOLD。01号原件不改判、不覆盖。当前命令已更新为02号输出契约修订：图片、事实答案、模型、次数和数据不变，只明确扁平字符串格式，并分开报告格式错误/视觉事实错误。此前1次真实请求（424输入、25输出tokens）保留在01号账本，不并入02号或删除。

## 1. 已替你完成的准备

沿用项目 `o4_d_deepseek_flash.yaml` 的非敏感配置：endpoint为 `https://api.deepseek.com/chat/completions`，模型 `deepseek-flash`，凭据读取已有环境变量 `DEEPSEEK_API_KEY`。没有读取、保存或显示密钥。O5专用配置为 `semantic_pallet_planner/configs/o5_s2_deepseek_flash.json`，不会改写旧O4配置或客户端。

- 金额模式unlimited，不要求价格、币种和金额上限；费用未知记null。
- thinking显式disabled、JSON输出、输出最多256；探针和选择请求使用同一provider选项。
- 图像detail=high保持原图语义，官方每图1024 token上界用于预算；另加512 framing工程余量及文本UTF-8字节上界。512不是服务商精确token承诺，每次仍校验实际usage，超界停止。
- 不发送seed，当前文档没有公开seed请求参数；不宣称可控的模型随机种子。Flash是在线别名，不假设不可变快照；预期返回model为deepseek-flash，不一致即停止并保留原件。
- 当前预检矩阵最多4次模型请求；后续八单pilot最多290次选择尝试。无隐藏重试、无切换模型或G0兜底。

本地账号标识 `local-pallet_vlm-DEEPSEEK_API_KEY` 只是非敏感凭据引用别名，不是假定的供应商账号UID。

上述接口依据已核对 [DeepSeek图像文档](https://api-docs.deepseek.com/guides/vision/) 和 [Chat Completions文档](https://api-docs.deepseek.com/api/create-chat-completion/)。官方文档兼容不等于用户账号的真实预检通过。

已在本机 `pallet_vlm` 的Python3.11.16、Pillow11.1.0、jsonschema4.23.0、numpy2.1.3环境生成本轮具体计划，ID为 `20261028_02`：

|产物|仓库内路径|
|---|---|
|预检计划|`semantic_pallet_planner/outputs/PLAN_O5_DIRECT_MEMORY_S2_B_DEEPSEEK_20261028_02`|
|摘要和命令清单|`report/analysis/O5_S2_DEEPSEEK_HANDOFF_20261028_02/handoff.json`|
|仅预检阶段记录|`report/analysis/O5_S2_DEEPSEEK_HANDOFF_20261028_02/preflight_authorization.json`|
|预检结果，将在运行后生成|`semantic_pallet_planner/outputs/EXP_O5_DIRECT_MEMORY_S2_B_DEEPSEEK_20261028_02`|

计划已绑定精确源码、依赖、profile、原始开发任务及规范。阶段记录由当前用户指令和本地显式运行命令关联，不自动执行API，也不自动授权后续阶段。当前02号没有真实预检或pilot结果；01号HOLD记录保留。

## 2. 现在先运行这一步：真实预检

在你已配置API的终端中执行。不需要重新导入或粘贴密钥：

```bash
conda activate pallet_vlm
cd /home/cyw/NBU_Papper
python -B -m semantic_pallet_planner.runners.o5_deepseek run-preflight --id 20261028_02
```

这条命令会调用API：两组双色形状图像探针各一次，再做一个固定公共状态的选择契约请求（最多一次格式修复），总计最多4次。它不会启动八单pilot、训练、测试集、R0/M0或S3。

随后可以零网络独立复核：

```bash
python -B -m semantic_pallet_planner.runners.o5_deepseek verify-preflight --id 20261028_02
```

将终端JSON结果和上述预检结果目录路径提供回来即可；无需贴密钥。PASS才表示这次真实接口与探针通过。HOLD、错误、模型不一致或未知在途请求时保留原目录，不换ID反复请求找成功。

正常进程中断且确实需要恢复时，同一命令可加 `--resume`；UNKNOWN_IN_FLIGHT不会因此重发。不要用新目录来绕过暂停或隐藏费用。

## 3. 预检通过后，再手动运行pilot

以下仅供预检PASS后的下一步，不会自动执行。先零网络创建绑定真实预检结果的八单计划及pilot阶段记录：

```bash
python -B -m semantic_pallet_planner.runners.o5_deepseek prepare-pilot --id 20261028_02
```

再由你执行真实pilot：

```bash
python -B -m semantic_pallet_planner.runners.o5_deepseek run-pilot --id 20261028_02
```

该命令只执行冻结开发集前8单，G0/D0共16条记录；D0最多290次尝试，G0无模型调用。预检和pilot共用campaign，保持原始订单分母和所有失败。金额无限额不取消协议和系统异常停止规则。

运行后零网络复核与报告：

```bash
python -B -m semantic_pallet_planner.runners.o5_deepseek verify-pilot --id 20261028_02
python -B -m semantic_pallet_planner.runners.o5_deepseek report-pilot --id 20261028_02
```

pilot结果目录：`semantic_pallet_planner/outputs/EXP_O5_DIRECT_MEMORY_S2_C_DEEPSEEK_20261028_02`；报告目录：`report/analysis/O5_S2_DEEPSEEK_PILOT_20261028_02`。执行完成不等于S2-C通过或D0已封存，仍需按真实协议合法率、物理、费用与难度独立验收；不自动进入S3。

## 4. 只有源码/依赖变化时才重新准备

如计划生成后修改了代码、环境依赖或协议，原计划会拒绝继续。这时在接触新实验结果前，以新ID创建计划：

```bash
python -B -m semantic_pallet_planner.runners.o5_deepseek prepare --id 20261028_03
```

prepare零网络，自动复用已知模型配置、计算摘要及生成阶段记录，不需要你手填摘要或预算。后续命令使用同一新ID。此方式用于明确的新版本准备，不能用于绕过已有未知付费请求、重复pilot挑结果或覆盖历史原件。
