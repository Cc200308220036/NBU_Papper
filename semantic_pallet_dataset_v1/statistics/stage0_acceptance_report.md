# 阶段0数据与接口验收报告

结论：**PASS**

## 自动验收

- [x] 基础Schema与划分校验
- [x] 独立几何复核
- [x] VLM白名单输入无隐藏标签
- [x] 全部视觉输入可读取
- [x] 完整在线可视化episode
- [x] 两次重建校验和一致
- [x] buffer3能力边界已声明

## 关键统计

- VLM白名单输入：360份；视觉输入：720张PNG。
- 独立复核候选：5124个，其中多层候选1963个，错误0。
- 非平凡语义Decision Case：244/360。
- 平均Top-K数量：14.233333；平均Pareto覆盖：0.900387。

## 能力边界

- buffer_size=1已通过固定Decision Case、VLM协议及完整在线可视化episode验收。
- buffer_size=3当前只有20个配对场景，没有Decision Case和动态选箱候选，留待阶段1实现。
- 当前图片是由数据集真值生成的合成视觉输入，不是Gazebo RGB-D图像。

## 视觉抽查

已按validation、Test-ID、Geometry-OOD、Semantic-OOD、Language-OOD各抽6例生成30例清单和总览图。冻结论文正式V1.0前，课题负责人仍应复核并签字。
