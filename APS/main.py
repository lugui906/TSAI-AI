#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""APS — AI 原生办公套件（对标 WPS）

三件套：文字 / 表格 / 演示 + PDF 阅读 + AI 中枢（AIM 接入）

用法：
  python3 main.py            # 打开 APS 桌面套件主窗口
  python3 main.py --lo       # 打开 LibreOffice 伴侣窗口（连接 LO 的 UNO socket 端口 2002）
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gtk, Gio

from aps.ui.main_window import MainWindow


class APSApp(Gtk.Application):
    def __init__(self, companion: bool = False):
        super().__init__(application_id="com.turtlesoft.aps",
                         flags=Gio.ApplicationFlags.FLAGS_NONE)
        self._companion = companion

    def do_activate(self):
        win = self.props.active_window
        if not win:
            if self._companion:
                from aps.ui.lo_companion import LoCompanionWindow
                win = LoCompanionWindow(application=self)
            else:
                win = MainWindow(application=self)
        win.present()


def main():
    companion = "--lo" in sys.argv
    if companion:
        sys.argv.remove("--lo")
    app = APSApp(companion=companion)
    sys.exit(app.run(sys.argv))


if __name__ == "__main__":
    main()
