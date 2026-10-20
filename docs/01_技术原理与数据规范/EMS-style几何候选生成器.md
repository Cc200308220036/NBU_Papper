# EMS-style几何候选生成器：实现、数据逻辑、GOPT对照与VLM接口

> 文档对象：`semantic_pallet_planner`阶段1A—1B实现及`GOPT-main`参考源码  
> 当前范围：真值状态、`buffer_size=1`、0°/90°放置、Top-K候选、确定性状态更新  
> 后续用途：阶段1C的VLM候选选择器、阶段1E的ReMe经验记忆，以及最终Gazebo/机器人验证

## 1. 结论与准确命名

当前项目中的候选生成器不是从GOPT源码直接复制或移植出来的。它的实现来源是：

```text
semantic_pallet_dataset_v1/scripts/build_dataset.py
                         ↓ 抽取、模块化、独立复核
semantic_pallet_planner/src/semantic_pallet_planner/planner/
```

代码来源记录在：

```text
semantic_pallet_planner/configs/extraction_provenance.json
```

其中明确记录：

```json
{
  "source": "semantic_pallet_dataset_v1/scripts/build_dataset.py"
}
```

GOPT在当前阶段的作用是：

1. 提供3D-BPP中EMS候选空间、候选动作和策略网络的参考；
2. 用小型空容器、单箱上层案例检查基础空间覆盖；
3. 为后续实现学习型GOPT基线提供源码依据。

当前方法的准确名称应为：

> 基于极值点和支撑层的GOPT-inspired EMS-style几何候选生成器。

不应写成“从GOPT提取的规划器”“完整GOPT复现”或“GOPT训练模型”。当前实现没有使用GOPT训练权重，也没有把GOPT环境作为正式运行依赖。

还需要特别说明：GOPT的EMS是一个真实的六维最大空闲空间：

```text
[x_min, y_min, z_min, x_max, y_max, z_max]
```

当前实现直接生成候选箱体的极值点位姿：

```text
(x0, y0, z0, yaw)
```

当前Candidate中的`ems_id`和`ems_type`用于标识候选来自地面空间还是支撑空间，并不表示已经计算了完整六维最大空闲长方体。因此称为“EMS-style”比“EMS算法复现”准确。

## 2. 系统总体架构

当前在线规划链路如下：

```text
Scenario JSON
  │ container / items / arrival_order / instruction
  ▼
PalletEnvironment.reset()
  │ 只暴露当前到货箱体，buffer_size=1
  ▼
PalletState
  │ container + placed_items + available_items
  ▼
ExtremePointGenerator.generate()
  ├─ candidate_points()：枚举极值点和支撑层
  ├─ evaluate_pose()：硬约束过滤和几何特征计算
  ├─ pareto_front()：计算非支配候选
  └─ select_diverse_topk()：返回多样性Top-K
  ▼
CandidateSet
  │ 候选ID、位姿、支撑、承重余量和几何特征
  ▼
build_request()
  │ 生成传统Selector或VLM共用的公开请求
  ▼
Selector
  │ lowest / geometry_greedy / pareto_greedy / VLM
  ▼
SelectorResponse：只返回candidate_id
  ▼
resolve_response() + independent check_candidate()
  │ 协议校验 + 独立物理复核
  ▼
apply_candidate()
  │ 更新摆放状态和向下传播载荷
  ▼
下一步重新生成候选，直到完成或无可行候选
```

系统将“产生合法坐标”和“从合法坐标中决策”分成两个模块：

| 模块 | 职责 | 是否产生坐标 |
|---|---|---:|
| `ExtremePointGenerator` | 枚举并过滤可行放置位置 | 是 |
| `lowest` | 从Top-K中选择最低位置 | 否 |
| `geometry_greedy` | 从Top-K中选择几何分最高的位置 | 否 |
| `pareto_greedy` | 从Top-K的Pareto前沿中选择 | 否 |
| 后续VLM Selector | 根据业务规则和视觉信息选择候选ID | 否 |
| `PalletEnvironment` | 校验响应、提交位姿和更新状态 | 否 |

这种分工使VLM不承担连续三维坐标生成，也不承担碰撞、支撑和承重计算。VLM只处理高层语义决策。

## 3. 坐标体系与核心数据对象

### 3.1 容器坐标系

当前数据集采用：

```text
coordinate_frame = container_bottom_center
```

容器默认尺寸为：

```text
length = 1200 mm
width  = 1000 mm
height = 850 mm
```

坐标范围为：

```text
x ∈ [-600, 600]
y ∈ [-500, 500]
z ∈ [0, 850]
```

公开JSON中的位姿含义为：

```json
{
  "pose": {
    "x_mm": 402.5,
    "y_mm": -305.0,
    "z_base_mm": 170.0,
    "yaw_deg": 90
  }
}
```

- `x_mm`：箱体底面中心的X坐标；
- `y_mm`：箱体底面中心的Y坐标；
- `z_base_mm`：箱体底面相对容器底面的高度；
- `yaw_deg`：绕Z轴旋转角度，当前仅为0°或90°。

内部几何计算使用箱体边界：

```text
x0 = x_center - length/2
x1 = x_center + length/2
y0 = y_center - width/2
y1 = y_center + width/2
z0 = z_base
z1 = z_base + height
```

### 3.2 领域对象

`domain.py`使用不可变JSON快照包装各类数据：

| 对象 | 含义 | 主要字段 |
|---|---|---|
| `PalletState` | 当前规划状态 | container、placed_items、available_items、step_index |
| `Candidate` | 单个候选动作 | candidate_id、pose、support、load、geometry features |
| `CandidateSet` | 当前Top-K候选集合 | physical_state_hash、candidates、generator |
| `SelectionRequest` | 选择器公开输入 | state、instruction、candidates、visual_inputs |
| `SelectorResponse` | 选择器输出 | request_id、state_hash、candidate_id |
| `StepResult` | 环境提交结果 | before、after、candidate、error、done |

这些对象在边界处都返回深拷贝，避免Selector意外修改环境状态。

### 3.3 内部状态恢复

公开数据中的支撑比例和负载经过JSON小数化。在线生成前，`restore_placed()`根据位姿重新计算：

1. 每个箱体的精确AABB；
2. 与同高度支撑箱的重叠面积；
3. 支撑质量比例；
4. 从当前箱体一直传播到最底层的累计负载。

对应代码：

```text
semantic_pallet_planner/src/semantic_pallet_planner/domain.py
```

这样可以避免多步规划反复使用四舍五入后的负载数据而积累误差。

## 4. 当前项目模块的输入与输出

### 4.1 `ExtremePointGenerator`

文件：

```text
semantic_pallet_planner/src/semantic_pallet_planner/planner/generator.py
```

接口：

```python
class CandidateGenerator(Protocol):
    def generate(self, state: PalletState) -> CandidateGenerationResult:
        ...
```

输入`PalletState`：

```json
{
  "container": {},
  "placed_items": [],
  "available_items": [{}],
  "step_index": 0,
  "request_id": "SCN_0051_STEP_000",
  "instruction_text": "易碎箱应尽量不承载其他箱体……"
}
```

当前实现要求：

```python
len(state["available_items"]) == 1
```

也就是阶段1A—1B只实现严格在线`buffer_size=1`。候选生成器不读取未来到货箱体，也不读取隐藏规则和Oracle。

输出`CandidateGenerationResult`包含三部分：

```text
candidate_set：返回给Selector的Top-K候选
audit：候选漏斗、拒绝原因和覆盖率
timing：枚举、过滤、评分和Top-K耗时
```

### 4.2 `candidate_points()`

文件：

```text
semantic_pallet_planner/src/semantic_pallet_planner/planner/constraints.py
```

输入：

```text
placed：已放箱体的内部AABB记录
box_l：当前旋转姿态下的长度
box_w：当前旋转姿态下的宽度
container：容器尺寸
```

输出：

```text
List[(x0, y0, z0)]
```

这里的`x0、y0`是新箱体底面左下角，不是公开JSON中的中心坐标。

高度层来自：

```python
z_levels = {0.0} | {p["z1"] for p in placed}
```

即：

- `z=0`：容器底面；
- `z=已放箱体顶面`：支撑层。

地面层的X/Y来源包括：

```text
容器最小边界
容器最大边界减去新箱尺寸
已放箱体的右/前边缘
已放箱体的左/后边缘减去新箱尺寸
```

上层还会增加：

```text
支撑箱体左边对齐
支撑箱体右边对齐
支撑箱体前边对齐
支撑箱体后边对齐
```

算法会组合所有X和Y边界，因此能产生贴容器边、贴已有箱、与支撑箱对齐以及跨多个支撑箱的候选。

### 4.3 旋转枚举

`generator.py`根据配置枚举：

```json
"yaw_degrees": [0, 90]
```

尺寸转换为：

```text
yaw=0°  → oriented_size = [length, width, height]
yaw=90° → oriented_size = [width, length, height]
```

每个候选以`(x0, y0, z0, yaw)`去重。

### 4.4 `evaluate_pose()`

输入：

```text
当前箱体item
全部已放箱体placed
候选左下角x0/y0/z0
旋转后的box_l/box_w
yaw
候选生成配置
```

输出有两种：

```python
(candidate, None)       # 合法候选
(None, rejection_code) # 非法候选
```

合法候选的内部结果包括：

```text
visible：可公开给Selector/VLM的信息
geometry_score：生成器内部总分
stratum：多样性Top-K分层标签
record：提交状态所需的内部AABB
load_increments：各层支撑箱新增负载
result_state：候选提交后的内部状态
```

只有`visible`部分进入公开CandidateSet。

## 5. 物理硬约束及对应代码

所有候选必须依次通过以下物理规则。这些规则由规划器执行，不交给VLM判断。

| 硬约束 | 判定逻辑 | 拒绝码 | 生成期代码 |
|---|---|---|---|
| 容器边界 | AABB必须完全位于X/Y边界内，`z1≤max_height` | `out_of_bounds` | `constraints.py/evaluate_pose()` |
| 容器总载荷 | 已放总质量+当前质量≤`max_payload_kg` | `over_payload` | `constraints.py/evaluate_pose()` |
| 三维无碰撞 | X、Y、Z三个区间同时有正重叠即碰撞 | `overlap` | `boxes_overlap_3d()` |
| 支撑面积 | 上层箱底面被同高度箱体覆盖的并集比例≥0.70 | `insufficient_support` | `rectangle_union_area()`、`evaluate_pose()` |
| 重心投影 | 新箱底面中心必须落在至少一个有效支撑矩形内 | `com_outside_support` | `evaluate_pose()` |
| 可堆叠性 | 任一直接支撑箱`stackable=false`时拒绝 | `non_stackable_support` | `evaluate_pose()` |
| 传播承重 | 新箱质量按接触面积比例向下递归传播 | `overload` | `propagate_load()` |
| 旋转合法性 | 当前只允许0°和90° | `invalid_yaw`（独立复核） | `geometry_oracle.py/check_candidate()` |
| 箱体尺寸一致 | yaw与`oriented_size_mm`必须匹配 | `oriented_size_mismatch` | `geometry_oracle.py/check_candidate()` |

### 5.1 边界与碰撞

容器采用底面中心原点：

```text
xmin = -length/2
xmax =  length/2
ymin = -width/2
ymax =  width/2
```

候选满足：

```text
x0 ≥ xmin, x1 ≤ xmax
y0 ≥ ymin, y1 ≤ ymax
z0 ≥ 0,    z1 ≤ max_height
```

碰撞判定使用连续AABB。只有在X、Y和Z方向都有正重叠时才算三维碰撞；边界恰好接触不算重叠。

### 5.2 支撑面积

对于`z_base>0`的候选：

1. 找出顶面高度等于`z_base`的已放箱体；
2. 计算它们与新箱底面的矩形交集；
3. 计算所有交集矩形的并集面积；
4. 除以新箱底面积得到`support_ratio`。

公式为：

```text
support_ratio = union(support rectangles) / candidate bottom area
```

当前阈值：

```text
support_ratio_min = 0.70
```

地面候选的支撑率固定为1.0。

### 5.3 重心投影

当前实现使用新箱几何中心：

```text
cx = x0 + box_l/2
cy = y0 + box_w/2
```

该点必须落入至少一个直接支撑重叠矩形。当前实现不是一般的“所有支撑点凸包”判定，因此比某些凸包稳定性判据更保守。跨越两个支撑箱但中心位于两者间隙的候选会被拒绝。

### 5.4 质量传播与顶部承重

若新箱由多个箱体支撑，新箱质量按接触面积比例分配：

```text
fraction_i = overlap_area_i / sum(overlap_area)
load_i = new_item_mass × fraction_i
```

每一份载荷继续沿支撑关系递归向下传播。任一下层箱体满足：

```text
supported_load_kg + new_increment
    > top_load_limit_kg_synthetic
```

则候选被拒绝。

这里的`top_load_limit_kg_synthetic`是数据集构造的合成属性，不是真实纸箱抗压试验值。Gazebo和实体实验前需要用更可信的材料/包装参数替换或标定。

### 5.5 当前公开负载字段的边界

公开Candidate包含：

```json
"load": {
  "downward_load_kg": 0.0,
  "minimum_remaining_capacity_kg": 12.5
}
```

当前`minimum_remaining_capacity_kg`有实际计算意义；`downward_load_kg`在现版本中仍固定为0.0。后续若要让VLM理解“这个位置会给下层增加多少压力”，应将真实的传播增量摘要写入该字段，并同步更新Schema和测试。

## 6. 几何特征与评分

每个合法候选会计算四个归一化分项：

| 分项 | 公式或含义 | 趋势 |
|---|---|---|
| `compactness` | 已放总体积/当前三维包络体积 | 越大越好 |
| `height` | `1 - max_z/container_height` | 越大表示总体越低 |
| `stability` | 当前候选支撑率 | 越大越稳定 |
| `balance` | `1 - COM_offset/max_possible_offset` | 越大越居中 |

固定权重为：

```text
geometry_score = 0.35 × compactness
               + 0.25 × height
               + 0.25 × stability
               + 0.15 × balance
```

配置来自：

```text
semantic_pallet_dataset_v1/configs/mvd_v0.1.json
```

运行期Selector使用同一公式，代码在：

```text
semantic_pallet_planner/src/semantic_pallet_planner/planner/scoring.py
```

`height`是一个“低高度得分”，不是毫米高度。`resulting_geometry.max_height_mm`才是实际放置后的最高高度。

## 7. Pareto前沿与多样性Top-K

### 7.1 Pareto前沿

若候选B在四个几何分项上都不差于候选A，并且至少一个分项严格更好，则A被B支配。

```text
B dominates A ⇔
∀k: B[k] ≥ A[k]
且 ∃k: B[k] > A[k]
```

未被任何其他候选支配的集合构成Pareto前沿。

### 7.2 多样性分层

每个候选首先具有以下分层标签：

```text
floor / upper
center / edge
直接支撑箱数量（截断到2）
item_id
```

`diverse_v1`还增加：

```text
yaw=0 / yaw=90
是否属于Pareto前沿
```

### 7.3 Top-K选择

候选先按：

```text
geometry_score降序
candidate_id升序稳定打破平局
```

然后：

1. 每个分层保留一个最高分候选；
2. 按几何分选择最多K个分层代表；
3. 若不足K个，用剩余高分候选补齐。

当前冻结值：

```text
K = 16
```

多样性Top-K的目的不是让所有候选都接近Geometry-Greedy，而是同时保留低层、上层、边缘、中心、不同旋转和不同几何权衡，给VLM留下语义选择空间。

## 8. CandidateSet的公开输出

候选生成器返回的Candidate示例：

```json
{
  "display_label": "C01",
  "candidate_id": "cand_af7d63c2870a",
  "pick_item_id": "item_02",
  "pose": {
    "x_mm": -85.0,
    "y_mm": -300.0,
    "z_base_mm": 0.0,
    "yaw_deg": 90
  },
  "oriented_size_mm": [290, 400, 230],
  "support": {
    "support_item_ids": [],
    "support_ratio": 1.0,
    "com_margin_mm": 145.0
  },
  "load": {
    "downward_load_kg": 0.0,
    "minimum_remaining_capacity_kg": null
  },
  "resulting_geometry": {
    "max_height_mm": 260.0,
    "volume_utilization": 0.063322,
    "center_of_mass_offset_mm": 350.628
  },
  "geometry_score_components": {
    "compactness": 0.748239,
    "height": 0.694118,
    "stability": 1.0,
    "balance": 0.551067
  }
}
```

公开Candidate不包含：

- 生成器内部的`result_state`；
- 私有`load_increments`；
- Oracle候选ID；
- 规则评分结果；
- 候选选择后的反馈；
- 未来到货箱体。

`candidate_id`由箱体ID、`x0/y0/z0`和yaw的稳定指纹生成。同一状态、同一位姿会产生稳定ID。

### 8.1 候选生成审计输出

`audit`至少记录：

```text
raw_candidate_count
physical_valid_count
duplicate_count
pareto_candidate_count
returned_count
rejection_histogram
pareto_recall_at_k
geometry_oracle_score
epsilon_optimal_recall_at_k
strata_count
returned_strata_count
```

这些字段用于判断候选生成器是否因为Top-K过小而丢失关键几何候选，而不是给VLM作为答案标签。

## 9. 独立物理复核与状态提交

生成期合法并不意味着环境直接信任候选。`PalletEnvironment.step()`在提交动作前会调用独立检查器：

```text
semantic_pallet_planner/src/semantic_pallet_planner/evaluation/geometry_oracle.py
```

独立检查器不导入`planner/constraints.py`，会重新计算：

- yaw和旋转尺寸是否一致；
- AABB是否越界；
- 是否碰撞；
- 容器总载荷；
- 支撑面积；
- 重心投影；
- 不可堆叠约束；
- 递归承重；
- Candidate报告的支撑箱ID和支撑率是否正确；
- 放置后最大高度和容积率是否正确。

这形成两道防线：

```text
第一道：constraints.py负责生成与过滤
第二道：geometry_oracle.py负责独立复核
```

若独立复核失败，环境将该步标为`internal_error`，不会提交非法位姿。

状态提交由：

```text
semantic_pallet_planner/src/semantic_pallet_planner/evaluation/state.py
```

中的`apply_candidate()`完成。它根据公开候选重新计算支撑关系和负载传播，不直接使用生成器私有的`result_state`。因此候选生成、状态提交和结果复核不会共享同一份私有中间结果。

需要注意：独立检查器当前将0.70直接写在代码中，而生成器从配置读取`support_ratio_min`。当前两者一致；如果后续调整支撑阈值，必须同时改为共享的冻结配置或在检查器初始化时显式传入，防止生成与验收不一致。

## 10. 三种传统Selector如何使用Top-K

文件：

```text
semantic_pallet_planner/src/semantic_pallet_planner/selectors/baselines.py
```

三种方法面对相同的公开Top-K，不生成新坐标。

### 10.1 Lowest

排序键：

```text
z_base_mm升序
resulting max height升序
center of mass offset升序
candidate_id升序
```

它表示“尽量先放低处”的简单启发式。

### 10.2 Geometry-Greedy

选择`geometry_score`最高的候选，综合考虑紧凑、低高度、支撑和平衡。

### 10.3 Pareto-Greedy

它在“已经返回的Top-K内部”重新计算Pareto前沿，然后按以下字典序选择：

```text
height得分降序
stability降序
balance降序
compactness降序
candidate_id升序
```

它不访问生成器未返回的原始候选。因此所有普通Selector的候选预算相同。

### 10.4 Selector统一输出

```json
{
  "schema_version": "pallet_selector_response_v1",
  "request_id": "SCN_0051_STEP_000",
  "state_hash": "...",
  "candidate_id": "cand_489240afb82d",
  "confidence": null,
  "reason": "geometry_greedy"
}
```

环境通过`candidate_id`恢复规划器已经计算好的位姿。Selector不能增加`x_mm`、`y_mm`或`z_base_mm`等字段。

## 11. GOPT源码的实现逻辑

GOPT参考代码主要涉及：

```text
GOPT-main/envs/Packing/ems.py
GOPT-main/envs/Packing/container.py
GOPT-main/envs/Packing/env.py
GOPT-main/model.py
```

### 11.1 GOPT的高度图表示

`Container`创建整数高度图：

```python
self.heightmap = np.zeros(shape=(length, width), dtype=np.int32)
```

高度图每个栅格保存该X/Y位置当前的顶部高度。放置箱体后，箱体覆盖区域被更新为新的顶面高度。

输入：

```text
container_size = (L, W, H)
heightmap      = shape(L, W)
next_box       = [length, width, height]
```

这种表示适合整数、小尺寸和规则正交箱体；当前项目使用真实毫米尺寸，不建立`1200×1000`的稠密整数高度图。

### 11.2 `compute_corners()`

文件：

```text
GOPT-main/envs/Packing/ems.py
```

输入：二维高度图。

处理：

1. 在高度图周围填充大值；
2. 计算X/Y相邻栅格高度差；
3. 找出高度变化处的角点；
4. 区分普通角点和左下角点；
5. 返回X/Y边界集合。

输出包括：

```text
corners
left_bottom_corners
x_borders
y_borders
```

### 11.3 `compute_stair_corners()`

该函数在高度图中寻找阶梯形结构产生的额外角点，补充普通边缘差分可能遗漏的空间起点。

### 11.4 `compute_empty_space()`

给定某个角点和高度`h`，函数向允许的X/Y方向扩展，检查对应高度层是否可以形成空闲区域，最终构造：

```python
new_ems = [x_small, y_small, h, x_large, y_large, container_h]
```

它会：

- 删除宽或长为0的空间；
- 按`min_ems_width`过滤过小空间；
- 删除重复EMS。

### 11.5 `compute_ems()`

`compute_ems()`依次使用：

```text
左下角
普通角点
阶梯角点
```

生成一组最大空闲空间。其输出是六维EMS列表：

```text
[x_min, y_min, z_min, x_max, y_max, container_height]
```

### 11.6 `Container.candidate_from_EMS()`

输入：

```text
next_box：下一箱尺寸
max_n：最多保留的EMS数量
```

处理：

1. 根据当前高度图计算全部EMS；
2. 按`z、y、x`升序排序；
3. 截断为前`max_n`个；
4. 对原姿态和旋转姿态分别调用`check_box_ems()`；
5. 生成形状为`(2, max_n)`的合法动作mask。

输出：

```text
candidates：EMS数组
mask：原姿态/旋转姿态的合法性
```

GOPT在截断后再构造合法mask。当前项目先完成物理合法性过滤和几何评分，再进行多样性Top-K，两个流程并不等价。

### 11.7 GOPT的稳定性判断

`Container.check_box()`和`is_stable()`执行：

- XY边界检查；
- 通过覆盖高度图最大值确定`pos_z`；
- Z高度检查；
- 支撑稳定性判断。

GOPT默认稳定性逻辑为：

1. 地面箱体直接合法；
2. 支撑面积超过底面积50%时直接合法；
3. 支撑点较少时检查箱体中心是否在线段上；
4. 支撑点较多时构造凸包，检查箱体中心是否位于凸包内。

当前项目采用“支撑面积≥70%且中心落入至少一个有效支撑矩形”，还增加质量、承重传播和不可堆叠规则，因此不能直接复用GOPT的合法性mask。

### 11.8 `PackingEnv`

文件：

```text
GOPT-main/envs/Packing/env.py
```

环境的公开逻辑为：

```text
next_box
  ↓
get_possible_position()
  ↓
heightmap / EP / EMS / FC候选
  ↓
observation + action mask
  ↓
策略输出离散action index
  ↓
idx2pos()
  ↓
Container.place_box()
```

EMS模式观测包含：

```text
flattened heightmap
next box原姿态和旋转姿态尺寸
k个六维EMS候选
```

动作是候选索引，而不是直接输出连续坐标。这一点与当前项目让VLM输出`candidate_id`的思路一致。

### 11.9 GOPT模型

`model.py`包含：

| 模块 | 作用 |
|---|---|
| `item_encoder` | 编码当前箱体两种朝向 |
| `placement_encoder` | 编码三维点或六维EMS |
| `EncoderBlock` | 物料自注意力、EMS自注意力及双向交叉注意力 |
| `ActorHead` | 计算物料与候选之间的动作logits |
| `CriticHead` | 估计当前状态价值 |

EMS模式下：

```text
item feature shape      = (batch, 2, 3)
placement feature shape = (batch, K, 6)
actor output            = candidate action logits
```

当前项目尚未训练或加载这一网络。若后续加入“完整GOPT学习型基线”，需要重新定义与当前毫米尺度、质量属性和Candidate协议一致的观测、mask、动作及奖励，并在相同候选预算下训练。

## 12. 当前实现与GOPT的对照

| 项目 | GOPT源码 | 当前EMS-style生成器 |
|---|---|---|
| 正式实现来源 | GOPT仓库 | 阶段0`build_dataset.py`抽取 |
| 空间表示 | 整数栅格高度图 | 连续毫米AABB列表 |
| 坐标原点 | 容器角点 | 容器底面中心 |
| 候选主体 | 六维EMS或三维EP | `(x0,y0,z0,yaw)`候选位姿 |
| Z来源 | 高度图局部最大值/EMS底面 | 地面和已放箱体顶面 |
| 旋转 | 原姿态/交换长宽 | yaw=0°/90° |
| 支撑 | >50%或中心在支撑凸包 | ≥70%且中心在支撑矩形 |
| 质量 | 不进入当前EMS合法性 | 容器载荷+逐层传播承重 |
| 不可堆叠 | 无当前属性逻辑 | `stackable=false`硬约束 |
| 候选截断 | z/y/x排序后截断 | 合法性+几何评分+多样性Top-K |
| 决策输出 | 离散候选索引 | 稳定`candidate_id` |
| 学习模型 | Actor-Critic/注意力 | 当前阶段无学习模型 |
| 语义规则 | 未覆盖当前业务属性 | 留给VLM/规则Selector |

因此，两者共享“先生成有限候选，再由高层策略选择”的总体结构，但状态表示、物理约束和候选截断方式不同。

## 13. 固定Decision Case与在线Episode的数据逻辑

### 13.1 固定Decision Case

```text
DC JSON + 冻结CSET JSON
        ↓
所有方法面对完全相同的Top-K
        ↓
各自选择candidate_id
        ↓
动作后读取Oracle并评价
```

固定案例不提交下一步状态，适合：

- 比较VLM、传统方法和Oracle的单步选择；
- 做配对统计；
- 控制候选集合完全相同；
- 调试提示词和响应协议。

### 13.2 在线Episode

```text
reset Scenario
  ↓
按arrival_order取得当前箱体
  ↓
基于实际当前状态在线生成Top-K
  ↓
Selector选择并提交
  ↓
状态改变，下一步重新生成候选
```

不同方法第一步选择不同后，第二步起候选集合可能完全不同。在线实验评价的是“连续决策形成的整条轨迹”，不是相同CSET上的单步准确率。

### 13.3 无可行候选

若生成器返回空集合：

```text
termination_reason = no_feasible_candidate
```

环境不会要求VLM凭空生成新坐标。后续若研究“候选恢复”，应独立定义旋转扩展、缓冲换箱、允许重排或回溯搜索，而不能让VLM绕过物理接口。

## 14. 后期如何配合VLM

### 14.1 VLM在系统中的角色

VLM定位为高层候选决策器：

```text
EMS-style生成器：负责“哪些位置物理可行”
VLM Selector：负责“哪些可行位置更符合业务语义”
Environment：负责“响应是否有效，以及如何提交状态”
Evaluator：负责“动作后语义与几何评价”
```

VLM不承担：

- 连续坐标生成；
- 碰撞检测；
- 支撑面积计算；
- 承重传播；
- MoveIt轨迹规划；
- 机械臂可达性和抓取规划。

阶段1C首先在固定Decision Case上验证VLM能否根据自然语言规则选择正确候选；阶段1D再运行完整在线episode；阶段1E再加入ReMe记忆。

### 14.2 给VLM的结构化内容

`protocol.py/build_request()`构造：

```json
{
  "schema_version": "pallet_vlm_request_v1",
  "request_id": "DC_00001",
  "state_hash": "848195...",
  "instruction_text": "电子产品箱不得与重物箱直接接触或形成上下支撑关系。",
  "container": {
    "length_mm": 1200,
    "width_mm": 1000,
    "max_height_mm": 850,
    "max_payload_kg": 1000
  },
  "placed_items": [],
  "available_items": [],
  "candidates": [],
  "visual_inputs": {
    "workspace_image": ".../workspace.png",
    "candidate_montage": ".../candidates_montage.png"
  }
}
```

具体可见信息包括：

| 输入 | VLM用途 |
|---|---|
| `instruction_text` | 理解易碎、重物、电子产品、分区和优先级规则 |
| `container` | 理解整体空间尺度和高度限制 |
| `placed_items` | 识别已放箱体的位置、类别、质量和支撑关系 |
| `available_items` | 识别当前箱体尺寸、质量和语义属性 |
| `candidate.pose` | 理解每个候选位置和旋转 |
| `candidate.support` | 判断候选会由哪些箱体支撑、支撑是否充足 |
| `candidate.load` | 判断下层剩余承重；当前字段仍需增强 |
| `resulting_geometry` | 理解最大高度、容积率和质心偏移 |
| `geometry_score_components` | 在语义近似时保留几何质量 |
| `workspace_image` | 观察当前取料区和托盘状态 |
| `candidate_montage` | 将C01…CK与候选JSON对应起来 |

### 14.3 决策前视觉输入

在线视觉输入由：

```text
semantic_pallet_planner/src/semantic_pallet_planner/visualization/renderer.py
```

中的`prepare_visual_request()`按需生成：

```text
workspace.png
candidates_montage.png
```

该函数只接收公开request，不接收：

- 已选候选ID；
- Oracle；
- 动作后语义反馈；
- 后续到货物料。

正式VLM输入必须使用这些“决策前”图像，不能使用`frame_selected.png`或最终布局作为同一步输入。

### 14.4 VLM禁止看到的内容

普通VLM请求中禁止出现：

```text
oracle_candidate_id
candidate_evaluations
ground_truth_rule
semantic_decision_required
split
source_order_id
未来到货物料
动作后的违规反馈
```

规则真值和Oracle只能在VLM提交选择后，由Evaluator读取并计算指标。

### 14.5 VLM输出协议

VLM必须返回严格JSON：

```json
{
  "schema_version": "pallet_selector_response_v1",
  "request_id": "DC_00001",
  "state_hash": "848195...",
  "candidate_id": "cand_782d1d4569cb",
  "confidence": 0.82,
  "reason": "避免电子产品箱与重物箱直接接触，并保持较低高度"
}
```

允许字段只有：

```text
schema_version
request_id
state_hash
candidate_id
confidence
reason
```

`resolve_response()`会拒绝：

- 过期或错误的`request_id`；
- 与当前状态不一致的`state_hash`；
- 不属于当前Top-K的`candidate_id`；
- `x/y/z/yaw`等坐标覆盖字段；
- 任意未列入白名单的附加字段。

因此即使VLM产生幻觉，也不能把未经规划器验证的新坐标直接写入环境。

### 14.6 VLM Selector接口

后续Selector应实现：

```python
class VLMSelector:
    name = "vlm"
    privileged_input = False
    future_visible = False
    requires_images = True

    def select(self, request, *, rng, memories=None):
        # 1. 将request和图片传给VLM
        # 2. 解析严格JSON
        # 3. 返回SelectorResponse
        ...
```

它可以通过`register(name, factory)`加入现有Selector注册表，无需修改候选生成器、环境和评价器。

### 14.7 建议的提示词职责

VLM提示词应要求按以下顺序决策：

1. 只在给定候选中选择；
2. 优先满足自然语言硬规则；
3. 在硬规则都满足时比较语义软偏好；
4. 语义效果接近时优先保持几何质量；
5. 只输出协议JSON。

一个简化决策准则可以写为：

```text
第一优先级：语义硬违规数量最少
第二优先级：语义软效用最高
第三优先级：几何分项整体合理
第四优先级：candidate_id稳定打破平局
```

不要要求VLM自行验证碰撞和70%支撑率，因为候选已经通过规划器硬过滤；VLM可以使用支撑和承重摘要理解语义后果。

### 14.8 非法响应与fallback

环境支持两种策略：

```text
fallback_policy = geometry_greedy
fallback_policy = abort
```

- `geometry_greedy`：VLM响应无效时用几何贪心继续运行，并记录`fallback=true`；
- `abort`：终止episode并记录`invalid_selector_response`。

正式论文实验应报告：

```text
response_valid_rate
fallback_count
invalid_json_count
unknown_candidate_count
stale_state_count
```

不能将fallback后的成功结果当作VLM独立成功。

## 15. 后续ReMe如何接入

现有Selector接口已经预留：

```python
select(request, rng=rng, memories=None)
```

VLM+ReMe流程可以设计为：

```text
当前request
  ↓
根据指令、物料属性、候选摘要构造检索query
  ↓
ReMe检索历史经验卡
  ↓
经验摘要加入VLM上下文
  ↓
VLM选择candidate_id
  ↓
动作后计算几何和语义结果
  ↓
成功经验沉淀 / 失败经验重写 / 冲突经验降权
```

经验卡建议记录：

```json
{
  "memory_id": "MEM_xxx",
  "trigger": {
    "instruction_family": "fragile_top",
    "item_attributes": ["fragile", "light"],
    "state_pattern": "heavy_base_available"
  },
  "procedure": [
    "先排除会让易碎箱直接承重的候选",
    "优先选择上层且支撑率充足的位置",
    "若多个候选等价，选择质心偏移较小者"
  ],
  "evidence": {
    "scenario_id": "SCN_xxxx",
    "step_index": 4,
    "candidate_id": "cand_xxx",
    "outcome": "success"
  },
  "confidence": 0.78
}
```

经验中可以保存候选特征模式，不能把某个局部`candidate_id`当作跨场景通用规则，因为candidate ID只对应特定状态和位姿。

## 16. 面向Gazebo和机器人验证的接口延伸

当前候选的`pose`处于容器底面中心坐标系。进入Gazebo/MoveIt 2前需要新增坐标变换：

```text
container frame candidate pose
        ↓ TF/标定
Gazebo world / robot base frame
        ↓
箱体目标中心或吸盘工具目标位姿
        ↓
MoveIt 2可达性、碰撞和轨迹规划
```

机器人阶段还需增加以下过滤器：

| 过滤器 | 当前是否实现 | 后续责任模块 |
|---|---:|---|
| 码垛几何边界 | 已实现 | EMS-style规划器 |
| 箱体间碰撞 | 已实现 | EMS-style规划器+PlanningScene |
| 静态支撑与承重 | 已实现简化模型 | 规划器/Gazebo验证 |
| 机械臂IK可达性 | 未实现 | MoveIt 2 |
| 进场/退场轨迹 | 未实现 | MoveIt 2 |
| 吸盘接触面可抓取性 | 未实现 | 抓取规划器 |
| RGB-D尺寸与位姿不确定性 | 未实现 | 感知模块 |
| 放置误差安全裕量 | 未实现 | 候选生成器/执行层 |

最终机器人接口可以继续使用`candidate_id`，但Candidate需要扩展：

```text
robot_reachable
approach_pose
retreat_pose
grasp_face
clearance_mm
perception_uncertainty_mm
execution_status
```

这些字段属于执行可行性，不应与当前几何评分含混在一起。

## 17. 模块输入输出总表

| 模块/函数 | 输入 | 输出 | 是否读取语义规则 |
|---|---|---|---:|
| `PalletEnvironment.reset` | scenario_id | 初始PalletState | 否 |
| `candidate_points` | placed、箱体长宽、container | `(x0,y0,z0)`列表 | 否 |
| `evaluate_pose` | item、placed、pose、config | 合法Candidate或拒绝码 | 否 |
| `pareto_front` | 全部合法候选 | 非支配候选集合 | 否 |
| `select_diverse_topk` | 合法候选、K | Top-K候选 | 否 |
| `ExtremePointGenerator.generate` | PalletState | CandidateSet+audit+timing | 否 |
| `build_request` | state、CandidateSet、图片路径 | 公开SelectionRequest | 只携带自然语言指令 |
| `lowest` | 公开Top-K | candidate_id响应 | 否 |
| `geometry_greedy` | 公开Top-K | candidate_id响应 | 否 |
| `pareto_greedy` | 公开Top-K | candidate_id响应 | 否 |
| 后续`VLMSelector` | 公开request、决策前图片、可选记忆 | candidate_id响应 | 读取公开自然语言指令 |
| `resolve_response` | request、response | 当前Top-K中的Candidate | 否 |
| `check_candidate` | 当前state、scenario、Candidate | 物理错误列表 | 否 |
| `apply_candidate` | state、Candidate | 新placed_items | 否 |
| `semantic_evaluation` | 动作后状态、隐藏规则 | 软效用和违规 | 是，且只能动作后使用 |

## 18. 代码文件导航

### 当前项目

| 文件 | 主要职责 |
|---|---|
| `planner/generator.py` | 候选生成总控、audit和timing |
| `planner/constraints.py` | 极值点、物理过滤、几何特征、Pareto和Top-K |
| `planner/scoring.py` | Selector使用的冻结几何总分和Pareto计算 |
| `domain.py` | 不可变数据对象与内部状态恢复 |
| `protocol.py` | 状态哈希、公开请求、严格响应解析 |
| `environment.py` | 在线reset/generate/step状态机 |
| `selectors/baselines.py` | traditional selectors和扩展注册表 |
| `evaluation/geometry_oracle.py` | 与生成器独立的物理复核 |
| `evaluation/state.py` | 状态提交和整体几何指标 |
| `visualization/renderer.py` | 决策前VLM图像和重放动画 |
| `runners/core.py` | 固定案例与在线episode编排 |

### GOPT参考源码

| 文件 | 主要职责 |
|---|---|
| `GOPT-main/envs/Packing/ems.py` | 高度图角点、阶梯角点和六维EMS生成 |
| `GOPT-main/envs/Packing/container.py` | 高度图、合法性、EMS/EP候选和箱体放置 |
| `GOPT-main/envs/Packing/env.py` | Gym环境、观测、mask、动作和奖励 |
| `GOPT-main/model.py` | 物料—EMS交叉注意力、Actor和Critic |
| `tests/golden/test_gopt_small_spaces.py` | 当前生成器与GOPT基础空间覆盖对照 |

## 19. 当前实现限制与后续修改优先级

### 19.1 进入VLM阶段前必须保持冻结

1. 容器坐标系；
2. 支撑率阈值0.70；
3. 0°/90°旋转集合；
4. 几何评分定义和权重；
5. Top-K=16；
6. Candidate公开字段；
7. Selector响应白名单；
8. train/validation/test划分。

否则传统方法与VLM将面对不同的候选空间，失去公平性。

### 19.2 建议在阶段1C实现

1. `VLMSelector`和模型调用适配层；
2. 严格JSON重试与错误分类；
3. 结构化输入、视觉输入和图文输入三种消融；
4. 决策级语义成功率、硬违规率和Oracle regret；
5. token、时延、调用失败率和fallback率；
6. 确保只用validation调整提示词，冻结后再测试ID/OOD。

### 19.3 建议在在线VLM或ReMe阶段补充

1. `episode_mean_soft_utility`；
2. `episode_total_semantic_violations`；
3. 每步语义后果与最终episode结果的关联；
4. 真实`downward_load_kg`公开摘要；
5. 经验卡证据、版本和重写历史；
6. Instruction Shift连续任务流。

### 19.4 可以暂缓

1. 完整GOPT训练复现；
2. buffer3选箱和BufferBeam；
3. 连续角度旋转；
4. 非轴对齐箱体；
5. 材料形变和精细接触动力学；
6. Gazebo、RGB-D、MoveIt 2和Aubo i5闭环。

## 20. 论文中建议的技术表述

可以表述为：

> 本研究借鉴GOPT及三维装箱问题中的EMS候选动作思想，在真实毫米尺度的码垛状态上设计了基于极值点与支撑层的EMS-style候选生成器。生成器枚举当前箱体的0°/90°姿态和地面/支撑层极值点，并通过容器边界、三维碰撞、最小支撑面积、重心投影、可堆叠性、容器载荷及递归顶部承重约束进行过滤。随后根据紧凑度、高度、稳定性和平衡性构造多样性Top-K候选。VLM不生成连续坐标，而是在统一的合法候选集合中依据自然语言业务规则选择candidate ID；环境在提交前使用独立物理检查器再次复核。

若未完成GOPT训练与严格复现，实验方法名应保持为：

```text
GOPT-inspired EMS-style candidate generator
```

而不应写成：

```text
GOPT planner
完整GOPT复现
从GOPT源码移植的EMS算法
```

这种命名既能说明思想来源，也准确反映当前代码的独立实现和约束扩展。
