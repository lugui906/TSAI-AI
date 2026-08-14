#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""APS AI · LibreOffice 伴侣窗口 — 外部 GTK 小窗口

通过 UNO socket（端口 2002）连接本机 LibreOffice：
  - 不展示文件内容
  - AI 输出实时流式刷新（AIM 逐行回显）
  - 连接状态自动检测与重连（LO 重启后自动恢复）
  - AI 操作：总结 / 问答 / 自由操作（AI 生成脚本直接落地到文档）
"""
import threading

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gtk, GLib

from aps.lo.bridge import LOBridge, DEFAULT_PORT

DOC_TYPE_LABEL = {
    "writer": "Writer 文字",
    "calc": "Calc 表格",
    "impress": "Impress 演示",
    "unknown": "（无文档）",
}


class LoCompanionWindow(Gtk.ApplicationWindow):
    def __init__(self, application=None, port: int = DEFAULT_PORT):
        super().__init__(application=application,
                         title="APS AI · LibreOffice 伴侣")
        self.set_default_size(460, 620)
        self.set_size_request(360, 460)

        self.bridge = LOBridge(port=port)
        self._busy = False
        self._in_conversation = False  # 多对话：True 表示当前对话进行中，后续用 aim run

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        root.set_margin_top(8)
        root.set_margin_bottom(8)
        root.set_margin_start(8)
        root.set_margin_end(8)

        # ---------------- 连接状态栏 ----------------
        top = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self.status_label = Gtk.Label(label="正在连接 LibreOffice…", xalign=0)
        self.status_label.set_hexpand(True)
        top.append(self.status_label)
        save = Gtk.Button(label="保存")
        save.connect("clicked", self._on_save)
        top.append(save)
        root.append(top)

        # ---------------- AI 操作 ----------------
        quick = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        for label, action in [("总结", "summarize"), ("问答", "ask"),
                              ("自由操作", "execute")]:
            b = Gtk.Button(label=label)
            b.connect("clicked", self._on_quick, action)
            quick.append(b)
        new_conv = Gtk.Button(label="新对话")
        new_conv.connect("clicked", self._on_new_conversation)
        quick.append(new_conv)
        root.append(quick)

        self.entry = Gtk.Entry()
        self.entry.set_placeholder_text("问题或操作指令（AI 直接修改文档，输出实时刷新）…")
        self.entry.connect("activate", self._on_send)
        root.append(self.entry)

        send = Gtk.Button(label="发送")
        send.connect("clicked", self._on_send)
        root.append(send)

        # ---------------- 输出区（实时刷新） ----------------
        self.output = Gtk.TextView()
        self.output.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        self.output.set_editable(False)
        self.output_buf = self.output.get_buffer()
        self.output_buf.create_tag("ok", foreground="#2e7d32")
        self.output_buf.create_tag("err", foreground="#c62828")
        self.output_buf.create_tag("dim", foreground="#888888")
        osw = Gtk.ScrolledWindow()
        osw.set_child(self.output)
        osw.set_vexpand(True)
        root.append(osw)

        self.set_child(root)

        # 后台连接
        threading.Thread(target=self._connect_bg, daemon=True).start()
        # 实时刷新：每 3 秒检测连接状态，断开则自动重连
        GLib.timeout_add_seconds(3, self._auto_refresh)

    # ---------------- 连接 / 实时刷新 ----------------
    def _connect_bg(self):
        ok = self.bridge.connect(timeout=20)
        if ok:
            GLib.idle_add(self._set_status,
                          f"已连接 LibreOffice（端口 {self.bridge.port}）", False)
        else:
            GLib.idle_add(self._set_status,
                          "未连接：请用 launcher 启动 LibreOffice（自动带 UNO socket 端口 2002）",
                          True)

    def _auto_refresh(self):
        """周期调用：刷新连接状态 + 当前文档类型；断开则自动重连。"""
        if not self.bridge.connected:
            threading.Thread(target=self._connect_bg, daemon=True).start()
            return True
        try:
            if not self.bridge.ping():
                self.bridge.disconnect()
                threading.Thread(target=self._connect_bg, daemon=True).start()
            else:
                label = DOC_TYPE_LABEL.get(self.bridge.doc_type(), "（无文档）")
                GLib.idle_add(self._set_status,
                              f"已连接 · {label}（端口 {self.bridge.port}）", False)
        except Exception:
            pass
        return True

    def _set_status(self, text, is_err):
        self.status_label.set_text(text)
        self.status_label.add_css_class("dim-label" if not is_err else "error")

    # ---------------- 保存 ----------------
    def _on_save(self, *_):
        def worker():
            try:
                msg = self.bridge.save()
                GLib.idle_add(self._append_output, f"💾 {msg}", "dim")
            except Exception as e:  # noqa: BLE001
                GLib.idle_add(self._append_output, f"保存失败：{e}", "err")
        threading.Thread(target=worker, daemon=True).start()

    # ---------------- AI 操作（流式实时刷新） ----------------
    def _on_quick(self, btn, action):
        self._run_action(action)

    def _on_send(self, *_):
        self._run_action("execute")

    def _on_new_conversation(self, *_):
        """开始新对话：下一次提问将使用 aim newrun。"""
        self._in_conversation = False
        self._append_output("── 新对话开始（下一次将使用 aim newrun）──", "dim")

    def _run_action(self, action):
        if self._busy:
            self._append_output("（上一任务仍在处理，请稍候…）", "dim")
            return
        instruction = self.entry.get_text()
        if action in ("ask", "execute") and not instruction.strip():
            self._append_output("请先在上方输入框输入内容。", "dim")
            return
        self._busy = True
        self.entry.set_text("")
        # 多对话：当前对话进行中 → aim run（继续）；否则 → aim newrun（新对话）
        run = self._in_conversation
        mode = "run（继续对话）" if run else "newrun（新对话）"
        self._append_output(f"🧠 {action} · {mode} 处理中…", "dim")

        def delta(line):
            GLib.idle_add(self._append_output, line, "ok")

        def done(out):
            GLib.idle_add(self._finish_run)
            GLib.idle_add(self._append_output, "── 完成 ──", "dim")

        def error(msg):
            GLib.idle_add(self._finish_run)
            GLib.idle_add(self._append_output, f"❌ 出错：{msg}", "err")

        self.bridge.stream_action(action, instruction, run=run,
                                  on_delta=delta, on_done=done, on_error=error)

    def _finish_run(self):
        self._busy = False
        self._in_conversation = True  # 对话已开始，后续提问用 aim run

    def _append_output(self, text, tag=None):
        end = self.output_buf.get_end_iter()
        if tag:
            self.output_buf.insert_with_tags_by_name(end, text + "\n", tag)
        else:
            self.output_buf.insert(end, text + "\n")
        adj = self.output.get_vadjustment()
        if adj:
            adj.set_value(adj.get_upper())
