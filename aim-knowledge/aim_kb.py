#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""AIM 知识库 - GTK 客户端

用户在主目录的 AI知识库 文件夹（~/AI知识库）放置知识库文件，
应用启动时会自动创建该文件夹。
输入框交互：
  - 首次发送  -> aim newrun <prompt>（新对话）
  - 之后发送  -> aim run <prompt>   （继续上一次对话）
  - 「新对话」按钮 -> 重置为 newrun 模式
提示词开头自动注入 AI 知识库位置信息。
"""

import os
import pwd
import threading
import subprocess

import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, GLib


def _home_dir():
    try:
        return pwd.getpwuid(os.getuid()).pw_dir
    except (KeyError, OSError):
        return os.path.expanduser("~")


KB_DIR = os.path.join(_home_dir(), "AI知识库")
KB_PROMPT = (
    "AI知识库位于 {kb_dir} 目录，回答问题时请先查阅该目录下的文件"
    "（可用读取/搜索工具浏览），再基于其中的内容作答。\n\n用户问题："
)

FONT_MONO = "monospace"
MOD_COLOR_QUESTION = "#1a6e3c"
MOD_COLOR_ANSWER = "#1a4fa0"
COLOR_USER = "#b03030"
COLOR_AI = "#1a6e3c"
COLOR_SYS = "#666666"
COLOR_ERR = "#cc0000"


def run_aim(mode, prompt):
    proc = subprocess.Popen(
        ["aim", mode, prompt],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        env=os.environ.copy(),
    )
    return proc


def stream_aim_output(proc, on_text, on_done):
    chunks = []
    for line in proc.stdout:
        line = line.rstrip("\n")
        if not line:
            continue
        chunks.append(line)
        on_text(line + "\n")
    proc.wait()
    on_done("".join(chunks))


class AimKbApp:
    def __init__(self):
        os.makedirs(KB_DIR, exist_ok=True)

        self.mode = "newrun"
        self._busy = False
        self._proc = None

        self.window = Gtk.Window(title="AIM 知识库")
        self.window.set_default_size(900, 640)
        self.window.connect("destroy", Gtk.main_quit)

        self._build_ui()
        self._refresh_file_list()
        self._append_sys("知识库目录：%s\n首次提问将开始新对话，后续输入自动延续上一对话。\n" % KB_DIR)

    def _build_ui(self):
        header = Gtk.HeaderBar()
        header.set_show_close_button(True)
        header.set_title("AIM 知识库")
        self.window.set_titlebar(header)

        new_btn = Gtk.Button(label="新对话")
        new_btn.set_tooltip_text("开始新对话（aim newrun）")
        new_btn.connect("clicked", self._on_new_conversation)
        header.pack_start(new_btn)

        refresh_btn = Gtk.Button(label="刷新")
        refresh_btn.set_tooltip_text("刷新知识库文件列表")
        refresh_btn.connect("clicked", lambda *_: self._refresh_file_list())
        header.pack_end(refresh_btn)

        hpane = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL)
        self.window.add(hpane)

        # --- 左侧：知识库文件列表 ---
        left = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        left.set_margin_start(4)
        left.set_margin_end(4)
        left.set_margin_top(4)
        left.set_margin_bottom(4)
        hpane.pack1(left, resize=False, shrink=False)

        self.mode_label = Gtk.Label(label="<b>对话模式：新对话</b>", use_markup=True, xalign=0)
        left.pack_start(self.mode_label, False, False, 0)

        lbl = Gtk.Label(label="<b>知识库 (~/AI知识库)</b>", use_markup=True, xalign=0)
        left.pack_start(lbl, False, False, 0)

        scroll = Gtk.ScrolledWindow()
        scroll.set_min_content_width(200)
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.file_store = Gtk.ListStore(str)
        self.file_view = Gtk.TreeView(model=self.file_store)
        renderer = Gtk.CellRendererText()
        col = Gtk.TreeViewColumn("文件名", renderer, text=0)
        self.file_view.append_column(col)
        self.file_view.get_selection().connect("changed", self._on_file_selected)
        scroll.add(self.file_view)
        left.pack_start(scroll, True, True, 0)

        self.file_path_label = Gtk.Label(label="", xalign=0, wrap=True)
        self.file_path_label.get_style_context().add_class("dim-label")
        left.pack_start(self.file_path_label, False, False, 0)

        # --- 右侧：对话区 ---
        right = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        right.set_margin_start(4)
        right.set_margin_end(4)
        right.set_margin_top(4)
        right.set_margin_bottom(4)
        hpane.pack2(right, resize=True, shrink=False)

        chat_scroll = Gtk.ScrolledWindow()
        chat_scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        self.buffer = Gtk.TextBuffer()
        self._init_tags()
        self.chat_view = Gtk.TextView(buffer=self.buffer)
        self.chat_view.set_editable(False)
        self.chat_view.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        self.chat_view.set_cursor_visible(False)
        chat_scroll.add(self.chat_view)
        right.pack_start(chat_scroll, True, True, 0)

        input_box = Gtk.Box(spacing=4)
        self.entry = Gtk.Entry()
        self.entry.set_placeholder_text("输入问题，回车发送…")
        self.entry.connect("activate", self._on_send)
        input_box.pack_start(self.entry, True, True, 0)

        self.send_btn = Gtk.Button(label="发送")
        self.send_btn.connect("clicked", self._on_send)
        input_box.pack_start(self.send_btn, False, False, 0)

        right.pack_start(input_box, False, False, 0)

    def _init_tags(self):
        self.buffer.get_tag_table()
        self.buffer.create_tag("sys", foreground=COLOR_SYS)
        self.buffer.create_tag("user", foreground=COLOR_USER, weight=700)
        self.buffer.create_tag("ai", foreground=COLOR_AI, weight=700)
        self.buffer.create_tag("err", foreground=COLOR_ERR, weight=700)

    # ---------- 知识库文件 ----------
    def _refresh_file_list(self):
        self.file_store.clear()
        if not os.path.isdir(KB_DIR):
            return
        names = sorted(os.listdir(KB_DIR))
        for name in names:
            full = os.path.join(KB_DIR, name)
            if os.path.isfile(full) or os.path.isdir(full):
                self.file_store.append([name])

    def _on_file_selected(self, selection):
        model, treeiter = selection.get_selected()
        if treeiter:
            name = model[treeiter][0]
            self.file_path_label.set_text(os.path.join(KB_DIR, name))
        else:
            self.file_path_label.set_text("")

    # ---------- 对话 ----------
    def _on_new_conversation(self, _widget=None):
        if self._busy:
            return
        self.mode = "newrun"
        self.mode_label.set_markup("<b>对话模式：新对话</b>")
        self._append_sys("已开启新对话（aim newrun）\n")

    def _on_send(self, _widget=None):
        if self._busy:
            return
        content = self.entry.get_text().strip()
        if not content:
            return

        self._busy = True
        self.entry.set_sensitive(False)
        self.send_btn.set_sensitive(False)

        prompt = KB_PROMPT.format(kb_dir=KB_DIR) + content
        mode = self.mode
        if mode == "newrun":
            self.mode = "run"
            self.mode_label.set_markup("<b>对话模式：继续对话</b>")

        self._append_user(content)
        self._append_ai_prefix()

        self.entry.set_text("")
        self._append_text("思考中…\n", tag="sys")

        def emit_text(chunk):
            GLib.idle_add(self._append_stream, chunk)

        def emit_done(reply):
            GLib.idle_add(self._on_reply_done, reply)

        def worker():
            try:
                proc = run_aim(mode, prompt)
                self._proc = proc
                stream_aim_output(proc, emit_text, emit_done)
            except Exception as e:  # noqa: BLE001
                GLib.idle_add(self._on_reply_done, "", error=str(e))

        t = threading.Thread(target=worker, daemon=True)
        t.start()

    def _append_user(self, text):
        end = self.buffer.get_end_iter()
        self.buffer.insert_with_tags_by_name(end, "你：\n", "user")
        self.buffer.insert(end, text + "\n\n")

    def _append_ai_prefix(self):
        end = self.buffer.get_end_iter()
        self.buffer.insert_with_tags_by_name(end, "AI：\n", "ai")

    def _append_stream(self, chunk):
        if not self._busy:
            return False
        end = self.buffer.get_end_iter()
        self.buffer.insert(end, chunk)
        mark = self.buffer.create_mark(None, end, False)
        self.chat_view.scroll_to_mark(mark, 0.0, True, 0.0, 0.5)
        return False

    def _append_sys(self, text):
        end = self.buffer.get_end_iter()
        self.buffer.insert_with_tags_by_name(end, text, "sys")

    def _append_text(self, text, tag=None):
        end = self.buffer.get_end_iter()
        if tag:
            self.buffer.insert_with_tags_by_name(end, text, tag)
        else:
            self.buffer.insert(end, text)

    def _on_reply_done(self, reply, error=None):
        self._busy = False
        self.entry.set_sensitive(True)
        self.send_btn.set_sensitive(True)
        self.entry.grab_focus()

        self._strip_stream("思考中…\n")
        if error:
            self._append_text("\n[错误] %s\n\n" % error, tag="err")
        else:
            self._append_text("\n\n")

    def _strip_stream(self, text):
        end = self.buffer.get_end_iter()
        start = end.copy()
        if start.backward_chars(len(text)):
            actual = self.buffer.get_text(start, end, False)
            if actual == text:
                self.buffer.delete(start, end)

    def run(self):
        self.window.show_all()
        Gtk.main()


def main():
    app = AimKbApp()
    app.run()


if __name__ == "__main__":
    main()
