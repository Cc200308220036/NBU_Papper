# 展示层浏览器验证

在仓库根目录，使用现有Chrome和Python websocket-client；不安装或升级依赖。先在两个独立终端启动只读静态服务器和临时调试浏览器：

```bash
python3 -m http.server 8767 --bind 127.0.0.1 --directory report/visualization/Jev_JN4_六方法决策回看_20261107/web
google-chrome --headless --no-sandbox --disable-dev-shm-usage --use-angle=swiftshader --enable-unsafe-swiftshader --remote-debugging-address=127.0.0.1 --remote-debugging-port=9227 --remote-allow-origins='*' --user-data-dir=/tmp/jn4-viewer-chrome about:blank
```

再在第三个终端运行：

```bash
PYTHONDONTWRITEBYTECODE=1 python3 report/visualization/Jev_JN4_六方法决策回看_20261107/qa/browser_verify.py
```

并列功能专项检查：

```bash
PYTHONDONTWRITEBYTECODE=1 python3 report/visualization/Jev_JN4_六方法决策回看_20261107/qa/ties_verify.py
```

脚本只操作展示页，使用本机8767/9227端口；不包含模型、凭证或内核入口。产生截图与browser_checks.json。没有启动浏览器时脚本会失败，不自动启动其他服务。检查后关闭自己启动的临时浏览器和服务器；不要对外开放调试端口。脚本不会写入实验run。
