# 测试环境说明

本轮使用 `/home/cyw/anaconda3/envs/pallet_vlm/bin/python`，Python3.11.16、Pillow11.1.0、jsonschema4.23.0、numpy2.1.3。

第一次直接启动pytest尚未收集测试即失败：当前shell可见ROS插件自动加载 `/opt/ros/humble/lib/python3.10/site-packages/launch_testing`，其依赖 `lark` 不存在，触发 `ModuleNotFoundError: No module named 'lark'`。未安装/改动依赖；后续测试显式设置 `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1`，使用pytest内置功能和仓库conftest。该设置不修改被测逻辑、数据或校验门槛。

首轮 `tests.initial.xml`：110项现有O5回归通过。`tests.text.first.xml`：35项Direct-Text测试通过。最终含补充风险测试及原物理回归的批次以 `tests.acceptance.final.xml` 和同名log为准。
