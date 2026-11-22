# GP6 包装顶部限载开关交接

本包为代码及两项离线验收交付，真实调用为 0。基础订单属于已暴露训练来源，可满足性仍为 UNKNOWN。四项历史运行归档保留。

- `fixture_receipt.json`：同一小夹具的默认/关闭模式、E2/EMS 候选、独立复核、公共提交、保存态校验及支撑不足反例。
- `disabled_request.json`、`request_receipt.json`：由公共请求构建链产生的关闭态可发送 JSON；没有发送到服务。监测采用明确标记的 TEST_DOUBLE，未运行真实内核或 LP。
- `gp6_top_load_disabled_plan_DRAFT.json`：显式两项矩阵及当前源码身份；`run_layout_DRAFT.json` 指定独立运行和账本位置。每项最多 19、合计 38 是草案上限，不是调用授权。
- `formal_jev_driver.py`：复用既有 GP6 正式批次驱动实现的两项版本；保留 `run_jev_job`、请求账本、计量和前置授权门禁，原四项驱动未修改。

运行配置 v19、计划 v2、请求/检查点 v19 和账本 v2 独立于历史 v18。旧计划缺开关时仍启用原顶部限载；新模式仅跳过 overload，质量、载荷传播、stackable、总载重和几何检查仍执行。关闭态合规指标为 NOT_APPLICABLE。

后续只核对两项离线验收和两项计划。未经另行授权不冻结、初始化正式账本或执行真实订单。后续开跑须绑定当时源码和环境，准备新的 v19 admission、v3 kernel bridge 及适用性审查，不能重签或覆盖旧运行身份。跨机环境身份变化时重新生成草案，不改写历史记录。
