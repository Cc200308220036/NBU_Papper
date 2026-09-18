# Semantic Pallet Planner — 阶段1A / 1B

基于数据集真值的确定性三维码垛实验平台。采用极值点和支撑层候选生成器，在合法候选中比较几何、规则与Oracle选择器；支持固定决策评测、在线episode、独立复核、日志回放、Top-K实验和3D GIF。

本阶段不运行VLM、ReMe、Gazebo、MoveIt或机械臂，不包含完整GOPT训练。

## 快速运行

以下命令从`NBU_Papper`根目录执行。当前环境已有全部运行依赖，可直接运行模块，无需修改系统Python：

```bash
python3 -m semantic_pallet_planner.cli run-episode \
  --config semantic_pallet_planner/configs/stage1b_geometry_greedy.yaml \
  --scenario SCN_0051 --selector geometry_greedy --render
```

如需安装为Python包，建议在独立环境中安装：

```bash
python3 -m venv --system-site-packages /tmp/pallet-venv
/tmp/pallet-venv/bin/python -m pip install --no-deps --no-build-isolation -e ./semantic_pallet_planner
/tmp/pallet-venv/bin/pallet-planner --help
```

`--no-deps`适用于依赖已经满足的环境；新环境正常执行`pip install -e ./semantic_pallet_planner`。Python至少3.11，运行依赖为NumPy、Matplotlib、Pillow、jsonschema、PyYAML；测试另需pytest。中文动画需要包含中英文字形的字体（本机使用Noto Sans CJK）；字体测试会检查实际字形覆盖。

## 测试与正式验收

当前宿主加载了ROS pytest插件，使用以下环境变量隔离不相关插件：

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest semantic_pallet_planner/tests -q
python3 -m unittest discover -s semantic_pallet_dataset_v1/tests -v

python3 -m semantic_pallet_planner.cli acceptance --stage 1a --experiment-id MY_1A
python3 -m semantic_pallet_planner.cli acceptance --stage 1b --experiment-id MY_1B
```

1A自动运行测试、120条固定决策、SCN_0051在线任务、真实重复运行与回放。1B自动运行测试、validation Top-K分析、1440条固定决策、300场在线任务、5个代表动画与完整回放。动画耗时明显长于数值规划。

每次实验写入独立目录`outputs/<experiment_id>/`。同名目录已存在时拒绝覆盖；省略`--experiment-id`时自动生成时间戳ID。数据集只读，禁止将实验输出设置到数据集目录内。

## 单独运行各模块

```bash
# 固定validation案例四方法
python3 -m semantic_pallet_planner.cli run-fixed \
  --split validation \
  --selectors random_valid,geometry_greedy,handcrafted_rule,candidate_oracle

# 全部360个固定案例的1B四方法
python3 -m semantic_pallet_planner.cli run-fixed \
  --split all --selectors lowest,geometry_greedy,pareto_greedy,candidate_oracle

# 100个基础场景 × 三个在线方法
python3 -m semantic_pallet_planner.cli benchmark \
  --all-base-scenarios --selectors lowest,geometry_greedy,pareto_greedy

# 只允许validation的候选覆盖灵敏度
python3 -m semantic_pallet_planner.cli sweep-topk \
  --split validation --values 4,8,16,32

# 检查保存的证据、独立复核动作、重新生成动态候选
python3 -m semantic_pallet_planner.cli validate --experiment semantic_pallet_planner/outputs/MY_1B
python3 -m semantic_pallet_planner.cli replay --experiment semantic_pallet_planner/outputs/MY_1B

# 从已保存日志重新生成动画，不调用选择器
python3 -m semantic_pallet_planner.cli render \
  --experiment semantic_pallet_planner/outputs/MY_1B \
  --scenario SCN_0051 --method geometry_greedy

# 根据实际证据重新生成验收报告
python3 -m semantic_pallet_planner.cli report --experiment semantic_pallet_planner/outputs/MY_1B
```

`report`不会补跑缺失的测试或实验；普通小实验不满足完整阶段门槛时报告FAIL是正常行为。`render`更新图像后如与既有manifest内容不同，校验会报告产物变化；保留原始正式实验，并将新的展示另存实验副本更便于比较。

## 目录

```text
src/semantic_pallet_planner/
  domain.py             不可变领域快照、内部状态恢复
  repository.py         只读Schema与引用验证
  protocol.py           白名单请求、状态哈希、严格ID响应
  environment.py        在线状态与独立复核后提交
  planner/              几何约束、评分、极值点、Top-K
  selectors/            六类基线及扩展注册表
  runners/              固定、episode、Top-K、阶段验收
  evaluation/           独立物理复核、语义评分、聚合、回放和报告
  visualization/        绘图原语、固定画布动画、统计图
  logging/              JSONL、CSV、manifest、文件哈希
  schemas/              配置、响应、日志、指标、manifest规范
configs/                三份实验配置及抽取来源记录
scripts/                辅助检查脚本
tests/                  unit、integration、golden
outputs/                实验产物（不提交版本控制）
```

完整阶段说明、输入输出、数据流、参数语义和本次实际结果见[阶段1A-1B开发说明](../docs/阶段1A-1B开发说明.md)。

## 阶段1C：GLM固定候选实验

阶段1C代码将真实候选确定性重排为`C01…CK`，删除模型输入中的内部candidate ID，并为视觉模式重新生成选择前工作区图和候选蒙版。GLM只返回显示编号，本地适配器恢复真实ID后继续使用原有协议和评价器。

在`pallet_vlm`环境运行离线测试：

```bash
conda activate pallet_vlm
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest semantic_pallet_planner/tests -q
python -m unittest discover -s semantic_pallet_dataset_v1/tests -v

python -m semantic_pallet_planner.cli run-stage1c \
  --config semantic_pallet_planner/configs/stage1c_glm.yaml \
  --split validation --fake-vlm --experiment-id MY_1C_OFFLINE
```

真实GLM密钥只从环境变量读取：

```bash
export GLM_API_KEY="替换为新密钥"

# 单案例Text+Visual冒烟
python -m semantic_pallet_planner.cli run-stage1c \
  --config semantic_pallet_planner/configs/stage1c_glm.yaml \
  --case DC_00151 --selectors vlm_text,vlm_visual \
  --experiment-id MY_1C_SMOKE

# 完整360案例、六方法正式验收；会产生720次基础VLM调用，格式修复会增加调用数
python -m semantic_pallet_planner.cli acceptance \
  --stage 1c --config semantic_pallet_planner/configs/stage1c_glm.yaml \
  --experiment-id MY_1C_FINAL
```

使用`validate`或`replay`检查保存结果：

```bash
python -m semantic_pallet_planner.cli validate --experiment semantic_pallet_planner/outputs/MY_1C_SMOKE
python -m semantic_pallet_planner.cli replay --experiment semantic_pallet_planner/outputs/MY_1C_FINAL
```

`--fake-vlm`只验证工程链路，不得作为论文模型结果。正式验收要求GLM自身合法响应率至少98%，不将Geometry-Greedy fallback计入该比例。详细设计和验收口径见[阶段1C实验方案](../docs/阶段1C实验方案.md)。

### 切换DeepSeek

`deepseek-flash`支持文本和图像，可直接用于阶段1C的Text/Visual配对主实验：

```bash
export DEEPSEEK_API_KEY="替换为DeepSeek密钥"
python -m semantic_pallet_planner.cli run-stage1c \
  --config semantic_pallet_planner/configs/stage1c_deepseek_flash.yaml \
  --case DC_00151 --selectors vlm_text,vlm_visual \
  --experiment-id EXP_1C_DEEPSEEK_FLASH_SMOKE
```

`deepseek-v4-pro`不支持图像，只能作为额外的Text-only基线：

```bash
python -m semantic_pallet_planner.cli run-stage1c \
  --config semantic_pallet_planner/configs/stage1c_deepseek_v4_pro_text.yaml \
  --case DC_00151 --selectors vlm_text \
  --experiment-id EXP_1C_DEEPSEEK_PRO_TEXT_SMOKE
```

不要用`deepseek-v4-pro`运行`vlm_visual`；适配器会以`model_capability_error`明确拒绝该组合。
