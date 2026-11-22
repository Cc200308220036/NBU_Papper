# GP6-F0 最终冻结材料交付

本包仅准备固定 G00–G03 最终冻结材料，独立质检待接收；不代表准入或执行授权。当前真实调用授权为 0。

基线：dev/jev-select，origin/dev/jev-select；git pull --ff-only 完成，HEAD d131f3d3033aa8d1885c68691eeeb451cd4e7652，包含 QA 提交 d131f3d30。初始工作区、暂存区为空。未修改已验收驱动、生产源码和历史记录。

最终计划摘要：`40fc57ca5093148adbdd93a722580c12f2de3c32a24541b12df69ddd62f39978`。DRAFT v2 仅改变 status、request_ledger_path、call_ledger_path。任务、后端、源码及监测身份保持，发送保留上限每项 19、合计 76。

目标 Linux、实际绝对路径和解释器见 target_binding.json。账本位于本包 ledgers/，独立于尚不存在的业务目录 GEOM_CANDIDATES_GP6_F0_FORMAL_RUN_20261122_01。requests.json 请求为空；shared_call_ledger.json 的 assessment_entries、solver_calls、test_double_assessments 均为 0；两者绑定同一最终计划摘要。账本文件 SHA-256 与驱动 SHA-256 见 freeze_identity.json。

本机已运行只读材料检查，结果见 readonly_check_receipt.json：计划合同、仅三字段差异、驱动摘要、两账本初态及目录隔离通过；账本字节和目录条目未变，业务目录未创建。该检查不执行正式联合预检，不调用监测、LP、模型或凭证。不重跑历史测试或 GP5。

commands.sh 提供从仓库根运行的默认预检和显式执行两条命令，两者使用相同业务目录。使用目标 Anaconda 环境的 python3。命令尚未运行；待签文件目前不能通过准入检查。独立 QA 完成审查后在这些待签路径放置正式签发文件，并重新记录签发摘要；不得直接把模板状态改成批准。用户必须先明确批准最终计划摘要及固定 G00–G03/19/76，独立 QA 随后才能绑定授权、桥接、API核对、审查并签发总准入。全部材料到位后目标 Linux 必须正式联合预检 4/4，方可按授权单次启动。保留首错停批规则，不隐式重试。

历史源码由已验收驱动复用目标机上 manifest 字节匹配目录，或从固定 Git 提交临时导出并清理，无需另交副本。桥接中的历史路径沿用基线。

交付状态：冻结材料完成；独立 QA 待完成；用户授权待完成；总准入未签发；联合预检 NOT_RUN；G00–G03 全部 NOT_RUN。费用 UNKNOWN（未调用）。未读取密钥、未签发、未提交或推送、未生成下一任务提示词。开发端到此停止。

manifest 覆盖本包除自身外所有文件，记录交付时零账本字节；未来正式签发与执行后的变化必须另留收据，不可冒充此初态。
