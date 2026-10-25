# O4-E0/E1开发与验收证据

最终结果：`EXP_O4_E1_OFFLINE_20261025_03`。E0公共契约、E1完整底面区域约束的单箱/容量3缓冲离线开发验收通过；E2/E3/E5未在本轮完成，E4按用户要求OUT_OF_SCOPE。标签固定顶面朝上。新增真实API调用0。

## 证据

- [开发与结果报告](../../../docs/03_阶段产出分析/O4/O4E0与E1区域约束开发与离线验收_20261025.md)。
- [运行手册](../../../docs/04_运行与复核手册/O4E0与E1区域约束运行及验收手册_20261025.md)。
- [正式验收](../../../semantic_pallet_planner/outputs/EXP_O4_E1_OFFLINE_20261025_03/acceptance_report.json)：EA-01—EA-10、E1-A—E1-E全通过。
- [最终计划](../../../semantic_pallet_planner/outputs/PLAN_O4_E1_OFFLINE_READY_20261025_03/plan.json)：源码/数据/配置冻结、96个完整job身份。
- [pytest.xml](pytest.xml)：190项测试，无失败/错误/跳过；覆盖新E0/E1和旧三约束/V2等价评价。
- [cli_verify.json](cli_verify.json)：从磁盘读419项封存文件、96个主episode，独立复算通过。
- [completion_checks.json](completion_checks.json)：264次实际提交、0物理违规、0候选误放/误拒、资源上限与逐方法分母。
- [physical_commit_checks.json](physical_commit_checks.json)：每次实际提交重新调用独立物理检查器。
- [fifo_single_checks.json](fifo_single_checks.json)：24组single/FIFO几何与选箱序列一致。
- [manual_positive_witnesses.json](manual_positive_witnesses.json)：8个正例×4个手工坐标，未调用生成器/Planner；32次物理与参考业务检查通过。
- [protected.before.json](protected.before.json)：开发前101,248个文件的原始SHA256；[最终保护结果](../../../semantic_pallet_planner/outputs/EXP_O4_E1_OFFLINE_20261025_03/audit/protected.json)无变化。
- [requirements_audit.json](requirements_audit.json)：逐项需求/实验/交付与实际证据对应，不以总PASS替代覆盖检查。
- [evidence.json](evidence.json)：最终汇总及真实API范围。

## 结果边界

主矩阵96个episode中，64个无违规完成；32个对应预先保留的4种受限任务。每个编译来源×规划器均8/12完成，没有证据表明缓冲普遍优于单箱。构造来源及其变体不是未见自然订单，重复/恢复不增加独立样本数。

104张唯一顶面标签PNG被344份公共输入引用并独立核验。新图像不修改旧A5侧面标签图像。真实编译的两个计划已准备：冒烟基础24请求、预算上限48；固定题基础48请求、预算上限96。均未运行，真实在线模型订单与泛化/视觉增量未测。

`_01`保留为较早开发结果；`_02`因执行期间源码漂移而拒绝最终验收。正式结论只用`_03`，并在运行前后验证源码摘要；冻结源码导入的实际用法见运行手册的`python -P -m`说明。
