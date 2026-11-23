# EMS＋Jev 靠角起步单项实验

用户 2026-11-23 明确授权单项真实运行，最多19次发送保留、无隐式重试。源代码、候选规则和静态监测保持不变。新单项计划 `single_experiment_plan_FROZEN.json` 仅允许 EMS/G01；底层 v2 计划保留旧封闭矩阵两槽位以复用原引擎，G00/E2 不派发。新请求和监测账本位于 `ledgers/`，新运行目录为 `run/`。

实验变量是版本化传输文本变换 `append_choice_instructions_only_v1`：在经过公共上下文校验的原请求上，仅向 `questions.next_action.instructions` 追加用户指定英文，其余 state、criteria、Cxx、候选映射、排序及动作不变。`CornerTransport` 复用原 `JevTransport.complete` 认证、单次HTTP及错误处理。基础上下文和账本的 body digest 仍绑定原始请求，**不能把基础上下文中的请求直接称为实际发出的请求**。实际发送的完整 canonical JSON 保存于 `run/sent_requests/NN.json`；相邻 `.binding.json` 绑定基础请求摘要、实际正文SHA256、决策ID及本实验计划；`.instructions.txt` 保存每次完整选择文字。HTTP请求不包含账本、对照结果或私有整单信息。

`final_selection_instructions.txt` 是完整选择文字，准备阶段用对照首步原始文字生成并验证只有该字段变化；实际发送内容以 `sent_requests` 保存件为准。发送前保存正文不是成功发送的证明，真实网络尝试、HTTP结果、发送保留和发送不明以 `ledgers/requests/requests.json` 为准。

本窗口根据已有独立复核及本轮明确用户授权准备新绑定，**没有宣称新增独立审查**。沿用 v3 引用绑定桥接，不重跑历史证据。启动检查失败或运行错误即停止，不重复执行入口。启动命令输出在 `launch.log`，实际退出码在 `exit_code.txt`。

官方接口访问核对日期 2026-11-23：[System One](https://docs.typesafe.ai/api/system-one)、[Choice](https://docs.typesafe.ai/primitives/choice)、[Models](https://docs.typesafe.ai/models)。没有为核对发送额外探测请求。凭证仅由现有加载器读取，未复制入本包。
