# DeepSeek Flash 01号预检失败归因与v2契约修订

2026-10-28。01号保留HOLD_ENGINEERING，不改判PASS；当前修复未发送新增模型API。

## 事实

第一张探针的请求实际包含两张PNG，HTTP200、返回model=deepseek-flash、finish_reason=stop。原始usage为424输入/25输出/449总tokens，耗时约1.106秒。费用未知为null。

模型原始文本为：

```json
{"workspace":{"color_shape":"red circle"},"candidates":{"color_shape":"blue square"}}
```

private期望值是workspace=red_circle、candidates=blue_square。视觉事实吻合，但旧提示仅说“workspace and candidates: color_shape”，未明确值必须是字符串、下划线和禁止嵌套；校验器却只接受严格扁平字符串相等，造成该次格式解释差异被泛化为PREFLIGHT_CAPABILITY_FAILED。不能据此归因于账号、网络或模型未识图，也不能凭此判整个S2-B通过。

## 修订范围（发生在第二次真实请求前）

新探针增加response_contract.version=o5_visual_probe_response_v2，明确两个字段、字符串color_shape、下划线、允许颜色/形状以及禁止额外字段和嵌套。提示提供所有通用词汇，不给出图片对应答案。

校验保持严格，不做嵌套展开、空格替换或按已有响应放宽：格式不符为PREFLIGHT_RESPONSE_FORMAT_INVALID；格式合法但视觉事实错误为PREFLIGHT_VISUAL_FACT_MISMATCH。实际执行与只读复核共用同一判定函数。未标版本的旧探针保留旧相等判定语义。

02号继续同一图片字节、事实答案、模型配置、开发来源及4次请求上限；未调整研究数据、候选、物理或S2-C门槛。01号消费1次原件保留，02号后续调用另行记账，不把失败删出累计支出。

## 证据和后续

- original_artifact_hashes.json：01号计划/运行/campaign共252文件修订前哈希，修订后逐一核对。
- original_verification.json：代码修改前独立复核01号仍为HOLD。
- tests.xml：v2正反例、旧响应不被重判、DeepSeek适配与金额/恢复回归。
- prepared_v2.json：在pallet_vlm中零网络生成02号计划和阶段记录。
- acceptance.json：图片相等、原件未变、测试与本轮零新增模型API核查。

[当前用户运行指令](../../../docs/04_运行与复核手册/O5/O5DeepSeekFlash本地预检与Pilot命令_20261028.md)。本轮仅准备，用户执行02号后再根据真实结果判断；不自动进入pilot。
