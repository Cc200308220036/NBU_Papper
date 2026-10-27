# O4-E5代表性失败案例

打开`index.html`查看交互页面；`overview.png`和`overview.pdf`适合直接阅读或分享。

来源订单00102047，C0/Text/single，6/12箱处于24个Text/single任务的比例中位数。模型7次AST均正确，第7箱的3.1kg重量与当前低限载/布局产生冲突，33个采样物理候选中业务允许数为0，正确停止而未违规提交。

`last_input.json`为失败点完整业务请求，`last_output.json`为解析后的模型响应，`last_output_raw.txt`保留原始模型文本。`order_snapshot.json`含完整订单，仅供事后分析，未到达对象不是模型当时的输入。`last_candidates.json`记录16个Top-K候选和拒绝原因。`metrics.json`区分订单体积完成52.73%与托盘空间利用16.19%。

完整分析见`docs/03_阶段产出分析/O4/O4E5代表性失败订单可视化与输入输出解析_20261027.md`。

只读分析，无新API、无轨迹重跑、无原始产物改写。
