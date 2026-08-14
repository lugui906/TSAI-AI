#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""AI 助手面板：快捷命令 + 对话 + AIM 桥接。"""
import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gtk, GLib

from aps.ai.aim import AimBridge
from aps.ai.agent import QUICK_CMDS, build_prompt


class AiPanel(Gtk.Box):
    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self.set_size_request(340, -1)
        self.bridge = AimBridge()
        self._doc = None  # 当前 Document（由主窗口注入）

        # 标题
        title = Gtk.Label(label="AI 助手 · AIM 驱动")
        title.add_css_class("title")
        self.append(title)

        # 快捷命令
        quick = Gtk.FlowBox()
        quick.set_max_children_per_line(3)
        quick.set_selection_mode(Gtk.SelectionMode.NONE)
        for name in ["生成PPT", "生成Word", "生成Excel", "总结", "改写", "分析", "问答", "翻译"]:
            b = Gtk.Button(label=name)
            b.connect("clicked", self._on_quick, name)
            quick.append(b)
        self.append(quick)

        # 对话历史
        self.chat_view = Gtk.TextView()
        self.chat_view.set_editable(False)
        self.chat_view.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        self.chat_buf = self.chat_view.get_buffer()
        sw = Gtk.ScrolledWindow()
        sw.set_child(self.chat_view)
        sw.set_vexpand(True)
        self.append(sw)

        # 输入区
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        self.entry = Gtk.Entry()
        self.entry.set_placeholder_text("让 AI 操作文档…")
        self.entry.connect("activate", lambda *_: self._on_send())
        row.append(self.entry)
        send = Gtk.Button(label="发送")
        send.connect("clicked", lambda *_: self._on_send())
        row.append(send)
        stop = Gtk.Button(label="停止")
        stop.connect("clicked", lambda *_: self.bridge.cancel())
        row.append(stop)
        self.append(row)

        self._log("APS AI 就绪 🥬 对任意文档下指令：生成 / 修改 / 分析 / 问答")

    # ------------------------------------------------------------------
    def set_document(self, doc):
        self._doc = doc

    def _log(self, text: str):
        self.chat_buf.insert(self.chat_buf.get_end_iter(), text + "\n")
        self._scroll_bottom()

    def _scroll_bottom(self):
        adj = self.chat_view.get_vadjustment()
        if adj:
            adj.set_value(adj.get_upper())

    def _on_quick(self, btn, name):
        self._send(QUICK_CMDS.get(name, name))

    def _on_send(self, *_):
        prompt = self.entry.get_text().strip()
        if prompt and not self.bridge.busy:
            self.entry.set_text("")
            self._send(prompt)

    def _send(self, prompt: str):
        doc = self._doc
        doc_type = doc.ext.lstrip(".") if doc else "txt"
        context = doc.context_snippet() if doc else None
        full = build_prompt(prompt, doc_type, context)
        self._log(f"\n🧑 你：{prompt}")
        self._log("🤖 AI 执行中…")

        def delta(line):
            GLib.idle_add(self._log, line)

        def done(full_out):
            GLib.idle_add(self._log, "✅ 完成" + ("-" * 24))

        def error(msg):
            GLib.idle_add(self._log, f"❌ 出错：{msg}")

        self.bridge.send(full, run=False,
                         on_delta=delta, on_done=done, on_error=error)
