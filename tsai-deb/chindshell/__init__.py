"""chindshell — TSAI-OS HTML套壳共享框架。

WebKit GTK4 窗口 + 本地 Flask 服务，模仿 chinai3 的结构。
用法：每个应用提供自己的 server.py（Flask app），入口脚本调用
`chindshell.shell.run(...)` 即可。
"""
