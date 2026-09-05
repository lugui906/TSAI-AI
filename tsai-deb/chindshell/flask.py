"""Flask 辅助：挂载共享静态资源（chindshell/static）。"""
import os

from flask import send_from_directory

_ROOT = os.path.dirname(os.path.abspath(__file__))


def register(app):
    @app.route("/chindshell/<path:filename>")
    def _chindshell_static(filename):
        return send_from_directory(os.path.join(_ROOT, "static"), filename)
