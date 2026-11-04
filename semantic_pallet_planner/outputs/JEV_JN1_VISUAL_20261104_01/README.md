# JN1完整订单码垛交互观察台

入口为 `JN1_interactive.html`，直接双击即可离线打开；可以单独复制这个HTML，无需安装、联网或启动服务。开发源码在 `web/`。参照 JEV_JN0_VISUAL_20261103_01 的投影、时间线、箱体属性和监测面板制作，增加JN1真实请求与三方法并排对照。

## 查看顺序

1. 页首切换订单00100153（15箱）或00100150（18箱），并排查看 Jev无经验、几何基线、固定顺序的最终已提交布局。视角、容器与尺度一致；卡片列出装入件数、体积比例、垛高、包络利用率、固定容器利用率及历史请求数。
2. 点击对照卡或左侧运行卡，进入该运行。拖动旋转、滚轮缩放，切换俯视/正视、箱号、反力和高度切片；点击箱体查看位置、尺寸、质量与承载。虚线箱体是尝试动作，尚未计入提交数量。
3. 时间线播放或拖动至任意保存事件；切换选择前、已选动作、监测后、提交/停止后。跳到停单可查看候选池为空或不可评价。箱体整单表是事后信息，含未到货箱体，不是模型输入。
4. “Jev输入/输出”展示实际公开状态概览、Cxx到不可变候选与精确动作的映射、原生概率和confidence、token及完整请求/响应JSON。通过面板末尾请求按钮切换该订单全部真实请求，可下载请求和响应。没有模型生成的解释，不补写选择理由；概率/confidence不是物理稳定概率。本地基线明确显示没有API输出。
5. “监测过程”选择箱体节点，查看自身质量、上层传载、向下反力、实际接触角点、有效作用中心与保守凸包；从保存反力计算质量和两轴力矩残差。公式页解释面积承载账本、落高核对、全局接触网络LP、严格内部余量及独立复核；网页不执行LP。
6. “原始证据”提供事件路径、SHA256、持久化阶段、公开选择上下文和监测JSON下载。右上角六次运行数据提供原始方向的配对指标与有效性限制。

## 本页的实际数据范围

只读源：`semantic_pallet_planner/outputs/JEV_JN1_20261103_03/`，即JN1-B的两个已暴露训练来源、三种方法、六次完整订单入口运行。JN1-A的单次请求不计入本页。完整订单入口运行不表示整单全部装入。

- 完整装完0/6；五次EMPTY_POOL，一次UNASSESSABLE；技术错误0。
- 122个保存事件，50次已选监测：49 STABLE、1 UNASSESSABLE；49次成功提交。没有观测到UNSTABLE，不编造失败反力或预测失稳示例。
- 17次历史真实请求分属J0000（11次）与J0003（6次），模型jev-1.14.0，memories均为空；其他四次运行没有API调用。历史实际费用UNKNOWN。本次新增模型请求0，不读取凭证。
- 订单00100153：Jev装11/15箱、815mm；几何10/15箱、840mm；固定10/15箱、850mm，后者因不可评价停止。
- 订单00100150：三方法均6/18箱，Jev555mm、几何380mm、固定480mm，Jev在这例的高度与包络紧凑性更差。只作已暴露来源的轨迹描述，不据此推断总体收益或未见泛化。
- 不可评价原选item_13底面230mm、顶面520mm；与既有item_10有90×5mm的XY投影重叠，上方箱底570mm，真实空隙50mm。保守从上方落箱预检取850mm，差620mm，POSE_HEIGHT_MISMATCH；失败动作未提交，不是预测静态失稳，也没有最终反力解。

均匀刚性箱、轴对齐0/90度、竖直准静态、合成包装承载等假设保留。反力为重力约去的等效kg，位置mm、力矩kg·mm；不是摩擦、冲击、变形或真实坍塌动力学。原面积账本与PCT反力不互相回写。

## 已执行验证与复现

从仓库根目录执行：

```bash
python semantic_pallet_planner/outputs/JEV_JN1_VISUAL_20261104_01/export_records.py
node --check semantic_pallet_planner/outputs/JEV_JN1_VISUAL_20261104_01/web/app.js
python semantic_pallet_planner/outputs/JEV_JN1_VISUAL_20261104_01/package_viewer.py
python semantic_pallet_planner/outputs/JEV_JN1_VISUAL_20261104_01/browser_qa.py
python semantic_pallet_planner/outputs/JEV_JN1_VISUAL_20261104_01/standalone_smoke.py
python semantic_pallet_planner/outputs/JEV_JN1_VISUAL_20261104_01/package_viewer.py
```

- stdlib导出器只读取JSON，独立算术核验49个STABLE结果的239组节点质量/力矩与全局地面质量；结果见 `computation_audit.json`。未调用订单引擎、候选器、物理提交或求解器。
- 现有Chrome的file://实际运行17项交互检查，覆盖488个事件/阶段视图、17次真实I/O、本地无API提示、两来源对照、搜索筛选、场景点击、播放、下载、公式/证据、移动端无横向溢出及239组浏览器数值复算。页面HTTP/HTTPS/WS/WSS由CDP阻断；仅使用本机回环端口控制Chrome，没有模型请求。
- `qa/browser_acceptance.json` 与 `qa/standalone_acceptance.json` 记录实际结果；`qa/comparison.png`、`qa/desktop.png`、`qa/mobile.png`为本机截图。
- 导出前和最终打包均核对历史交付清单的883个文件摘要，全部保持不变。源码、数据、算法、冻结身份及历史报告未修改；没有commit/push或在线部署。

`source_manifest.json`记录事件与原生I/O来源摘要，`handoff.json`记录交付范围，`delivery_manifest.json`记录本网页包文件摘要。只新增本可视化目录，不开发后续阶段。
