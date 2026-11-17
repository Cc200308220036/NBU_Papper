# GP5 P1-R1 限定整改交付

仅 GP5_P1_R1_LIMITED_REMEDIATION。开发完成交独立质检，不构成P2或正式订单许可。

- source_manifest / code_snapshot：本轮源码及可核对副本；before_source_manifest是同步后原560文件身份。
- sync_receipt / read_inventory：同步与必读摘要。历史导航固定revision，不重签原包。
- test.log / final_evidence：最终固定源码6项R1、13项P1合成验证；监测全为明确TEST_DOUBLE。
- legacy_regression.log：受影响旧N3/N3-R1/绑定21项回归，真实内核与freeze均禁用；最后v16诊断叶子补充不影响旧Schema。
- completion_contract_results：纯覆盖规则夹具，回调故意不做真实验证；不是有效真实收据。
- intermediate*、initial*、pre_diagnostic*、evidence：保留失败/中间测试版本，不充当最终通过证据，也不是额外研究样本。
- checks / verification / handoff / delivery_manifest：逐项检查、限制与清单。manifest排除自身；无add/commit/push。

NUM-01仍OPEN，A03 PARTIAL；真实exact-v3/PCT/LP、freeze、真实来源episode、模型及8job均0。
