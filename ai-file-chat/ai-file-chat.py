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
import shutil

try:
    import gi
    gi.require_version("Gtk", "3.0")
    gi.require_version("Gdk", "3.0")
    gi.require_version("Pango", "1.0")
    from gi.repository import Gtk, Gdk, GLib, Pango, Gio
except ImportError:
    sys.stderr.write("Error: PyGObject required. sudo apt install python3-gi gir1.2-gtk-3.0\n")
    sys.exit(1)

AIM_BIN = os.environ.get("AIM_BIN") or shutil.which("aim") or "/usr/bin/aim"
SOCKET_PATH = "/tmp/ai-file-chat.sock"
WINDOW_WIDTH = 460

USER_TAG = "你"
AI_TAG = "AI"


class AIChatWindow(Gtk.ApplicationWindow):
    def __init__(self, app, initial_paths=None):
        super().__init__(application=app, title="AI 对话 · 文件附件", default_width=WINDOW_WIDTH)
        self.set_default_size(WINDOW_WIDTH, 720)

        self.attachments = []          # [(display_name, full_path)]
        self.attachment_store = None   # Gtk.ListStore for the chips list
        self._proc = None
        self._first_message = True
        self._stop_flag = threading.Event()
        self._msg_queue = queue.Queue()
        self._sending = False

        self._build_ui()
        self._position_right()
        GLib.idle_add(self._position_right)

        if initial_paths:
            for p in initial_paths:
                self.add_attachment(p)

        self._start_socket_listener()
        GLib.timeout_add(60, self._drain_queue)
        self.connect("destroy", self._on_destroy)

    # ------------------------------------------------------------------ UI
    def _build_ui(self):
        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.add(root)
        self.set_keep_above(True)

        css = Gtk.CssProvider()
        css.load_from_data(b"""
            .chat-ai-view text { background: #ffffff; color: #1a1a1a;
                                  font-family: "Noto Sans CJK SC"; font-size: 13px; }
            .chat-path-chip { background: #eef3ff; color: #1d4ed8; border-radius: 4px;
                              padding: 2px 8px; font-size: 12px; }
        """)
        Gtk.StyleContext.add_provider_for_screen(
            Gdk.Screen.get_default(), css,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

        toolbar = Gtk.HeaderBar(show_close_button=True)
        toolbar.set_title("AI 对话")
        toolbar.set_subtitle("右键文件 → AI 对话 · 附件随问题发送")
        self.set_titlebar(toolbar)

        attach_btn = Gtk.Button(label="＋ 附件")
        attach_btn.connect("clicked", self._on_attach_clicked)
        toolbar.pack_start(attach_btn)

        new_conv_btn = Gtk.Button(label="新对话")
        new_conv_btn.set_tooltip_text("清空记录并开启全新对话")
        new_conv_btn.connect("clicked", self._on_new_conversation)
        toolbar.pack_end(new_conv_btn)

        # ---- attachments list ----
        attach_frame = Gtk.Frame(visible=True)
        attach_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        attach_box.set_border_width(6)
        attach_frame.add(attach_box)
        root.pack_start(attach_frame, expand=False, fill=True, padding=0)

        self.attachment_store = Gtk.ListStore(str, str)
        attach_list = Gtk.ListBox()
        attach_list.set_selection_mode(Gtk.SelectionMode.NONE)
        attach_list.set_visible(False)

        attach_scroll = Gtk.ScrolledWindow()
        attach_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        attach_scroll.set_max_content_height(160)
        attach_scroll.add(attach_list)
        attach_box.pack_start(attach_scroll, expand=False, fill=True, padding=0)

        self._attach_list = attach_list
        self._attach_frame = attach_frame
        self._attach_box = attach_box

        # ---- chat view ----
        self.chat_view = Gtk.TextView()
        self.chat_view.set_editable(False)
        self.chat_view.set_cursor_visible(True)
        self.chat_view.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        self.chat_view.get_style_context().add_class("chat-ai-view")
        self.chat_buf = self.chat_view.get_buffer()

        chat_scroll = Gtk.ScrolledWindow()
        chat_scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        chat_scroll.set_size_request(WINDOW_WIDTH - 60, 200)
        chat_scroll.add(self.chat_view)
        root.pack_start(chat_scroll, expand=True, fill=True, padding=0)

        # ---- input row ----
        input_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        input_box.set_border_width(8)
        root.pack_end(input_box, expand=False, fill=True, padding=0)

        self.entry = Gtk.Entry()
        self.entry.set_placeholder_text("向 AI 提问（Ctrl+Enter 发送）…")
        self.entry.connect("activate", self._on_send)
        self.entry.connect("key-press-event", self._on_entry_key)
        self.entry.get_style_context().add_class("chat-entry")
        input_box.pack_start(self.entry, expand=True, fill=True, padding=0)

        self.send_btn = Gtk.Button(label="发送")
        self.send_btn.set_can_default(True)
        self.send_btn.connect("clicked", self._on_send)
        input_box.pack_start(self.send_btn, expand=False, fill=True, padding=0)

        self.stop_btn = Gtk.Button(label="停止")
        self.stop_btn.set_sensitive(False)
        self.stop_btn.connect("clicked", self._on_stop)
        input_box.pack_start(self.stop_btn, expand=False, fill=True, padding=0)

        self.show_all()

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
        for child in self._attach_list.get_children():
            self._attach_list.remove(child)
        self._attach_list.set_visible(bool(self.attachments))
        for name, path in self.attachments:
            row = Gtk.ListBoxRow()
            box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            box.set_border_width(3)
            icon = Gtk.Image.new_from_icon_name(
                "folder-symbolic" if os.path.isdir(path) else "text-x-generic-symbolic",
                Gtk.IconSize.MENU)
            box.pack_start(icon, expand=False, fill=False, padding=0)
            label = Gtk.Label(label=f"{name}  ({path})", xalign=0.0, ellipsize=Pango.EllipsizeMode.MIDDLE)
            label.get_style_context().add_class("chat-path-chip")
            box.pack_start(label, expand=True, fill=True, padding=0)
            rm = Gtk.Button.new_from_icon_name("window-close-symbolic", Gtk.IconSize.MENU)
            rm.set_relief(Gtk.ReliefStyle.NONE)
            rm.set_tooltip_text("移除附件")
            rm.connect("clicked", self._on_remove_clicked, path)
            box.pack_start(rm, expand=False, fill=False, padding=0)
            row.add(box)
            self._attach_list.add(row)
        self._attach_list.show_all()

    def _on_attach_clicked(self, _btn):
        dlg = Gtk.FileChooserDialog(
            title="选择要附加到 AI 的文件/文件夹", transient_for=self,
            action=Gtk.FileChooserAction.OPEN, select_multiple=True)
        dlg.add_buttons(Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL,
                        "添加附件", Gtk.ResponseType.OK)
        if self.attachments and os.path.isdir(self.attachments[-1][1]):
            dlg.set_current_folder(self.attachments[-1][1])
        else:
            dlg.set_current_folder(os.path.expanduser("~"))
        if dlg.run() == Gtk.ResponseType.OK:
            for f in dlg.get_filenames():
                self.add_attachment(f)
        dlg.destroy()

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
        self._start_aim(prompt)

    def _on_entry_key(self, _widget, event):
        if event.keyval == Gdk.KEY_Return and event.state & Gdk.ModifierType.CONTROL_MASK:
            self._on_send()
            return True
        return False

    def _on_new_conversation(self, _widget):
        self._stop_current()
        self.chat_buf.set_text("")
        self.attachments = []
        self._render_attachments()
        self._first_message = True
        self._append_ai("已开启全新对话。\n")

    def _on_stop(self, _widget):
        self._stop_current()

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

    def _position_right(self):
        display = self.get_display()
        if display is None:
            return False
        monitor = display.get_primary_monitor()
        if monitor is None:
            return False
        wa = monitor.get_workarea()
        w, h = self.get_size()
        if w <= 1 or h <= 1:
            return True
        margin = 6
        self.move(wa.x + wa.width - w - margin, wa.y + margin)
        return False

    def _raise_window(self):
        self.present()
        self.set_keep_above(True)
        return False

    def _drain_queue(self):
        try:
            while True:
                kind, payload = self._msg_queue.get_nowait()
                if kind == "chunk":
                    self._append_ai(payload)
                elif kind == "stderr":
                    self._append_ai(payload)
                elif kind == "done":
                    self._set_sending(False)
                    rc = payload
                    it = self.chat_buf.get_end_iter()
                    self.chat_buf.insert(it, "\n" if rc == 0 else f"\n[退出码 {rc}]\n")
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

    def do_activate(self):
        win = AIChatWindow(self, self.initial_paths)
        self.win = win
        win.show_all()
        win.present()


def main():
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
