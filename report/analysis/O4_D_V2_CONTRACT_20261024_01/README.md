# O4-D V2公共契约离线验证

- [实现说明与运行命令](../../../docs/03_阶段产出分析/O4/O4D_V2公共契约修订与离线验证_20261024.md)
- [最终证据摘要](evidence.json)
- [最终测试JUnit](pytest.xml)
- [247条历史失败的公开诊断回归](failure_regression.json)及[只读复核脚本](verify_public_failures.py)。V2诊断为237条非法类别值和10条绑定不匹配；后者包含V1归为其他Schema问题的摘要格式错误，未改写V1原分类。
- [初轮测试记录](pytest_initial.xml)：含测试期间源码变动保护触发及新增测试取样错误，不作为通过证据。
- [开发前保护清单](protected.before.json)及[开发后核验](protected.after.json)。核对原源码/配置/测试及两份真实D实验，共8517份原有文件。
- [离线CLI验收](../../../semantic_pallet_planner/outputs/EXP_O4_D_V2_CONTRACT_OFFLINE_20261024_01/acceptance_report.json)：48条记录、24次本地服务替身请求、真实API调用0。

247条既有最终失败仅用于诊断回归；它们仍是原V1失败，不计作修复成功。V2真实模型收益尚未测量。

最终V1/V2相关回归116项通过、0失败；原有8517份受保护文件变化0。运行采用`PYTHONDONTWRITEBYTECODE=1 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1`，pytest附加`-p no:cacheprovider`，无真实模型请求。
