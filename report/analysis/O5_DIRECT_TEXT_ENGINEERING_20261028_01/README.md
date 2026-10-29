# O5 Direct-Text 离线工程验收

2026-10-28。离线工程PASS，299项测试通过。真实API新增0；真实文本预检待用户执行；D0 Pilot表现未验证。未启动S3。

- [详细开发与验收规范](../../../docs/02_阶段实施方案/O5/O5DirectText独立协议修订与开发验收规范_20261028.md)
- [阶段验收记录](../../../docs/03_阶段产出分析/O5/O5DirectText独立协议离线开发与验收_20261028.md)
- [pallet_vlm本地命令](../../../docs/04_运行与复核手册/O5/O5DirectText本地预检与D0Pilot命令_20261028.md)
- [机器验收](acceptance.json)、[最终测试](tests.acceptance.final.xml)、[测试日志](tests.acceptance.final.log)
- [启动审计](startup_audit.json)、[初始状态](initial_status.txt)、[修改前哈希](before_hashes.json)、[保护检查](protection.json)、[源码补丁](source_changes.patch)
- [最终02号计划复核](final_plan_review.json)、[计划准备结果](prepared_handoff.final.json)、[实际发送体0](actual_provider_body_0.json)、[实际发送体1](actual_provider_body_1.json)
- [替身流程验收](offline_lifecycle.json)、[替身预检复核](offline_preflight_verification.json)、[替身订单复核](offline_fixture_verification.json)、[工程脚本](offline_acceptance.py)
- [环境问题说明](environment_note.md)、中间XML/log及01号开发中快照均保留，最终结论以final文件为准。

最终用户计划为 `semantic_pallet_planner/outputs/PLAN_O5_DIRECT_TEXT_PREFLIGHT_20261028_02`。纯文本协议 `o5_direct_text_v1`，两个状态各最多2次请求，共≤4。预检真实PASS后才允许准备8单G0/D0（16条记录，D0≤290次尝试）。不重判历史图文HOLD。

本目录offline产物显式test_double=true；4条合成完整订单、68次提交、34次wire仅验证工程，3次开发公共状态wire只验证文本契约。真实用户02号run/campaign/Pilot目录仍不存在。所有费用未知值保持null，known_subtotal的0不代表未知总费用为0。
