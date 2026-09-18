# 语义码垛数据集 V1

本目录是[《测试数据集设计》](../测试数据集设计.md)中 MVD-v0.1 的可复现实现。
BED-BPP 提供箱体尺寸、质量、订单归属和到货顺序；MixedPalletBoxes 提供材料、
易碎性、可堆叠性和顶部承重能力的确定性生成逻辑。

## 一、当前数据规模

- 100个基础三维场景：train 50、validation 10、test-ID 20、
  Geometry-OOD 10、Semantic-OOD 10；
- 20个与test-ID物理状态配对的Language-OOD场景；
- 20个分布于五种基础划分中的`buffer_size=3`配对场景；
- 360个固定Decision Case及对应的EMS-style候选集合；
- 360份Oracle候选评价和100份多层可行参考方案；
- 4条Stationary Stream和4条Policy-Shift Stream，每条10个episode。

这是用于跑通接口和开展功能实验的最小数据集，不承担最终统计结论。

## 二、生成与验证

在`/home/cyw/NBU_Papper`下执行：

```bash
python3 semantic_pallet_dataset_v1/scripts/build_dataset.py
python3 semantic_pallet_dataset_v1/scripts/validate_dataset.py
```

如果已经生成过数据，重新生成时需要显式添加`--force`：

```bash
python3 semantic_pallet_dataset_v1/scripts/build_dataset.py --force
```

`--force`只替换自动生成的目录，不会删除`scripts/`、`schemas/`、`configs/`、
`raw/`或README。生成器默认读取仓库根目录下已经下载的两个原始数据源，不复制
78 MB的BED-BPP文件。

## 三、目录说明

```text
semantic_pallet_dataset_v1/
├── configs/                 数据集规模、随机种子和几何约束
├── schemas/                 核心JSON记录的Schema
├── scripts/                 生成器和验证器
├── raw/                     原始数据位置说明，不存放副本
├── catalog/                 商品属性及几何目录
├── tasks/
│   ├── scenarios/           完整场景输入
│   └── decision_cases/      固定状态下的选择任务
├── candidates/
│   ├── candidate_sets/      规划器/VLM可选择的候选
│   └── candidate_audits/    候选过滤和Pareto覆盖审计
├── annotations/
│   ├── ground_truth_rules/  隐藏规则及原始数据关联
│   ├── oracle_candidate_scores/ 候选语义得分和Oracle答案
│   └── reference_feasible_plans/ 多层可行参考方案
├── streams/                 ReMe连续任务流
├── splits/                  数据划分和配对关系
├── statistics/              数据统计、验证报告和文件哈希
└── provenance/              原始数据版本和SHA-256
```

## 四、数据可见性

- 规划器可以读取`tasks/`、`candidates/candidate_sets/`和`streams/`。
- `annotations/`、`candidates/candidate_audits/`、`splits/`、`catalog/`、
  `statistics/`和`provenance/`只供评测器或开发者使用。
- VLM提示词只应包含物理状态、当前可用箱体、自然语言指令和候选列表。
- 场景ID、候选ID仅用于日志关联，不应作为模型的学习特征。
- 不得把来源订单、来源商品、结构化规则、Oracle答案或split名称放进提示词和
  ReMe检索键。

## 五、坐标约定

托盘底面中心为`(0, 0, 0)`。候选位姿中的`x_mm`和`y_mm`表示箱体中心，
`z_base_mm`表示箱体底面高度。箱体保持直立，只允许`yaw=0°`或`yaw=90°`。

## 六、候选生成器的定位

当前生成器是独立实现的EMS-style极值点候选生成器，用来建立统一、可审计的
候选接口，并不等同于完整GOPT算法。它执行边界、不重叠、支撑率、重心投影、
不可堆叠和传播承重等硬约束，再缓存多样化Top-K候选。

`buffer_size=3`场景暂不缓存固定候选，因为动作需要同时确定`pick_item_id`和
放置位姿；这部分候选由后续规划器在完整rollout中实时生成。

## 七、当前阶段与后续步骤

V0.1已经适合开展真值状态实验，包括Geometry-only、Oracle-Rule、VLM、
VLM+Frozen Retrieval和VLM+ReMe。Gazebo物理、RGB-D观测、MoveIt 2可达性和
Aubo i5执行日志属于后续派生数据，不包含在本版本中。

## 八、阶段0数据与接口验收

阶段0已经增加以下接口和工具：

- `scripts/pallet_protocol.py`：统一`request_id + state_hash + candidate_id`协议；
- `scripts/export_vlm_inputs.py`：导出不含Oracle、划分和来源标签的VLM白名单输入；
- `scripts/validate_geometry_independent.py`：不调用候选生成器，独立复核返回候选；
- `scripts/render_decision_cases.py`：生成取料区、当前托盘和Top-K候选图；
- `scripts/run_visual_episode.py`：逐箱生成候选、选择、提交并更新三维场景；
- `scripts/generate_stage0_report.py`：汇总接口、几何、视觉和复现性验收；
- `tests/test_stage0.py`：测试过期状态、未知候选、坐标覆盖及错误姿态等反例。

完整验收命令：

```bash
python3 semantic_pallet_dataset_v1/scripts/build_dataset.py --force
python3 semantic_pallet_dataset_v1/scripts/validate_dataset.py
python3 semantic_pallet_dataset_v1/scripts/validate_geometry_independent.py
python3 semantic_pallet_dataset_v1/scripts/export_vlm_inputs.py
python3 -m unittest discover -s semantic_pallet_dataset_v1/tests -v
MPLCONFIGDIR=/tmp/semantic-pallet-matplotlib \
  python3 semantic_pallet_dataset_v1/scripts/render_decision_cases.py
MPLCONFIGDIR=/tmp/semantic-pallet-matplotlib \
  python3 semantic_pallet_dataset_v1/scripts/run_visual_episode.py --scenario SCN_0001
python3 semantic_pallet_dataset_v1/scripts/generate_stage0_report.py
```

视觉输出位于：

```text
views/vlm_inputs/                 360份VLM白名单JSON
views/rendered/DC_xxxxx/          场景总览和Top-K候选图
views/visual_audit_contact_sheet.png
runs/DEMO_SCN_0001/              完整在线三维码垛回放
```

阶段0自动验收结果见`statistics/stage0_acceptance_report.md`。当前
`buffer_size=1`已通过固定候选和动态episode接口验收；20个`buffer_size=3`
场景尚未生成动态选箱候选，明确留待阶段1实现。
