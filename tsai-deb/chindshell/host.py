"""共享 Flask 服务 —— 多个套壳应用的后端集中在同一进程，窗口进程只负责渲染。

用 DispatcherMiddleware 按 URL 前缀把各应用的 Flask app 挂载到统一端口。
z/scr/bai/clockai 参与共享；hm/hy 因 meeting 包实现不同保留独立服务。
"""
import importlib.util
import os
import sys

from flask import Flask, Response
from werkzeug.middleware.dispatcher import DispatcherMiddleware

HOST_PORT = 19400

APP_DIRS = {
    "/z": "/usr/chindows/z",
    "/scr": "/usr/chindows/scr",
    "/bai": "/usr/chindows/bai",
    "/clockai": "/usr/chindows/clockai",
}


def _load_server(uniq, path, basedir):
    sys.path.insert(0, "/usr/chindows")
    sys.path.insert(0, basedir)
    spec = importlib.util.spec_from_file_location(uniq, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[uniq] = mod
    spec.loader.exec_module(mod)
    return mod.app


def build():
    from chindshell import flask as csf

    root = Flask("chindshell_host", static_folder=None)
    csf.register(root)

    @root.route("/")
    def home():
        items = "".join(f'<li><a href="{p}/">{p}</a></li>' for p in sorted(APP_DIRS))
        return Response(f"<h3>chindshell host</h3><ul>{items}</ul>")

    mounts = {}
    for prefix, basedir in APP_DIRS.items():
        name = "app_" + prefix.strip("/")
        mounts[prefix] = _load_server(name, os.path.join(basedir, "server.py"), basedir)

    return DispatcherMiddleware(root.wsgi_app, mounts)


def main(port=HOST_PORT):
    from werkzeug.serving import make_server

    disp = build()
    try:
        srv = make_server("127.0.0.1", port, disp, threaded=True)
    except OSError:
        sys.exit(0)  # 端口已被占用（另一个 host 已在运行）
    srv.serve_forever()


if __name__ == "__main__":
    main()
