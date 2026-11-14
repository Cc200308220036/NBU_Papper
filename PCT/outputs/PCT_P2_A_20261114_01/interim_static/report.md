# PCT P2-A 网络副本与数值验收

2026-11-14。当前为静态准备交付，**P2-A尚未完成；B21 NOT_RUN，等待用户明确授权补装Torch**。不能交作数值验收PASS。没有进入P2-B、P2-C、P3，没有执行订单、候选生成、LP、训练、远程请求或权重下载。

实际基线为dev/PCT、HEAD `c8d1e66c8e379de1e945797076c8a3fb958d46d4`，进入时工作区与暂存区均空。用户提供的QA历史HEAD `68c80a9b`已是祖先；当前提交已包含P1-C及独立QA，保留实际现场。上游提交为`5e7b4238b18310af4529e0f85157d17de605850c`、工作区无修改。本轮新增和修改均在PCT内，没有自动提交或修改第三方。

已有报告声明B10—B18在限定范围内通过；本轮只读核对P1-C与QA的指定JSON及manifest：P1-C 1201项仅共享docs/README因QA追加不同，QA 13项全部匹配。这是摘要核对，不是重跑恢复/订单测试；历史封印和manifest没有修改。P1C-Q01仍交接，P3成本分析前另行处理。

## 已实现与证据

- [最小兼容核心](../src/pct_baseline/vendor/pct/)：保留作者模型、图注意力及点积指针算术和参数键；附原MIT许可、来源摘要及完整upstream.patch。
- [原始参考副本](../outputs/PCT_P2_A_20261114_01/reference/)：model、attention_model、graph_encoder、distributions、tools、evaluation和许可按原字节保存。参考worker设计为独立进程，原始网络不改，tools仅通过AST提取原init与decode函数，避免不必要的Gym导入；这一工具隔离边界不称完整原生环境复现。
- [补丁清单](../outputs/PCT_P2_A_20261114_01/patch_register.json)：相对导入、纯函数提取、局部Categorical、B=1 squeeze调整；严格padding扩展与evaluation语法patch分别登记。
- [严格padding扩展](../src/pct_baseline/network_safety.py)：独立原创扩展，严格key/叶logits屏蔽和无epsilon路径；与原生padding差异须单列。尚未运行，不能称已验证可用。
- [B22登记](../outputs/PCT_P2_A_20261114_01/compatibility_register.json)：语法、全局分布修改、图/池化/叶mask、epsilon、连续/离散密度、排序/H、shuffle/LNES、squeeze及结构参数限制均逐项说明；静态登记不冒充环境行为复验。

上游实际指针是context投影query与glimpse_key缩放点积，经tanh裁剪取叶logits。没有添加glimpse softmax聚合。glimpse_val和logit_key保留原参数结构，预期unused梯度须记录null；不能改填0掩盖。

## 冻结的待运行验证

[数值配置](../configs/network_p2a_v1.json)遵循P0：CPU float32，normFactor=1，已规范化packed输入[B,57,9]，placed40/leaf16/current1，internal6/leaf8/current6，embedding64/单图层/单头。eval()开启；evaluate和deterministic各自False/True做笛卡尔覆盖；固定随机种子、单线程、确定性算法。绝对容差1e-6、相对1e-5，不因失败放宽。

[worker](../tests/p2a_worker.py)与[验证器](../scripts/verify_p2a.py)已编写但数值路径NOT_RUN。设计保存完整输入、随机初始化权重、每张量摘要、概率/value/固定动作logprob/梯度及未使用参数；all-valid覆盖B=1和3，padding、安全扩展、有效叶单个、并列和非法张量分别验证。精确并列取最小有效索引，接近并列须比较概率，argmax不能替代数值比较。

随机初始化仅用于工程一致性，未生成训练权重，未取得论文成绩。当前尚无实际weights.pt或数值输出，不能凭脚本存在声称证据齐全。

## 实际检查与阻塞

实际执行：`PYTHONDONTWRITEBYTECODE=1 python3 PCT/scripts/verify_p2a.py --static-only`，exit0；来源/副本摘要、MIT字节及兼容源码AST通过。原evaluation AST按预期失败，隔离逗号修补文本AST通过。`git diff --check` exit0。

[环境冻结](../outputs/PCT_P2_A_20261114_01/environment_before.json)：现有NBU Python3.12.16，NumPy2.3.5、SciPy1.15.3，Torch和Gym缺失。未安装任何包。拟只补装Torch及必需依赖，保留现有NumPy/SciPy，安装前审查解析方案；不需要Gym、torchvision、torchaudio或预训练权重。用户本轮第二节明确要求缺依赖先获授权，已提出授权问题，尚未收到答复。

安装方案依据[PyTorch官方安装入口](https://docs.pytorch.org/get-started/locally/)核对，访问日期2026-11-14；具体版本、wheel来源和依赖解析尚未执行/冻结，不能预填。

## 验收状态与接续边界

| 项目 | 当前状态 | 原因 |
|---|---|---|
| B20 | PARTIAL | 固定来源、许可、副本、摘要和patch清单已建立；补丁行为验证待Torch |
| B21 | NOT_RUN / BLOCKED_DEPENDENCY_AUTHORIZATION | Torch缺失且安装待明确授权，尚无概率/value/梯度比较 |
| B22 | PARTIAL | 逐项静态处置登记完成；运行反例尚未执行；原生完整论文成绩NOT_RUN |

本阶段没有完成，不声称交回独立质检已具备PASS条件。获得安装授权后仅接续本阶段纯网络验证和报告封存；失败须保留记录，不扩大实验、不修改公共代码/内核/容差。没有下一任务提示词。
