# Jev case viewer

独立的真实实验可视化导出器。只读封存记录，不导入规划器、不调用模型、不重做轨迹。

- `export-case.mjs`：核对封存文件SHA-256，按当前请求的真实Cxx和Bxxx映射提取数据并导出单文件页面。
- `template.html`、`viewer.css`、`viewer.js`：三维视图、全部候选、步骤播放及输入输出面板。
- `vendor/`：固定Three.js 0.128.0及OrbitControls、MIT许可。页面使用内嵌资源，可离线打开。

```bash
node semantic_pallet_planner/src/semantic_pallet_planner/jev_select/viewer/export-case.mjs
```

默认案例：正式`EXP_JEV_J3_TEST_20261029_01`中的J0025 / SCN_0065_B1，13次真实Choice，13/13码放且有9个业务违规实例。默认产物：`semantic_pallet_planner/outputs/JEV_J3_CASE_VIEWER_20261029_01/index.html`。导出到新目录，不覆盖封存实验；仅更新自己生成的页面时可用`--refresh`。

约束：页面不伪造模型理由；事后事实分析与模型原始输出分开。备选项只做位置预览，不展示未经执行的业务结果。动画是坐标展示，不是物理或机器人路径仿真。所有新增前端代码集中在本目录；不修改原J3生产Python/JSON协议或实验快照。
