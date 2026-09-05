#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ai-file-chat —— 文件管理右侧 AI 对话面板
- 从 Nautilus 右键菜单或命令行启动
- 支持把文件/目录作为附件，随问题一起通过 `aim newrun/run` 提交给 AI
- 单实例：再次传入路径会发送到已打开的面板，作为新附件追加
- 首个消息用 `aim newrun <内容> <附件路径>`（新对话），之后用 `aim run`（延续对话）
"""
import os
import sys
import queue
import socket
import threading
import subprocess
import time
import json

try:
    import gi
    gi.require_version("Gtk", "4.0")
    gi.require_version("Gdk", "4.0")
    gi.require_version("Pango", "1.0")
    from gi.repository import Gtk, Gdk, GLib, Pango, Gio
    try:
        import chindows_theme.style as chstyle
    except ImportError:
        import os as _os, sys as _sys
        _d = _os.path.dirname(_os.path.abspath(__file__))
        while _d and not _os.path.isdir(_os.path.join(_d, "chindows_theme")):
            _p = _os.path.dirname(_d)
            if _p == _d:
                break
            _d = _p
        if _d:
            _sys.path.insert(0, _d)
        try:
            import chindows_theme.style as chstyle
        except Exception:
            chstyle = None

except ImportError:
    sys.stderr.write("Error: PyGObject required. sudo apt install python3-gi gir1.2-gtk-4.0\n")
    sys.exit(1)

AIM_BIN = "/usr/bin/aim"
SOCKET_PATH = "/tmp/ai-file-chat.sock"
WINDOW_WIDTH = 460

HISTORY_DIR = os.path.expanduser("~/.nai")
HISTORY_FILE = os.path.join(HISTORY_DIR, "history.json")
MAX_HISTORY = 200

USER_TAG = "你"
AI_TAG = "AI"


def load_history():
    try:
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, list):
                return data
    except Exception:
        pass
    return []


def save_history(records):
    os.makedirs(HISTORY_DIR, exist_ok=True)
    tmp = HISTORY_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, indent=2)
    os.replace(tmp, HISTORY_FILE)


def add_history(record):
    records = load_history()
    records.insert(0, record)
    save_history(records[:MAX_HISTORY])


class AIChatWindow(Gtk.ApplicationWindow):
    def __init__(self, app, initial_paths=None):
        super().__init__(application=app, title="AI 对话 · 文件附件")
        self.set_default_size(WINDOW_WIDTH, 720)

        self.attachments = []          # [(display_name, full_path)]
        self.attachment_store = None   # Gtk.ListStore for the chips list
        self._proc = None
        self._first_message = True
        self._stop_flag = threading.Event()
        self._msg_queue = queue.Queue()
        self._sending = False
        self._history_messages = []

        self._build_ui()

        if initial_paths:
            for p in initial_paths:
                self.add_attachment(p)

        self._start_socket_listener()
        GLib.timeout_add(60, self._drain_queue)
        self.connect("destroy", self._on_destroy)

    # ------------------------------------------------------------------ UI
    def _build_ui(self):
        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.set_child(root)

        css = Gtk.CssProvider()
        css.load_from_data(b"""
            .chat-ai-view text { background: #ffffff; color: #1a1a1a;
                                  font-family: "Noto Sans CJK SC"; font-size: 13px; }
            .chat-path-chip { background: #eef3ff; color: #1d4ed8; border-radius: 4px;
                              padding: 2px 8px; font-size: 12px; }
        """)
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(), css,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

        toolbar = Gtk.HeaderBar(show_title_buttons=True)
        title_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        title_lbl = Gtk.Label(label="AI 对话")
        sub_lbl = Gtk.Label(label="右键文件 → AI 对话 · 附件随问题发送")
        sub_lbl.add_css_class("dim-label")
        title_box.append(title_lbl)
        title_box.append(sub_lbl)
        toolbar.set_title_widget(title_box)
        self.set_titlebar(toolbar)

        attach_btn = Gtk.Button(label="＋ 附件")
        attach_btn.connect("clicked", self._on_attach_clicked)
        toolbar.pack_start(attach_btn)

        new_conv_btn = Gtk.Button(label="新对话")
        new_conv_btn.set_tooltip_text("清空记录并开启全新对话")
        new_conv_btn.connect("clicked", self._on_new_conversation)
        toolbar.pack_end(new_conv_btn)

        # ---- attachments list ----
        attach_frame = Gtk.Frame()
        attach_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        attach_box.set_margin_top(6)
        attach_box.set_margin_bottom(6)
        attach_box.set_margin_start(6)
        attach_box.set_margin_end(6)
        attach_frame.set_child(attach_box)
        root.append(attach_frame)

        self.attachment_store = Gtk.ListStore(str, str)
        attach_list = Gtk.ListBox()
        attach_list.set_selection_mode(Gtk.SelectionMode.NONE)
        attach_list.set_visible(False)

        attach_scroll = Gtk.ScrolledWindow()
        attach_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        attach_scroll.set_max_content_height(160)
        attach_scroll.set_child(attach_list)
        attach_box.append(attach_scroll)

        self._attach_list = attach_list
        self._attach_frame = attach_frame
        self._attach_box = attach_box

        # ---- chat view ----
        self.chat_view = Gtk.TextView()
        self.chat_view.set_editable(False)
        self.chat_view.set_cursor_visible(True)
        self.chat_view.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        self.chat_view.add_css_class("chat-ai-view")
        self.chat_buf = self.chat_view.get_buffer()

        chat_scroll = Gtk.ScrolledWindow()
        chat_scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        chat_scroll.set_size_request(WINDOW_WIDTH - 60, 200)
        chat_scroll.set_vexpand(True)
        chat_scroll.set_child(self.chat_view)
        root.append(chat_scroll)

        # ---- collapsible history ----
        self.history_expander = Gtk.Expander(label="📜 历史记录")
        self.history_expander.connect("activate", self._on_history_toggle)
        history_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        history_box.set_margin_start(4)
        history_box.set_margin_end(4)
        history_box.set_margin_bottom(4)
        self.history_list = Gtk.ListBox()
        self.history_list.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.history_list.connect("row-activated", self._on_history_activated)
        history_scroll = Gtk.ScrolledWindow()
        history_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        history_scroll.set_min_content_height(80)
        history_scroll.set_max_content_height(200)
        history_scroll.set_child(self.history_list)
        history_box.append(history_scroll)
        btn_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        clear_btn = Gtk.Button(label="清空历史")
        clear_btn.connect("clicked", self._on_history_clear)
        btn_row.append(clear_btn)
        history_box.append(btn_row)
        self.history_expander.set_child(history_box)
        root.append(self.history_expander)

        # ---- input row ----
        input_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        input_box.set_margin_top(8)
        input_box.set_margin_bottom(8)
        input_box.set_margin_start(8)
        input_box.set_margin_end(8)
        root.append(input_box)

        self.entry = Gtk.Entry()
        self.entry.set_placeholder_text("向 AI 提问（Ctrl+Enter 发送）…")
        self.entry.connect("activate", self._on_send)
        key_controller = Gtk.EventControllerKey()
        key_controller.connect("key-pressed", self._on_entry_key)
        self.entry.add_controller(key_controller)
        self.entry.add_css_class("chat-entry")
        self.entry.set_hexpand(True)
        input_box.append(self.entry)

        self.send_btn = Gtk.Button(label="发送")
        self.send_btn.connect("clicked", self._on_send)
        input_box.append(self.send_btn)

        self.stop_btn = Gtk.Button(label="停止")
        self.stop_btn.set_sensitive(False)
        self.stop_btn.connect("clicked", self._on_stop)
        input_box.append(self.stop_btn)

    # ----------------------------------------------------------- attachment
    def add_attachment(self, path):
        path = os.path.abspath(os.path.expanduser(path))
        if not os.path.exists(path):
            self._append_ai(f"警告：附件不存在，已忽略 —— {path}\n")
            return
        if any(full == path for _, full in self.attachments):
            return
        name = os.path.basename(path.rstrip("/")) or path
        self.attachments.append((name, path))
        self._render_attachments()

    def remove_attachment(self, path):
        self.attachments = [(n, p) for n, p in self.attachments if p != path]
        self._render_attachments()

    def _render_attachments(self):
        self._attach_list.remove_all()
        self._attach_list.set_visible(bool(self.attachments))
        for name, path in self.attachments:
            row = Gtk.ListBoxRow()
            box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            box.set_margin_top(3)
            box.set_margin_bottom(3)
            icon = Gtk.Image.new_from_icon_name(
                "folder-symbolic" if os.path.isdir(path) else "text-x-generic-symbolic")
            icon.set_pixel_size(16)
            box.append(icon)
            label = Gtk.Label(label=f"{name}  ({path})")
            label.set_halign(Gtk.Align.START)
            label.set_ellipsize(Pango.EllipsizeMode.MIDDLE)
            label.set_hexpand(True)
            label.add_css_class("chat-path-chip")
            box.append(label)
            rm = Gtk.Button.new_from_icon_name("window-close-symbolic")
            rm.add_css_class("flat")
            rm.set_tooltip_text("移除附件")
            rm.connect("clicked", self._on_remove_clicked, path)
            box.append(rm)
            row.set_child(box)
            self._attach_list.append(row)

    def _on_attach_clicked(self, _btn):
        if self.attachments and os.path.isdir(self.attachments[-1][1]):
            initial = Gio.File.new_for_path(self.attachments[-1][1])
        else:
            initial = Gio.File.new_for_path(os.path.expanduser("~"))
        dialog = Gtk.FileDialog(title="选择要附加到 AI 的文件/文件夹")
        dialog.set_accept_label("添加附件")
        dialog.set_initial_folder(initial)
        dialog.open_multiple(self, self._on_filechooser_response)

    def _on_filechooser_response(self, dialog, result):
        try:
            files = dialog.open_multiple_finish(result)
        except GLib.Error:
            return
        for f in files:
            path = f.get_path()
            if path:
                self.add_attachment(path)

    def _on_remove_clicked(self, _btn, path):
        self.remove_attachment(path)

    # ------------------------------------------------------------- actions
    def _on_send(self, _widget=None):
        if self._sending:
            return
        text = self.entry.get_text().strip()
        if not text:
            return
        self.entry.set_text("")
        display_paths = [p for _, p in self.attachments]
        prompt = text
        if display_paths:
            prompt += "\n\n[附件]\n" + "\n".join(f"- {p}" for p in display_paths)
        self._append_user(text, display_paths)
        self._history_messages.append({"role": "user", "content": text, "paths": display_paths})
        self._ai_buffer = ""
        self._start_aim(prompt)

    def _on_entry_key(self, _controller, keyval, _keycode, state):
        if keyval == Gdk.KEY_Return and state & Gdk.ModifierType.CONTROL_MASK:
            self._on_send()
            return True
        return False

    def _on_new_conversation(self, _widget):
        self._stop_current()
        self._save_current_to_history()
        self.chat_buf.set_text("")
        self.attachments = []
        self._render_attachments()
        self._first_message = True
        self._history_messages = []
        self._append_ai("已开启全新对话。\n")

    def _on_stop(self, _widget):
        self._stop_current()

    # ------------------------------------------------------------- history
    def _on_history_toggle(self, expander):
        if expander.get_expanded():
            self._refresh_history_ui()

    def _refresh_history_ui(self):
        self.history_list.remove_all()
        records = load_history()
        if not records:
            row = Gtk.ListBoxRow()
            lbl = Gtk.Label(label="暂无历史记录")
            lbl.set_halign(Gtk.Align.START)
            lbl.set_margin_start(8); lbl.set_margin_end(8); lbl.set_margin_top(4); lbl.set_margin_bottom(4)
            lbl.add_css_class("dim-label")
            row.set_child(lbl)
            self.history_list.append(row)
            return
        for rec in records:
            row = Gtk.ListBoxRow()
            box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            box.set_margin_start(8); box.set_margin_end(8); box.set_margin_top(4); box.set_margin_bottom(4)
            ts = rec.get("time", "")
            title = rec.get("title", "对话")
            lbl = Gtk.Label(label=f"{ts}  {title}")
            lbl.set_halign(Gtk.Align.START)
            lbl.set_ellipsize(True)
            lbl.set_hexpand(True)
            box.append(lbl)
            row.set_child(box)
            row.record = rec
            self.history_list.append(row)

    def _on_history_activated(self, _listbox, row):
        rec = getattr(row, "record", None)
        if not rec:
            return
        self._stop_current()
        self._save_current_to_history()
        self.chat_buf.set_text("")
        self.attachments = []
        self._render_attachments()
        self._first_message = True
        self._history_messages = []
        for msg in rec.get("messages", []):
            role = msg.get("role", "user")
            content = msg.get("content", "")
            paths = msg.get("paths", [])
            if role == "user":
                self._append_user(content, paths)
                self._history_messages.append({"role": "user", "content": content, "paths": paths})
            else:
                self._append_ai(content + "\n\n")
                self._history_messages.append({"role": "assistant", "content": content})

    def _on_history_clear(self, _btn):
        save_history([])
        self._refresh_history_ui()

    def _save_current_to_history(self):
        if not self._history_messages:
            return
        title = ""
        for m in self._history_messages:
            if m.get("role") == "user":
                title = m["content"][:40]
                break
        if not title:
            title = "对话"
        add_history({
            "title": title,
            "time": time.strftime("%Y-%m-%d %H:%M:%S"),
            "messages": self._history_messages,
        })
        self._history_messages = []

    # ------------------------------------------------------------- backend
    def _start_aim(self, prompt):
        if not os.path.isfile(AIM_BIN):
            self._append_ai(f"错误：找不到 {AIM_BIN}，请先安装 aim。\n")
            return
        mode = "newrun" if self._first_message else "run"
        cmd = [AIM_BIN, mode, prompt]
        self._first_message = False
        self._append_ai(f"（{mode} 中…）\n")
        self._append_ai("")
        self._set_sending(True)

        proc = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, bufsize=1, start_new_session=True)
        self._proc = proc
        self._stop_flag.clear()

        def read_stream(stream, is_stderr):
            for line in stream:
                if is_stderr:
                    self._msg_queue.put(("stderr", line))
                else:
                    self._msg_queue.put(("chunk", line))
            stream.close()

        t_out = threading.Thread(target=read_stream, args=(proc.stdout, False), daemon=True)
        t_err = threading.Thread(target=read_stream, args=(proc.stderr, True), daemon=True)
        t_out.start()
        t_err.start()

        def waiter():
            proc.wait()
            self._msg_queue.put(("done", proc.returncode))
        threading.Thread(target=waiter, daemon=True).start()

    def _stop_current(self):
        if self._proc and self._proc.poll() is None:
            self._stop_flag.set()
            try:
                os.killpg(os.getpgid(self._proc.pid), 9)
            except Exception:
                try:
                    self._proc.kill()
                except Exception:
                    pass

    def _set_sending(self, sending):
        self._sending = sending
        GLib.idle_add(self._update_buttons, sending)

    def _update_buttons(self, sending):
        self.send_btn.set_sensitive(not sending)
        self.stop_btn.set_sensitive(sending)
        return False

    # -------------------------------------------------------------- render
    def _append_user(self, text, paths):
        it = self.chat_buf.get_end_iter()
        header = f"── {USER_TAG}"
        if paths:
            header += "  📎 " + " · ".join(os.path.basename(p) for p in paths)
        header += " ──\n"
        self.chat_buf.insert(it, header)
        it = self.chat_buf.get_end_iter()
        self.chat_buf.insert(it, text + "\n\n")

    def _append_ai(self, text):
        it = self.chat_buf.get_end_iter()
        self.chat_buf.insert(it, text)
        self._scroll_to_end()

    def _scroll_to_end(self):
        mark = self.chat_buf.create_mark(None, self.chat_buf.get_end_iter(), False)
        self.chat_view.scroll_to_mark(mark, 0.0, False, 0.0, 0.0)
        self.chat_buf.delete_mark(mark)

    def _raise_window(self):
        self.present()
        return False

    def _drain_queue(self):
        try:
            while True:
                kind, payload = self._msg_queue.get_nowait()
                if kind == "chunk":
                    self._ai_buffer += payload
                    self._append_ai(payload)
                elif kind == "stderr":
                    self._append_ai(payload)
                elif kind == "done":
                    self._set_sending(False)
                    rc = payload
                    it = self.chat_buf.get_end_iter()
                    self.chat_buf.insert(it, "\n" if rc == 0 else f"\n[退出码 {rc}]\n")
                    if rc == 0 and self._ai_buffer.strip():
                        self._history_messages.append({"role": "assistant", "content": self._ai_buffer.strip()})
                        self._save_current_to_history()
                    self._ai_buffer = ""
        except queue.Empty:
            pass
        return True

    # ---------------------------------------------------------- singleton
    def _start_socket_listener(self):
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            probe = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            probe.connect(SOCKET_PATH)
            probe.close()
            sock.close()
            return
        except OSError:
            try:
                os.unlink(SOCKET_PATH)
            except OSError:
                pass
        try:
            sock.bind(SOCKET_PATH)
        except OSError:
            sock.close()
            return
        sock.listen(8)
        self._sock = sock

        def loop():
            while True:
                try:
                    conn, _ = sock.accept()
                except OSError:
                    break
                data = conn.recv(65536)
                conn.close()
                if data:
                    for raw in data.decode("utf-8", "replace").splitlines():
                        p = raw.strip()
                        if p:
                            GLib.idle_add(self.add_attachment, p)
                    GLib.idle_add(self._raise_window)
        threading.Thread(target=loop, daemon=True).start()

    def _on_destroy(self, _win):
        self._stop_current()
        self._save_current_to_history()
        try:
            os.unlink(SOCKET_PATH)
        except OSError:
            pass


def send_paths_to_running_instance(paths):
    try:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.connect(SOCKET_PATH)
        sock.sendall("\n".join(paths).encode("utf-8"))
        sock.close()
        return True
    except OSError:
        return False


class AIChatApp(Gtk.Application):
    def __init__(self):
        super().__init__(application_id="org.chindows.ai-file-chat")
        self.initial_paths = []
        self.win = None

    def do_activate(self):
        if self.win is None:
            self.win = AIChatWindow(self, self.initial_paths)
        self.win.present()


def main():
    if chstyle:
        chstyle.apply_gtk4()
    paths = [os.path.abspath(p) for p in sys.argv[1:] if os.path.exists(p)]
    if paths and send_paths_to_running_instance(paths):
        return 0

    app = AIChatApp()
    app.initial_paths = paths
    try:
        GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, 2, lambda *a: app.quit())
        GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, 15, lambda *a: app.quit())
    except Exception:
        pass
    return app.run(None)


if __name__ == "__main__":
    sys.exit(main())
