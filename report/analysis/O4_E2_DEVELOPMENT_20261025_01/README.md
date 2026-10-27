# O4-E2交付审计

本目录记录E2开发的测试、旧件保护、落盘复算和逐项需求核验；真实API调用为0。正式结果在`semantic_pallet_planner/outputs/EXP_O4_E2_OFFLINE_20261025_01/`，计划在对应`PLAN_O4_E2_OFFLINE_READY_20261025_01/`。

- `protected.before.json`：开发前103681个旧源码、配置、测试及输出文件的SHA256。正式结果的`audit/protected.json`记录核验结果。
- `e2_unit_tests.xml`：96项E2单元测试。
- `e2_tests.xml`：较早83项E2单元测试与12项交付集成测试；重复的83项不计新增测试数。
- `e1_regression_tests.xml`：82项既有E1单元/交付测试。
- `legacy_semantics_tests.xml`：109项旧三约束、V2等价与离线复评测试。
- `cli_help_complete.txt`：实际CLI及全部六个子命令帮助。
- `readonly_verify.json`：冻结代码对96个落盘主episode的只读复算结果。
- `audit_delivery.py`：补充只读审计脚本；对实际提交重新独立检查物理、统计完成分母、核对重复恢复文件、预算与来源，并比较原始数据与Git index。
- `evidence.json`、`summary_checks.json`、`requirements_audit.json`：上述脚本通过后产生的证据和规范逐项映射。不能用目录存在代替PASS。
- `dataset_protected.json`：额外通过Git blob比对的原始数据文件SHA256。
- `source_and_tests.json`：新增E2模块和测试校验和。

测试总数按不同测试身份计数：96 E2单元＋12 E2交付＋82 E1回归＋109旧语义＝299，不把早期重复测试再计一次。

正式实验输出、计划和旧实验保持封存；本审计不重写其manifest，不发起远程请求。模型能力、图像增量及未见泛化未测量。E3和E5为后续阶段，E4为OUT_OF_SCOPE。
