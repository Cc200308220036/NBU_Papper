# 回退原版E5四方法可视化

浏览器直接打开 `index.html`，无需启动服务。拖动滑块查看真实放置过程，切换俯视/三维轴测，选择方法查看本步公共请求、Parser AST、动作和候选；点击被拒候选可查看未实际提交的红色假设位置。

- `overview.png`：四方法最终俯视与三维对比。
- `metrics.json`：最终指标；`case_data.json`：页面数据与四条原始episode的SHA256。
- `browser_validation.json`：页面交互检查结果。
- `build_visualization.py` / `template.html`：从保存记录生成图表与页面；不运行规划器或API。

输入：`semantic_pallet_planner/outputs/EXP_O4_E5_ROLLBACK_SMOKE_20261027_01`，订单00101152、配置C0、public_parser，共4条已保存轨迹。单箱/FIFO/启发式/搜索分别放入8/8/7/8箱，实际业务违规均为0，但整单均未完成。实验总计划240条，仅执行4条，因此总状态PARTIAL正常。

滑块按已放箱次数对齐，各方法到货前缀不同。订单体积完成比例与托盘体积利用率分开计算。这里没有VLM输出；AST来自本地Parser。可视化未新增API调用、未重跑episode。
