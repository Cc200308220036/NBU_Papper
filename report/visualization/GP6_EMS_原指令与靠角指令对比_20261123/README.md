# EMS 原指令与靠角指令对比

直接用浏览器打开 [index.html](index.html)，不需要联网、服务器或依赖安装。原 E2/EMS 页面未修改。

展示归档关闭包装承载的 G01 与 2026-11-23 EMS 靠角文字单项实验。支持同步0—4步回看、播放、首箱/分歧/最终定位、俯视/立体/正视、真实首步角落候选叠加及点击箱体查看精确姿态。新增英文以绿色区块显示，同时提供原指令和实际发送完整文字。

观察：新增文字在4份实际请求中均已逐字核对；两次首箱均为C17/item_03，中心(0,0)，并未贴角。前两步相同，第3步后选箱/顺序分化，最后右侧箱体为对照item_05、本次item_04。最终几何布局相同，两次均4/19箱、固定容器利用率15.9027%、垛高320 mm、4次STABLE监测、无候选停单。因此本次没有观察到装入指标改善；单次结果不能独立证明后续差异由文字引起，也不能推广为提示词普遍无效。

数据只提取保存事实，不访问模型、候选器、监测、凭证或订单执行入口。几何视图由保存坐标绘制，虚线是候选，不是实际放置。首步候选几何及顺序已核对；新计划的candidate_id/fingerprint不同，不能称全字节相同。完整来源哈希在case_data.json中，实际指令取自本次run/sent_requests而非配置模板。

构建：

```bash
python3 -I -B report/visualization/GP6_EMS_原指令与靠角指令对比_20261123/build_visualization.py
```

浏览器验证：

```bash
python3 -B report/visualization/GP6_EMS_原指令与靠角指令对比_20261123/validate_browser.py
```

验证需要现有Firefox WebDriver BiDi监听本机9335。本机复验时原端口关闭，首次沙箱网络访问被限制，提权连接确认端口关闭；启动已有Firefox时/tmp被Snap隔离无法读取profile，改用工作区独立临时profile后成功。最终Firefox浏览器验证PASS，收据为browser_validation.json，截图为browser_first_box.png与browser_final_layout.png。检查了5个进度帧、3种视图、候选开关、箱体详情、播放暂停、实际全文、2行轨迹分化和1560/760/390宽度；无页面JS错误、源文件哈希未变。所建临时profile已清理、独立浏览器已停止。

本次只读可视化，新增模型调用/监测/订单运行均0。没有上传或发布实验数据，没有commit/push。
