# semantic_pallet_dataset_v1 数据集解析

## 1. 这套数据集到底解决什么问题

`semantic_pallet_dataset_v1`不是一个单纯存放箱体尺寸的文件夹，而是一套用于研究以下问题的最小实验系统：

```text
EMS-style几何规划器生成合法候选
                  ↓
VLM根据自然语言和视觉信息选择候选
                  ↓
ReMe-style记忆积累、检索并修正历史经验
                  ↓
后续把同一候选动作交给Gazebo/Aubo执行
```

它目前同时保存五类内容：

1. **任务输入**：容器、箱体、到货顺序、自然语言要求；
2. **几何候选**：当前箱体可以放在哪里；
3. **隐藏答案**：每个候选在业务规则下的得分及Oracle选择；
4. **模型视图**：允许发送给VLM的JSON和三维图片；
5. **运行结果**：某个选择器从第一个箱体开始完整码垛后的轨迹。

理解它最重要的一句话是：

> `tasks/candidates`是题目和选项，`annotations`是标准答案，`views`是发给VLM的试卷，`runs`是某个规划方法实际完成的一次答题过程。

## 2. 数据来源和生成链

### 2.1 原始数据来源

基础箱体数据来自工作区根目录，而不是本数据集目录内部：

```text
/home/cyw/NBU_Papper/raw/bed_bpp/bed-bpp_v1.json
/home/cyw/NBU_Papper/raw/mixed_pallet_boxes/MixedPalletBoxes-v1.0/
```

两个来源承担不同职责：

| 来源 | 本项目使用内容 |
|---|---|
| BED-BPP | 箱体长宽高、质量、订单归属、商品身份、到货顺序 |
| MixedPalletBoxes | 材料、易碎、可堆叠、顶部承重等属性的生成逻辑参考 |

其中，`top_load_limit_kg_synthetic`是合成顶部承重能力，不是真实工业抗压测试值。

### 2.2 完整生成关系

```text
BED-BPP原始订单
       │
       ├── 读取真实尺寸、质量和顺序
       │
       └── 按商品ID确定性生成语义属性
                    ↓
          catalog/商品与几何目录
                    ↓
          tasks/scenarios/完整任务
                    ↓
       EMS-style规划器执行完整可行rollout
          │                       │
          │                       └── annotations/reference_feasible_plans/
          ↓
  从每个基础场景挑选3个有意义的决策时刻
          │
          ├── tasks/decision_cases/              当前状态
          ├── candidates/candidate_sets/         合法选项
          ├── candidates/candidate_audits/       候选质量审计
          └── annotations/oracle_candidate_scores/ 标准答案
                    ↓
          views/vlm_inputs/白名单JSON
                    +
          views/rendered/程序化三维图片
                    ↓
       VLM或几何选择器选择candidate_id
                    ↓
          runs/完整在线运行轨迹
```

## 3. 最重要的ID及其含义

| ID | 示例 | 含义 | 有效范围 |
|---|---|---|---|
| `scenario_id` | `SCN_0001` | 一个完整码垛任务 | 整个数据集 |
| `item_id` | `item_02` | 场景中的一个箱体实例 | 只在当前场景内 |
| `geometry_id` | `G_400x290x230` | 规范化几何尺寸类别 | 整个数据集 |
| `decision_case_id` | `DC_00001` | 从某个场景中截取的单步决策题 | 整个数据集 |
| `candidate_set_id` | `CSET_00001` | 某个Decision Case的候选集合 | 整个数据集 |
| `candidate_id` | `cand_338e85c33a1c` | 当前状态中的一个放置动作 | 只对当前状态有效 |
| `candidate_fingerprint` | `338e85...` | 候选几何内容的稳定摘要 | 候选审计使用 |
| `plan_id` | `PLAN_0001` | 基础场景的参考可行方案 | 基础场景级 |
| `instruction_id` | `INS_...` | 可见自然语言指令标识 | 场景级 |
| `stream_id` | `STREAM_SHIFT_01` | 一条连续记忆实验任务流 | stream级 |
| `physical_state_hash` | 64位SHA-256 | 当前物理状态版本 | 单次决策请求 |

需要特别注意：不同场景中都可能有`item_01`，所以不能只用`item_id`跨场景关联箱体。

## 4. 坐标、箱体位置和旋转

统一坐标系为：

```text
托盘底面中心 = (0, 0, 0)
X轴范围 = [-600, 600] mm
Y轴范围 = [-500, 500] mm
Z轴范围 = [0, 850] mm
```

候选位姿：

```json
{
  "x_mm": -85,
  "y_mm": -300,
  "z_base_mm": 260,
  "yaw_deg": 90
}
```

字段含义：

- `x_mm/y_mm`：箱体水平中心位置；
- `z_base_mm`：箱体底面离托盘底面的高度；
- `yaw_deg`：绕Z轴旋转，只允许0°和90°。

如果箱体高度为230 mm：

```text
z_center = z_base + height / 2
         = 260 + 230 / 2
         = 375 mm
```

数据集保存`z_base`便于表达支撑面；VTK、Matplotlib或Gazebo创建长方体时通常需要换算成中心Z坐标。

## 5. 根目录文件

### 5.1 `README.md`

数据集快速使用说明，包括规模、目录、生成、验证、可见性、坐标约定和阶段0命令。

### 5.2 `VERSION`

当前数据集版本：

```text
0.1.0
```

这是MVD最小可运行版本，不是论文最终冻结版本。

### 5.3 `.semantic_pallet_dataset`

安全标记文件，内容为：

```text
semantic-pallet-dataset-v1
```

`build_dataset.py --force`在删除并重建自动生成目录前会检查该标记，防止脚本误删其他目录。

### 5.4 `requirements.txt`

记录数据、验证和可视化所需Python包版本：

```text
jsonschema
matplotlib
numpy
Pillow
```

它不包含GOPT训练、ReMe完整运行或ROS 2依赖。

## 6. `raw/`：原始数据位置说明

### `raw/README.md`

这里只说明真正原始数据在哪里，不重复复制BED-BPP的大文件。

```text
semantic_pallet_dataset_v1/raw/README.md
        ↓ 指向
NBU_Papper/raw/bed_bpp/bed-bpp_v1.json
NBU_Papper/raw/mixed_pallet_boxes/MixedPalletBoxes-v1.0/
```

因此，数据集内部的`raw/`不是数据副本。删除工作区根目录的两个原始来源后，就不能从头重新构建数据集。

## 7. `configs/`：统一生成参数

### `configs/mvd_v0.1.json`

这是整个MVD数据集的主配置文件，同类配置以后可以增加`dataset_v1.0.json`。

主要字段如下：

| 字段 | 当前值 | 含义 |
|---|---:|---|
| `dataset_version` | `0.1.0` | 数据集版本 |
| `dataset_seed` | `20260911` | 所有确定性随机过程的根种子 |
| `container` | 1200×1000×850 mm | 固定三维码垛区域 |
| `max_payload_kg` | 1000 | 容器最大总载荷 |
| `items_per_scenario` | 8—20 | 每个场景箱体数量 |
| `target_volume_ratio` | 0.35—0.80 | 订单箱体总体积占容器体积范围 |
| `support_ratio_min` | 0.70 | 上层箱体最低支撑面积比例 |
| `height_threshold_mm` | 340 | Geometry-OOD高箱体阈值 |
| `top_k` | 16 | 每个固定决策点最多返回候选数 |
| `yaw_degrees` | `[0,90]` | 允许朝向 |
| `decision_cases_per_scenario` | 3 | 每个基础场景截取3个决策点 |
| `buffer3_pair_count` | 20 | buffer3配对场景数量 |
| `episodes_per_stream` | 10 | 每条ReMe任务流episode数量 |
| `policy_shift_episode` | 6 | 从索引6开始切换规则 |

几何评分权重为：

```text
geometry_score =
    0.35 × compactness
  + 0.25 × height
  + 0.25 × stability
  + 0.15 × balance
```

修改配置后必须重新构建数据，不能只修改JSON而继续使用旧候选。

## 8. `catalog/`：商品属性和几何目录

### 8.1 `catalog/article_attributes.json`

当前是一个包含405条记录的JSON数组，每条表示一个BED-BPP来源商品的稳定属性。

```json
{
  "source_article_id": "00102366",
  "geometry_id": "G_400x290x230",
  "material": "Cardboard",
  "fragile": false,
  "stackable": true,
  "top_load_limit_kg_synthetic": 16.68,
  "product_category": "electronics"
}
```

用途：

- 保证同一来源商品每次构建获得相同属性；
- 审计尺寸与语义标签是否存在偏差；
- 追踪合成属性如何加入BED-BPP商品。

该文件包含`source_article_id`，不应发送给VLM。

### 8.2 `catalog/geometry_catalog.json`

当前包含232种不同几何尺寸。

```json
{
  "geometry_id": "G_240x190x190",
  "count": 4,
  "attribute_combination_count": 1
}
```

字段含义：

- `geometry_id`：按三边规范化后的尺寸类别；
- `count`：基础场景中出现次数；
- `attribute_combination_count`：相同几何对应多少种语义属性组合。

该目录用于统计和偏差审计，不是VLM运行时输入。

## 9. `tasks/`：模型和规划器要完成的任务

### 9.1 `tasks/scenarios/SCN_xxxx.json`

每个文件代表一个完整码垛任务。当前共140个可见场景文件。

```json
{
  "scenario_id": "SCN_0001",
  "container": {},
  "items": [],
  "arrival_order": [],
  "buffer_size": 1,
  "instruction": {
    "instruction_id": "INS_...",
    "text": "电子产品箱不得与重物箱直接接触或形成上下支撑关系。"
  }
}
```

#### `container`

定义固定码垛空间：

```text
container_id
length_mm
width_mm
max_height_mm
max_payload_kg
coordinate_frame
```

#### `items`

按场景保存所有箱体，每个箱体包括：

```text
item_id                 场景内箱体编号
geometry_id             几何类别
dimensions_mm           长宽高
mass_kg                 质量
weight_class            light/medium/heavy
material                材料
fragile                 是否易碎
stackable               能否作为直接支撑
top_load_limit_kg_synthetic 合成顶部承重
product_category        general/electronics
```

#### `arrival_order`

箱体到货顺序，例如：

```json
["item_01", "item_02", "item_03"]
```

严格在线任务只能读取当前到达箱体，不能因为完整场景文件保存了未来顺序，就把后续箱体全部提供给模型。

#### `buffer_size`

- `1`：严格在线，只能选择当前箱体；
- `3`：可以从当前最多3个箱体中选一个。

当前buffer3场景只有场景定义，没有固定Decision Case和候选集。

#### 140个场景如何组成

| 场景范围 | 数量 | 含义 |
|---|---:|---|
| `SCN_0001—0050` | 50 | train基础场景 |
| `SCN_0051—0060` | 10 | validation基础场景 |
| `SCN_0061—0080` | 20 | Test-ID基础场景 |
| `SCN_0081—0090` | 10 | Geometry-OOD |
| `SCN_0091—0100` | 10 | Semantic-OOD |
| `SCN_0101—0120` | 20 | 与Test-ID物理状态配对的Language-OOD |
| `SCN_0121—0140` | 20 | 与基础场景配对的buffer3版本 |

前100个是独立基础物理任务；后40个是配对实验视图，不是40个全新独立订单。

### 9.2 `tasks/decision_cases/DC_xxxxx.json`

每个文件是从完整场景某一步截取出的固定选择题。当前共360个。

```json
{
  "decision_case_id": "DC_00001",
  "base_scenario_id": "SCN_0001",
  "step_index": 1,
  "placed_items": [],
  "available_items": [],
  "instruction_text": "...",
  "candidate_set_id": "CSET_00001"
}
```

字段含义：

- `base_scenario_id`：该决策点来自哪个完整任务；
- `step_index`：完整任务中的第几步，索引从0开始；
- `placed_items`：决策前已经放入托盘的箱体；
- `available_items`：当前允许选择的箱体；
- `instruction_text`：当前业务要求；
- `candidate_set_id`：去哪里读取本题选项。

`placed_items`除了位置，还保留质量、易碎、可堆叠、类别、当前已承受载荷和支撑分配，便于复算承重与语义关系。

Decision Case不是完整运行轨迹。每个基础场景只挑3个有代表性的时刻，用于让不同方法面对完全相同的状态和候选。

## 10. `candidates/`：几何规划器给出的选项

### 10.1 `candidates/candidate_sets/CSET_xxxxx.json`

一个CandidateSet与一个Decision Case一一对应。

顶层字段：

| 字段 | 含义 |
|---|---|
| `candidate_set_id` | 候选集合编号 |
| `scenario_id/step_index` | 来源场景和步骤 |
| `physical_state_hash` | 容器、已放箱体、可用箱体和buffer的状态摘要 |
| `decision_context_hash` | 物理状态加当前指令的摘要 |
| `generator` | 生成器名称、版本、配置哈希和Top-K |
| `coordinate_frame` | `container_bottom_center` |
| `length_unit` | `mm` |
| `raw_candidate_count` | 生成器尝试过的原始位置数量 |
| `physical_valid_count` | 经过硬约束过滤后的数量 |
| `returned_count` | 最终返回给决策器的数量 |
| `candidate_order_seed` | 展示顺序的确定性随机种子 |
| `candidates` | 候选动作数组 |

单个候选示意：

```json
{
  "candidate_id": "cand_338e85c33a1c",
  "candidate_fingerprint": "338e85...",
  "pick_item_id": "item_02",
  "pose": {
    "x_mm": -140,
    "y_mm": -355,
    "z_base_mm": 0,
    "yaw_deg": 0
  },
  "oriented_size_mm": [400, 290, 230],
  "ems": {},
  "support": {},
  "load": {},
  "resulting_geometry": {},
  "geometry_score_components": {},
  "physical_valid": true,
  "physical_rejection_reasons": []
}
```

#### `ems`

- `ems_id`：空余空间标识；
- `ems_type=floor_space`：放在托盘底面；
- `ems_type=supported_space`：放在其他箱体顶面。

#### `support`

- `support_item_ids`：直接支撑当前箱体的箱体ID；
- `support_ratio`：箱体底面被支撑的面积比例；
- `com_margin_mm`：重心投影距离有效支撑边界的裕量。

#### `load`

- `downward_load_kg`：候选箱体当前已有的向下载荷；
- `minimum_remaining_capacity_kg`：支撑链中最小剩余承重；底层可为`null`。

#### `resulting_geometry`

执行该候选后的结果：

```text
max_height_mm
volume_utilization
center_of_mass_offset_mm
```

#### `geometry_score_components`

归一化几何分项：

```text
compactness
height
stability
balance
```

这些是几何规划器计算的信息，可以提供给VLM；它们不是语义Oracle答案。

### 10.2 `candidates/candidate_audits/CSET_xxxxx.json`

与CandidateSet同名，共360个。它不提供给VLM，用于审计“Top-K有没有丢掉重要候选”。

```json
{
  "rejection_histogram": {},
  "pareto_candidate_fingerprints": [],
  "pareto_recall_at_k": 1.0,
  "geometry_oracle_fingerprint": "...",
  "geometry_oracle_score": 0.82,
  "epsilon_optimal_recall_at_k": true
}
```

字段含义：

- `rejection_histogram`：越界、重叠、支撑不足、超载等各自拒绝多少原始候选；
- `pareto_candidate_fingerprints`：多目标下不被其他候选全面支配的候选；
- `pareto_recall_at_k`：这些Pareto候选被Top-K保留的比例；
- `geometry_oracle_fingerprint/score`：所有合法候选中几何分数最高者；
- `epsilon_optimal_recall_at_k`：Top-K是否包含与几何最优相差不超过epsilon的候选。

它评价的是候选生成质量，不是VLM选择质量。

## 11. `annotations/`：隐藏规则、标准答案和参考方案

整个`annotations/`只允许评价器和研究者读取，不允许直接放入VLM提示词或ReMe检索键。

### 11.1 `annotations/ground_truth_rules/SCN_xxxx.json`

每个可见场景一个，共140个。它保存自然语言背后的结构化规则和原始来源追踪。

```json
{
  "scenario_id": "SCN_0001",
  "ground_truth_rules": [
    {
      "rule_type": "category_separate",
      "target_attribute": "product_category=electronics",
      "priority": 1,
      "hard_or_soft": "hard",
      "thresholds": {},
      "canonical": "...",
      "paraphrases": []
    }
  ],
  "source_order_id": "...",
  "source_order_key": "...",
  "source_article_ids": [],
  "source_sequence_positions": [],
  "split": "train",
  "split_group_id": "TRAIN",
  "reference_feasible_plan_id": "PLAN_0001"
}
```

五类规则：

| `rule_type` | 含义 | 默认性质 |
|---|---|---|
| `heavy_low` | 重物尽量低放 | 软规则 |
| `heavy_center` | 重物尽量靠近中心 | 软规则 |
| `fragile_protect` | 易碎品尽量高放且少承载 | 软规则 |
| `category_group` | 电子产品尽量集中 | 软规则 |
| `category_separate` | 电子产品与重物禁止接触/支撑 | 硬规则 |

Language-OOD文件还会有`paired_canonical_scenario_id`，表示它与哪个Test-ID场景共享完全相同的物理内容。

### 11.2 `annotations/oracle_candidate_scores/DC_xxxxx.json`

每个Decision Case一个，共360个，是候选选择题的标准答案。

```json
{
  "decision_case_id": "DC_00001",
  "candidate_set_id": "CSET_00001",
  "ground_truth_rule": {},
  "geometry_reference": {},
  "candidate_evaluations": [],
  "oracle_candidate_id": "cand_...",
  "semantic_utility_range": 1.0,
  "semantic_decision_required": true
}
```

`candidate_evaluations`为每个候选保存：

```text
candidate_id
geometry_score
semantic_score_components
soft_utility
hard_violations
```

Oracle排序原则：

1. 硬规则违规数量更少；
2. 语义效用更高；
3. 前两项相同时几何分数更高。

`semantic_decision_required=true`表示候选间存在明显语义差异，而且语义Oracle与几何最佳不是同一候选。这个字段是答案信息，所以已经从公开CandidateSet中移到这里。

### 11.3 `annotations/reference_feasible_plans/PLAN_xxxx.json`

仅为100个基础场景生成，共100个。

```json
{
  "plan_id": "PLAN_0001",
  "scenario_id": "SCN_0001",
  "planner": "extreme_point_ems_style_geometry_oracle_v0.1",
  "is_globally_optimal": false,
  "placements": []
}
```

用途：

- 证明所选场景能够完成多层放置；
- 提供构建Decision Case时的中间状态；
- 调试渲染和物理约束；
- 作为可行参考，不是全局最优答案。

如果VLM在完整episode中选择了与参考方案不同的动作，后续不能继续照搬该参考方案，必须基于新状态重新生成候选。

## 12. `splits/`：训练、测试和配对关系

### 12.1 普通划分文件

文件包括：

```text
train.json
validation.json
test_id.json
test_geometry_ood.json
test_semantic_ood.json
test_language_ood.json
```

结构相同：

```json
{
  "split": "train",
  "scenario_ids": [],
  "decision_case_ids": []
}
```

它回答：

- 这个划分有哪些完整场景；
- 这个划分有哪些固定Decision Case。

### 12.2 buffer3划分文件

```text
train_buffer3.json
validation_buffer3.json
test_id_buffer3.json
test_geometry_ood_buffer3.json
test_semantic_ood_buffer3.json
```

当前合计20个场景，`decision_case_ids`均为空。这意味着buffer3的场景定义已经存在，但“同时选择箱体和位置”的候选生成器尚未实现。

### 12.3 `splits/group_manifest.json`

共140条，记录不同场景是不是同一物理任务的变体。

```json
{
  "scenario_id": "SCN_0101",
  "base_physical_id": "PHY_0061",
  "scenario_family_id": "FAM_013",
  "pair_group_id": "PAIR_0061",
  "variant_id": "language_ood",
  "split_group_id": "TEST_ID_LANGUAGE"
}
```

字段含义：

- `base_physical_id`：物理内容相同的任务共享它；
- `pair_group_id`：配对统计时使用；
- `variant_id`：`canonical_instruction/language_ood/buffer3`；
- `scenario_family_id`：相关场景族；
- `split_group_id`：防止配对样本跨训练测试泄漏。

Language-OOD与Test-ID是配对观察，不应当作40个独立物理样本计算统计显著性。

## 13. `streams/`：ReMe连续任务流

### 13.1 `streams/stationary/STREAM_STATIONARY_xx.json`

共4条，每条10个episode。在同一条流中规则保持不变。

```json
{
  "stream_id": "STREAM_STATIONARY_01",
  "stream_type": "stationary",
  "memory_reset_group": "RESET_STATIONARY_01",
  "episodes": [
    {
      "episode_index": 0,
      "scenario_id": "SCN_0061",
      "policy_version": "P1",
      "instruction": "重物应尽量放在较低层。"
    }
  ]
}
```

用途：观察ReMe在规则稳定时是否能够逐步积累有效经验。

### 13.2 `streams/policy_shift/STREAM_SHIFT_xx.json`

共4条，每条10个episode。在`episode_index=6`发生规则变化。

```json
{
  "episode_index": 6,
  "scenario_id": "SCN_0067",
  "policy_version": "P2",
  "instruction": "重物应尽量靠近托盘底面中心。",
  "change_event": "heavy_low_to_heavy_center"
}
```

用途：评价旧经验是否造成负迁移，以及动态记忆需要多少episode才能修正。

`memory_reset_group`表示每条流必须从独立空白记忆启动，不能把另一条测试流学到的经验带进来。

目前stream只是实验顺序清单，还没有保存真正的ReMe记忆内容。

## 14. `schemas/`：JSON文件的格式合同

Schema不存放样本，而是规定同类JSON必须有什么字段、字段类型和合法范围。

| Schema文件 | 验证对象 |
|---|---|
| `scenario.schema.json` | `tasks/scenarios/SCN_*.json` |
| `decision_case.schema.json` | `tasks/decision_cases/DC_*.json` |
| `candidate_set.schema.json` | `candidates/candidate_sets/CSET_*.json` |
| `candidate_audit.schema.json` | `candidates/candidate_audits/CSET_*.json` |
| `ground_truth_rule.schema.json` | `annotations/ground_truth_rules/SCN_*.json` |
| `oracle_annotation.schema.json` | `annotations/oracle_candidate_scores/DC_*.json` |
| `reference_plan.schema.json` | `annotations/reference_feasible_plans/PLAN_*.json` |
| `split.schema.json` | 各普通/buffer3划分文件 |
| `group_manifest.schema.json` | `splits/group_manifest.json` |
| `stream.schema.json` | 两类stream文件 |
| `vlm_request.schema.json` | `views/vlm_inputs/DC_*.json`及运行时请求 |
| `vlm_response.schema.json` | VLM应该返回的响应 |

例如，`candidate_set.schema.json`要求：

- 状态哈希必须是64位十六进制字符串；
- `yaw_deg`只能是0或90；
- 支撑率必须在0到1之间；
- `physical_valid`必须为`true`；
- `physical_rejection_reasons`必须为空。

Schema验证只能检查格式和局部数值范围，不能独立证明箱体没有重叠，所以还需要`validate_geometry_independent.py`。

## 15. `views/`：发给VLM的派生视图

`views`中的内容都可以由核心JSON重新生成，不是新的原始数据。

### 15.1 `views/vlm_inputs/DC_xxxxx.json`

共360份，由Decision Case、场景容器和CandidateSet合并后进行白名单过滤得到。

```json
{
  "schema_version": "pallet_vlm_request_v1",
  "request_id": "DC_00001",
  "state_hash": "...",
  "instruction_text": "...",
  "container": {},
  "placed_items": [],
  "available_items": [],
  "candidates": [],
  "visual_inputs": {
    "workspace_image": "../rendered/DC_00001/workspace.png",
    "candidate_montage": "../rendered/DC_00001/candidates_montage.png"
  }
}
```

它不会包含：

```text
oracle_candidate_id
semantic_decision_required
ground_truth_rule
split
source_order_id
source_article_id
参考完整方案
```

### 15.2 `views/rendered/DC_xxxxx/workspace.png`

左侧显示当前取料/缓存箱体，右侧显示当前托盘状态。数据来自对应Decision Case和Scenario。

属性缩写：

```text
H  heavy
F  fragile
E  electronics
NS non-stackable
```

### 15.3 `views/rendered/DC_xxxxx/candidates_montage.png`

把当前最多16个合法候选绘制为4列网格。每个小图只增加一个半透明黄色候选箱，便于VLM比较位置。

`C01—C16`只是当前图片中的展示编号；真正执行和评价使用`candidate_id`。

### 15.4 `views/rendered/DC_xxxxx/render_metadata.json`

记录渲染器、相机角度、坐标系、单位、候选样式，以及是否绘制答案标签。

### 15.5 `views/visual_audit_contact_sheet.png`

30个分层抽查场景的总览图，只供人检查坐标、旋转、穿模、属性颜色和答案泄漏，不是正式VLM输入。

## 16. `runs/`：一次完整在线运行的产物

`runs/DEMO_SCN_0001`表示选择器从`SCN_0001`第一个箱体开始，连续运行完整任务后的结果。

### 16.1 `runs/DEMO_SCN_xxxx/episode.json`

记录整个episode：

```text
scenario_id
selector
completed_steps
requested_steps
final_placed_items
trajectory
```

`trajectory`中每一步保存选中的完整候选、候选数量和审计数据。

### 16.2 `runs/DEMO_SCN_xxxx/final_layout.png`

完整episode结束后的最终三维码垛图。

### 16.3 `step_xxx/vlm_request.json`

这一动态步骤如果交给VLM，它应该看到的白名单请求。目前虽然文件名叫`vlm_request`，演示选择器并没有真正调用VLM。

### 16.4 `step_xxx/selection.json`

保存当前选择器的选择：

```json
{
  "request_id": "SCN_0001_STEP_000",
  "state_hash": "...",
  "candidate_id": "cand_...",
  "selector": "geometry_best_demo"
}
```

当前选择器是`geometry_best_demo`，只选择几何评分最高的候选，不理解自然语言，也不使用ReMe。

### 16.5 `step_xxx/workspace.png`

执行动作前的取料区和托盘状态。

### 16.6 `step_xxx/candidates_montage.png`

当前动态状态下在线重新生成的Top-K候选，不是固定`CSET_xxxxx.json`的简单复制。

### 16.7 `step_xxx/selected_result.png`

绿色箱体表示本步选择后预期形成的状态。

### 16.8 为什么演示中经常看到C01被选择

当前`run_visual_episode.py`先按几何分数排序，再给候选分配展示编号，所以C01就是当前几何最佳候选；它不是跨步骤相同的动作。正式VLM实验必须打乱候选展示顺序，避免模型只学习“总选第一项”。

## 17. `statistics/`：统计和验收结果

### 17.1 `dataset_summary.json`

数据集总体统计：场景数、Decision Case数、箱体数、几何数、商品数、属性数量、偏差指标和候选拒绝原因。

### 17.2 `generated_checksums.json`

核心JSON文件的SHA-256清单。两次完整重建后比较该文件，可验证生成结果是否逐字节一致。

`views`和`runs`属于派生输出，不纳入核心数据哈希。

### 17.3 `validation_report.json`

基础验证结果，包括Schema、引用完整性、场景数量、来源订单隔离、OOD留出、Language-OOD物理配对、语义激活率和stream时序。

### 17.4 `independent_geometry_report.json`

独立几何复核结果。目前复核5124个返回候选，其中1963个是`z_base>0`的多层候选，错误数为0。

### 17.5 `reproducibility_report.json`

记录两次`--force`重建后校验和是否一致。

### 17.6 `visual_audit_manifest.json`

记录30个视觉抽查样本来自哪个划分、是否多层、图片路径和需要检查的项目。

### 17.7 `stage0_acceptance_report.json`

机器可读的阶段0总验收结果，包含检查项、规模、候选质量、复现性和buffer3能力边界。

### 17.8 `stage0_acceptance_report.md`

与上一文件对应的人类可读中文报告。

## 18. `provenance/`：数据来源追踪

### `provenance/manifest.json`

记录：

- 数据集发布日期；
- 使用哪个生成脚本；
- 使用哪个配置及其SHA-256；
- BED-BPP路径和SHA-256；
- MixedPalletBoxes Git提交版本；
- 使用的属性逻辑文件哈希。

它回答“这批数据到底由哪个版本的原始来源和配置生成”，是论文复现的重要文件。

## 19. `scripts/`：每个脚本具体负责什么

### 19.1 `build_dataset.py`：核心数据构建器

职责最多的脚本，完成：

1. 读取BED-BPP订单；
2. 清洗尺寸和质量；
3. 按商品ID确定性生成语义属性；
4. 按条件选择8—20箱的订单窗口；
5. 生成train/validation/ID/OOD基础场景；
6. 运行EMS-style几何rollout；
7. 检查边界、重叠、支撑、重心、不可堆叠和传播承重；
8. 保存100份参考可行方案；
9. 从每个基础场景选3个Decision Case；
10. 生成候选集、候选审计和Oracle答案；
11. 生成20个Language-OOD配对场景；
12. 生成20个buffer3配对场景；
13. 生成8条ReMe任务流；
14. 生成catalog、splits、statistics和provenance。

候选生成关键函数：

| 函数 | 作用 |
|---|---|
| `candidate_points()` | 从托盘和已放箱体表面生成极值位置 |
| `evaluate_pose()` | 对一个位置做硬约束检查并计算特征 |
| `propagate_load()` | 沿支撑图传播上层载荷 |
| `pareto_front()` | 找多目标非支配候选 |
| `select_diverse_topk()` | 保留具有多样性的Top-K |
| `generate_candidates()` | 组合候选生成、过滤和截断 |
| `commit_candidate()` | 把已选候选写入当前状态 |
| `rollout()` | 从第一个箱体运行到最后一个箱体 |
| `semantic_evaluation()` | 按隐藏规则计算语义分数/违规 |

启动：

```bash
python3 semantic_pallet_dataset_v1/scripts/build_dataset.py --force
```

`--force`表示替换自动生成的：

```text
catalog tasks candidates annotations streams splits statistics provenance
```

它不会删除`scripts/`、`schemas/`、`configs/`、`README.md`、`views/`和`runs/`。

### 19.2 `validate_dataset.py`：基础结构和划分验证器

检查：

- 所有核心JSON是否符合Schema；
- SCN/DC/CSET/Oracle引用是否一致；
- 候选ID是否唯一；
- Oracle答案是否存在于当前候选集合；
- 场景体积率、SKU多样性和多层条件；
- 来源订单是否跨划分泄漏；
- Geometry-OOD和Semantic-OOD是否按定义留出；
- Language-OOD配对是否只有语言不同；
- stream是否在正确episode切换策略；
- 可见文件是否包含禁止元数据；
- 状态哈希是否可重新计算。

启动：

```bash
python3 semantic_pallet_dataset_v1/scripts/validate_dataset.py
```

产出：

```text
statistics/validation_report.json
statistics/generated_checksums.json
```

### 19.3 `validate_geometry_independent.py`：独立物理复核器

不调用`build_dataset.py`中的`evaluate_pose()`，独立复算所有已返回候选：

```text
边界、不重叠、总载荷、支撑率、重心投影、不可堆叠、
传播承重、支撑ID、最大高度和体积率
```

启动：

```bash
python3 semantic_pallet_dataset_v1/scripts/validate_geometry_independent.py
```

产出：

```text
statistics/independent_geometry_report.json
```

### 19.4 `pallet_protocol.py`：VLM候选协议库

这是被其他脚本导入的公共模块，通常不单独启动。

主要函数：

- `state_payload()`：整理要参与状态哈希的字段；
- `state_hash()`：计算当前物理状态SHA-256；
- `public_candidate()`：删除候选内部审计字段，形成VLM可见候选；
- `build_request()`：构造完整VLM请求；
- `resolve_response()`：检查响应版本、请求ID、状态哈希和候选ID。

它禁止VLM自行返回`x_mm/y_mm/z_base/yaw`覆盖本地候选。

### 19.5 `export_vlm_inputs.py`：导出VLM白名单JSON

处理关系：

```text
Decision Case + Scenario.container + CandidateSet
                         ↓ 白名单过滤
              views/vlm_inputs/DC_xxxxx.json
```

启动：

```bash
python3 semantic_pallet_dataset_v1/scripts/export_vlm_inputs.py
```

产出360份VLM请求JSON，但不会生成PNG图片。

### 19.6 `render_decision_cases.py`：固定决策点渲染器

用Matplotlib 3D读取固定Decision Case和CandidateSet，生成：

```text
views/rendered/DC_xxxxx/workspace.png
views/rendered/DC_xxxxx/candidates_montage.png
views/rendered/DC_xxxxx/render_metadata.json
```

启动全部360例：

```bash
python3 semantic_pallet_dataset_v1/scripts/render_decision_cases.py
```

只渲染一个：

```bash
python3 semantic_pallet_dataset_v1/scripts/render_decision_cases.py \
  --case DC_00001
```

只渲染排序后的前10个：

```bash
python3 semantic_pallet_dataset_v1/scripts/render_decision_cases.py \
  --limit 10
```

### 19.7 `run_visual_episode.py`：完整动态运行器

从`tasks/scenarios/SCN_xxxx.json`读取完整任务，从空托盘开始逐箱运行。每次选择后都会更新状态并在线重新生成下一步候选。

当前选择器：

```text
geometry_best_demo
```

它只按几何分数选择，不调用VLM，不使用自然语言和ReMe。

完整运行：

```bash
python3 semantic_pallet_dataset_v1/scripts/run_visual_episode.py \
  --scenario SCN_0001
```

只运行前3步：

```bash
python3 semantic_pallet_dataset_v1/scripts/run_visual_episode.py \
  --scenario SCN_0001 \
  --max-steps 3
```

产出：

```text
runs/DEMO_SCN_0001/episode.json
runs/DEMO_SCN_0001/final_layout.png
runs/DEMO_SCN_0001/step_xxx/五类文件
```

### 19.8 `generate_stage0_report.py`：阶段0验收汇总器

汇总基础验证、独立物理验证、VLM白名单、视觉文件、动态episode和复现结果，并抽取30个视觉检查案例。

启动：

```bash
python3 semantic_pallet_dataset_v1/scripts/generate_stage0_report.py
```

产出：

```text
statistics/stage0_acceptance_report.json
statistics/stage0_acceptance_report.md
statistics/reproducibility_report.json
statistics/visual_audit_manifest.json
views/visual_audit_contact_sheet.png
```

## 20. `tests/test_stage0.py`：自动化回归测试

该文件不是训练代码，而是检查接口修改后是否破坏既有安全行为。

当前7项测试：

| 测试 | 检查内容 |
|---|---|
| `test_public_request_has_no_hidden_labels` | VLM请求不含Oracle、split、来源标签 |
| `test_valid_response_resolves_local_candidate` | 合法candidate_id可以恢复本地候选 |
| `test_stale_state_is_rejected` | 旧state_hash响应被拒绝 |
| `test_unknown_candidate_is_rejected` | 不存在的candidate_id被拒绝 |
| `test_coordinate_override_is_rejected` | VLM不能直接覆盖坐标 |
| `test_strict_candidate_schema_rejects_bad_yaw` | 45°等非法朝向被Schema拒绝 |
| `test_independent_checker_rejects_out_of_bounds` | 独立验证器能发现越界候选 |

运行：

```bash
python3 -m unittest discover \
  -s semantic_pallet_dataset_v1/tests \
  -v
```

通过时显示：

```text
Ran 7 tests
OK
```

测试通过只代表当前检查项没有回归，不代表规划算法性能已经达到论文要求。

## 21. 重要JSON之间如何关联

### 21.1 一个完整场景的关系

以`SCN_0001`为例：

```text
tasks/scenarios/SCN_0001.json
     │
     ├── annotations/ground_truth_rules/SCN_0001.json
     │       └── reference_feasible_plan_id = PLAN_0001
     │
     ├── annotations/reference_feasible_plans/PLAN_0001.json
     │
     ├── tasks/decision_cases/DC_00001.json
     ├── tasks/decision_cases/DC_00002.json
     └── tasks/decision_cases/DC_00003.json
```

基础场景有完整箱体序列，三个Decision Case只是从其参考rollout中截取的三个步骤。

### 21.2 一个Decision Case的完整关系

```text
tasks/decision_cases/DC_00001.json
     │
     ├── base_scenario_id = SCN_0001
     │       └── tasks/scenarios/SCN_0001.json
     │
     ├── candidate_set_id = CSET_00001
     │       ├── candidates/candidate_sets/CSET_00001.json
     │       └── candidates/candidate_audits/CSET_00001.json
     │
     ├── annotations/oracle_candidate_scores/DC_00001.json
     │       └── oracle_candidate_id必须存在于CSET_00001
     │
     └── views/vlm_inputs/DC_00001.json
             └── views/rendered/DC_00001/
```

### 21.3 VLM一次决策如何被评价

```text
VLM读取 views/vlm_inputs/DC_00001.json + 两张PNG
                         ↓
返回 candidate_id
                         ↓
pallet_protocol.resolve_response()确认ID和state_hash
                         ↓
从CSET_00001恢复不可变坐标
                         ↓
评价器读取oracle_candidate_scores/DC_00001.json
                         ↓
计算是否违规、语义得分、与Oracle的regret
```

### 21.4 Language-OOD配对

```text
Test-ID场景SCN_0061
       ↕ 相同base_physical_id/pair_group_id
Language-OOD场景SCN_0101
```

二者箱体、顺序、物理状态和候选相同，只改变自然语言表述和不透明ID。实验比较两者的配对差值，测量语言改写鲁棒性。

### 21.5 固定评测与完整运行的区别

```text
固定评测：DC_00001 → CSET_00001 → 选一个候选 → 立即评分

完整运行：SCN_0001 → 第0步在线生成候选 → 提交选择
                    → 第1步根据新状态重新生成候选 → ……
```

固定评测保证不同模型面对相同题目；完整运行评价误差和策略选择如何累积影响最终布局。两种实验都需要，但指标不能混为一谈。

## 22. 推荐的阅读顺序

第一次理解数据时，按以下顺序打开文件：

1. `tasks/scenarios/SCN_0001.json`：先看完整任务；
2. `annotations/ground_truth_rules/SCN_0001.json`：看隐藏结构化规则和来源；
3. `annotations/reference_feasible_plans/PLAN_0001.json`：看参考规划如何逐步放置；
4. `tasks/decision_cases/DC_00001.json`：看截取出的单步状态；
5. `candidates/candidate_sets/CSET_00001.json`：看本步有哪些合法选项；
6. `candidates/candidate_audits/CSET_00001.json`：看Top-K质量；
7. `annotations/oracle_candidate_scores/DC_00001.json`：看标准答案如何评价每个候选；
8. `views/vlm_inputs/DC_00001.json`：看真正允许发给VLM的内容；
9. `views/rendered/DC_00001/`：把JSON与三维图对应起来；
10. `runs/DEMO_SCN_0001/`：看完整在线运行与固定Decision Case的差异。

## 23. 常用启动命令与产出对照

所有命令从工作区根目录执行：

```bash
cd /home/cyw/NBU_Papper
conda activate pallet_vlm
```

| 命令 | 主要输入 | 主要产出 |
|---|---|---|
| `build_dataset.py --force` | raw数据、config | 核心数据八个目录 |
| `validate_dataset.py` | 核心JSON、schemas | 基础验证报告、校验和 |
| `validate_geometry_independent.py` | DC、Scenario、CSET | 独立物理报告 |
| `export_vlm_inputs.py` | DC、Scenario、CSET | 360份VLM白名单JSON |
| `render_decision_cases.py` | 固定DC和CSET | 720张VLM图片及元数据 |
| `run_visual_episode.py` | 一个完整Scenario | 动态运行轨迹和逐步图片 |
| `generate_stage0_report.py` | 所有验收产物 | 阶段0总报告和抽查图 |
| `unittest discover` | 测试代码和样例数据 | 7项接口回归测试结果 |

### 最小检查

```bash
python3 semantic_pallet_dataset_v1/scripts/validate_dataset.py
python3 semantic_pallet_dataset_v1/scripts/validate_geometry_independent.py
python3 -m unittest discover -s semantic_pallet_dataset_v1/tests -v
```

### 重新导出固定VLM输入和图片

```bash
python3 semantic_pallet_dataset_v1/scripts/export_vlm_inputs.py
python3 semantic_pallet_dataset_v1/scripts/render_decision_cases.py
```

### 体验一个完整在线场景

```bash
python3 semantic_pallet_dataset_v1/scripts/run_visual_episode.py \
  --scenario SCN_0001
```

### 从原始数据完整重建

```bash
python3 semantic_pallet_dataset_v1/scripts/build_dataset.py --force
python3 semantic_pallet_dataset_v1/scripts/validate_dataset.py
python3 semantic_pallet_dataset_v1/scripts/validate_geometry_independent.py
python3 semantic_pallet_dataset_v1/scripts/export_vlm_inputs.py
python3 -m unittest discover -s semantic_pallet_dataset_v1/tests -v
python3 semantic_pallet_dataset_v1/scripts/render_decision_cases.py
python3 semantic_pallet_dataset_v1/scripts/run_visual_episode.py --scenario SCN_0001
python3 semantic_pallet_dataset_v1/scripts/generate_stage0_report.py
```

## 24. 哪些内容可以给模型看

| 目录/字段 | 几何规划器 | VLM | 评价器 | ReMe测试时检索 |
|---|---:|---:|---:|---:|
| `tasks/scenarios`当前可见状态 | 是 | 经适配后是 | 是 | 只用历史/当前摘要 |
| `tasks/decision_cases` | 是 | 经白名单后是 | 是 | 当前状态可用 |
| `candidates/candidate_sets` | 是 | 经白名单后是 | 是 | 当前候选摘要可用 |
| `views/vlm_inputs` | 不需要 | 是 | 可记录 | 可作为当前上下文 |
| `views/rendered` | 可选 | 是 | 可记录 | 通常不直接存图片 |
| `annotations` | 否 | 否 | 是 | 测试决策前禁止 |
| `splits` | 调度器使用 | 否 | 是 | 不进入检索键 |
| `catalog`来源ID | 构建器使用 | 否 | 是 | 否 |
| `runs`过去已完成反馈 | 不直接 | 当前请求前的历史可摘要 | 是 | 可作为经验来源 |

严格在线`buffer_size=1`时，即使`SCN`文件保存完整`arrival_order`，模型也只能看到当前箱体。否则任务会从在线规划变成提前知道未来的离线规划。

## 25. 当前版本已经完成与尚未完成

### 已完成

- 100个基础三维场景和40个配对视图；
- 360个固定Decision Case、CandidateSet和Oracle；
- 多尺寸、多质量、多属性和多层参考方案；
- ID、Geometry-OOD、Semantic-OOD、Language-OOD；
- Stationary/Policy-Shift任务流；
- VLM无泄漏JSON视图和720张三维图片；
- 独立物理复核、复现性验证和接口单元测试；
- 一个16箱几何选择器完整动态运行样例。

### 尚未完成

- 真正VLM API选择器；
- 动态候选顺序随机化后的VLM完整episode；
- VLM-Text、VLM-Visual、规则程序和Oracle正式对比；
- ReMe经验卡片、检索、验证与改写；
- buffer3的`pick_item_id + placement`联合候选；
- GOPT适配和重训基线；
- Gazebo、RGB-D、MoveIt 2和Aubo闭环；
- 论文正式规模V1.0及统计结论。

因此，当前目录的正确定位是：

> 它已经是一套可复现、可验证、能生成VLM输入并运行几何演示的阶段0实验底座，但还不是VLM+ReMe算法实验的最终结果。
