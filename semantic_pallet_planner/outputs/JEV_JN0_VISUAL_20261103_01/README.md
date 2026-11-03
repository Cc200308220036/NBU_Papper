# JN0八次运行交互观察台

直接双击 `JN0_interactive.html`，无需安装、联网或启动服务。此文件包含全部网页代码和数据，可以单独复制。

开发版入口是 `web/index.html`，需要保留同目录的CSS、JS和数据文件。

## 如何使用

1. 左侧选择8次运行之一；右上角打开八次运行与四来源配对表。
2. 拖动三维场景旋转，滚轮缩放；支持俯视、正视和高度切片。
3. 使用时间滑块、事件按钮、播放及左右方向键浏览150个保存事件。
4. 切换选择前、已选动作、监测后、提交/停止后；虚线箱体为尝试位置，不计入已提交数量。
5. 点击场景、箱表或节点表查看每个箱体的尺寸、质量、可堆叠性、承载上限、原面积账本载荷/剩余、位置、包装与来源。
6. 在监测过程查看实际反力、每箱平衡数值代入、全局残差及求解器阶段；计算公式页解释面积分载与PCT全局LP两套模型。
7. 点击“跳到停单”查看6次空池与2次不可评价；不可评价页提供原选高度/预检落高示意及下方空隙切片。
8. 原始证据页展示保存路径和SHA256，可下载当前帧与监测结果JSON；不请求网络。

## 数据与计算边界

只读源为 `semantic_pallet_planner/outputs/JEV_JN0_20261103_02/`。仅展示8次补验收运行：6空池、2高度不一致不可评价，59/61个动作可评价，完整完成0/8；历史技术失败仍在原包，累计实际尝试9次。

模型、候选器、数据、冻结结果未修改。本次没有重新运行订单、调用模型API或LP。`export_records.py`只读取记录并从角点反力独立算术复核59个STABLE结果的263组节点质量/力矩平衡。2个UNASSESSABLE动作没有最终反力解，网页不补造结果；这8次没有观测到UNSTABLE，不伪造示例。

PCT反力以等效kg表示，位置mm、坐标矩kg·mm；均匀刚性箱与竖直准静态假设保留。原面积承载账本与PCT接触反力单独显示。箱体整单表是事后复盘信息，包含未到货箱体；真实选择上下文中没有未来箱体、PCT标签和反力。

## 本机验证

- `node --check semantic_pallet_planner/outputs/JEV_JN0_VISUAL_20261103_01/web/app.js`
- `python semantic_pallet_planner/outputs/JEV_JN0_VISUAL_20261103_01/export_records.py`
- `python semantic_pallet_planner/outputs/JEV_JN0_VISUAL_20261103_01/browser_qa.py`
- `python semantic_pallet_planner/outputs/JEV_JN0_VISUAL_20261103_01/package_viewer.py`

使用现有本机Chrome，通过file://实际检查15项行为，包括600个事件/阶段视图、点击箱体、播放、搜索筛选、下载JSON、公式/证据、移动端无横向溢出和263组浏览器算术复核。截图和记录在 `qa/`。没有安装浏览器或依赖，没有启动对外服务，没有commit/push。

`source_manifest.json`记录逐事件源文件摘要，`handoff.json`记录交付边界，`delivery_manifest.json`记录网页包摘要。既有补验收包717个文件在打包后重新核验，原证据字节不变。
