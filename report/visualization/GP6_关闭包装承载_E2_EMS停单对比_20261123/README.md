# GP6 关闭包装承载上限：E2 / EMS 停单对比

用浏览器打开 [index.html](index.html)。单文件离线运行，不依赖服务器或第三方资源。

- 默认并排展示真实终态：E2 8 箱 / 40.17%，EMS 4 箱 / 15.90%。
- 滑块或播放按钮回看提交顺序；点击箱体或轨迹查看尺寸、位置、实际 Cxx 与候选数量。
- 立体、俯视、正视三种视图；两条轨迹按提交次数对齐，不表示相同决策时刻或相同候选池。
- 点击“EMS 停在哪里”，切换 25 个去重后的实际拒绝动作。红框是保存动作，绿色为同高度的接触区域；支撑比例范围 0–64.83%，要求 70%。默认展示最高支撑比例动作。
- 点击“E2 停在哪里”，查看每箱 3408 次越界、855 次碰撞拒绝。顶部加箱是明确标注的高度示意，非归档失败动作；E2 原记录未保存失败坐标。

这些数据只能证明已枚举动作全部被拒，不能证明连续空间全局无解。没有新实验、模型调用、候选搜索或稳定性求解。几何接触比例由归档布局与归档动作的矩形并集派生，仅用于解释。

## 来源与检查

来源是 `semantic_pallet_planner/outputs/GEOM_CANDIDATES_GP6_TOP_LOAD_DISABLED_RUN_20261122_01/` 的两项 checkpoint、metrics、末步审计 blob 及原计划。`case_data.json` 保存来源哈希，`index.html` 内嵌同一份数据；没有密钥、请求原始响应或私有整单未来内容。

构建：

```bash
python3 report/visualization/GP6_关闭包装承载_E2_EMS停单对比_20261123/build_visualization.py
```

已使用现有 Firefox 的 WebDriver BiDi 复验全部 9 个回放进度、3 种视图、25 个 EMS 叠加动作、E2 高度示意开关和 1600/760/390 像素布局；无 JavaScript 错误，源证据哈希保持不变。见 `browser_validation.json`、`browser_overview.png`、`browser_support_detail.png`。测试浏览器的独立临时配置已清理。

浏览器复验脚本 `validate_browser.py` 连接专用 `ws://127.0.0.1:9335/session`；需先使用独立临时配置启动现有 Firefox（不要连接用户日常浏览器配置）。验证过程不调用生产实验代码。
