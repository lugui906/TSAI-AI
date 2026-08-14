import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
from gi.repository import Gdk, Gio, GLib, Gtk

from accel import AcceleratorManager
from backend import AimBackend
from capture import run_screenshot
import subprocess
import threading
import ipc

CSS = """
.chat-list { background: transparent; }
.bubble {
    border-radius: 14px;
    padding: 10px 14px;
    margin-top: 4px;
    margin-bottom: 4px;
}
.bubble.user { background: #2d7ff9; color: white; }
.bubble.ai   { background: #eceff4; color: #1c1c1e; }
.bubble.error { background: #f4b0b0; color: #5c1515; }
.bubble.thinking { background: #f2f2f2; color: #888; }
.attach-box { background: alpha(currentColor, 0.08); border-radius: 12px; padding: 8px; }
.thumb { border-radius: 10px; }
.status { color: alpha(currentColor, 0.6); }
.user-row { background: transparent; }
.ai-row { background: transparent; }
"""


class AssistantWindow(Gtk.ApplicationWindow):
    def __init__(self, app, start_hidden=False):
        self._app = app
        super().__init__(application=app)
        self.set_title("AI 助手")
        self.set_default_size(560, 740)
        self.set_size_request(380, 480)

        self.attachments = []
        self._shot_active = False
        self._stream_label = None
        self._stream_text = ""
        self._tree_text = None

        self._build_header()
        self._build_body()

        self.connect("close-request", self.on_close_request)
        if not start_hidden:
            self.present()

    # ---------- 构建 ----------

    def _build_header(self):
        hb = Gtk.HeaderBar()
        hb.set_title_widget(Gtk.Label(label="AI 助手"))
        btn_new = Gtk.Button(label="新对话")
        btn_new.connect("clicked", lambda *a: self.on_new_chat())
        hb.pack_start(btn_new)
        btn_ctxt = Gtk.Button(label="上下文")
        btn_ctxt.connect("clicked", lambda *a: self.do_context())
        hb.pack_end(btn_ctxt)
        btn_shot = Gtk.Button(label="截图")
        btn_shot.connect("clicked", lambda *a: self.do_screenshot())
        hb.pack_end(btn_shot)
        self.set_titlebar(hb)

    def _build_body(self):
        self.chat_list = Gtk.ListBox()
        self.chat_list.set_selection_mode(Gtk.SelectionMode.NONE)
        self.chat_list.add_css_class("chat-list")
        self.chat_sw = Gtk.ScrolledWindow()
        self.chat_sw.set_vexpand(True)
        self.chat_sw.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.chat_sw.set_child(self.chat_list)

        self.attach_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.attach_box.add_css_class("attach-box")
        attach_sw = Gtk.ScrolledWindow()
        attach_sw.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.NEVER)
        attach_sw.set_max_content_height(96)
        attach_sw.set_vexpand(False)
        attach_sw.set_child(self.attach_box)

        self.entry = Gtk.TextView()
        self.entry.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        self.entry.set_vexpand(True)
        self.entry.set_size_request(-1, 72)
        self.entry.set_left_margin(6)
        self.entry.set_top_margin(4)
        self.entry.set_bottom_margin(4)
        ctrl = Gtk.EventControllerKey.new()
        ctrl.connect("key-pressed", self.on_key_pressed)
        self.entry.add_controller(ctrl)
        entry_sw = Gtk.ScrolledWindow()
        entry_sw.set_vexpand(False)
        entry_sw.set_child(self.entry)

        hint = Gtk.Label(label="Enter 发送，Shift+Enter 换行；可直接附加图片，或附带问题一起发送")
        hint.set_halign(Gtk.Align.START)
        hint.add_css_class("status")

        btn_send = Gtk.Button(label="发送")
        btn_send.add_css_class("suggested-action")
        btn_send.connect("clicked", lambda *a: self.send())

        self.status_label = Gtk.Label(label="就绪")
        self.status_label.set_halign(Gtk.Align.START)
        self.status_label.add_css_class("status")

        bottom = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        bottom.append(attach_sw)
        bottom.append(hint)
        bottom.append(entry_sw)
        bottom.append(btn_send)
        bottom.append(self.status_label)

        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        content.set_margin_top(8)
        content.set_margin_bottom(8)
        content.set_margin_start(8)
        content.set_margin_end(8)
        content.append(self.chat_sw)
        content.append(bottom)
        self.set_child(content)

    # ---------- 消息 ----------

    def add_bubble(self, who, text, css=None):
        label = Gtk.Label(label=text or "")
        label.set_wrap(True)
        label.set_selectable(True)
        label.set_xalign(0.0)
        label.set_max_width_chars(52)
        label.add_css_class("bubble")
        label.add_css_class(who)
        if css:
            label.add_css_class(css)

        holder = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        holder.set_halign(Gtk.Align.END if who == "user" else Gtk.Align.START)
        holder.append(label)

        row = Gtk.ListBoxRow()
        row.set_activatable(False)
        row.set_selectable(False)
        row.set_child(holder)
        self.chat_list.append(row)
        self.scroll_bottom()
        return label

    def send(self):
        if self._app.backend.busy:
            self.set_status("上一个请求仍在处理中…")
            return
        buf = self.entry.get_buffer()
        start, end = buf.get_bounds()
        question = buf.get_text(start, end, False).strip()
        if not question and not self.attachments:
            self.set_status("请输入问题，或先截图添加附件")
            return

        parts = []
        if question:
            parts.append(question)
        for att in self.attachments:
            parts.append("【图片】" + (f"\nOCR: {att['ocr']}" if att["ocr"] else ""))
        self.add_bubble("user", "\n\n".join(parts))

        files = [att["path"] for att in self.attachments]
        ocr_parts = [att["ocr"] for att in self.attachments if att["ocr"]]
        if question:
            prompt = question
        else:
            prompt = "请解读这张图片。"
        if ocr_parts:
            prompt += "\n\n以下是图片的OCR识别结果，请结合图片内容回答：\n" + "\n---\n".join(ocr_parts)
        if self._tree_text:
            header = "以下是桌面当前窗口的无障碍控件树(Accessibility Tree)，请结合这份界面上下文来回答用户的问题：\n\n"
            prompt = header + self._tree_text + "\n\n### 用户问题 ###\n" + prompt
            self._tree_text = None

        self._clear_attachments()
        buf.set_text("", -1)
        self.entry.grab_focus()

        self._stream_text = ""
        self._stream_label = self.add_bubble("ai", "思考中…", css="thinking")
        self.set_status("AI 思考中…")

        self._app.backend.send(
            prompt,
            files=files,
            new_conversation=self._app.new_chat,
            on_delta=lambda t: GLib.idle_add(lambda: self.stream_append(t)),
            on_done=lambda final: GLib.idle_add(lambda: self.stream_done(final)),
            on_error=lambda e: GLib.idle_add(lambda: self.stream_error(e)),
        )
        self._app.new_chat = False

    def stream_append(self, text):
        self._stream_text += text
        if self._stream_label:
            self._stream_label.remove_css_class("thinking")
            self._stream_label.set_label(self._stream_text)
            self.scroll_bottom()
        return False

    def stream_done(self, final):
        if final:
            self._stream_text = final
        self._stream_label.remove_css_class("thinking")
        self._stream_label.set_label(self._stream_text or "（无输出）")
        self._stream_label = None
        self.set_status("就绪")
        self.scroll_bottom()
        return False

    def stream_error(self, msg):
        if self._stream_label:
            self._stream_label.remove_css_class("thinking")
            self._stream_label.add_css_class("error")
            self._stream_label.set_label(f"出错了：{msg}")
            self._stream_label = None
        self.set_status("出错了")
        return False

    def on_new_chat(self):
        self._app.new_chat = True
        self._stream_label = None
        self._stream_text = ""
        self._tree_text = None
        while (child := self.chat_list.get_first_child()) is not None:
            self.chat_list.remove(child)
        self._clear_attachments()
        self.entry.get_buffer().set_text("", -1)
        self.entry.grab_focus()
        self.set_status("已开始新对话")

    # ---------- 附件 ----------

    def _clear_attachments(self):
        self.attachments = []
        while (child := self.attach_box.get_first_child()) is not None:
            self.attach_box.remove(child)

    def add_attachment(self, path, ocr):
        self.attachments.append({"path": path, "ocr": ocr})
        pic = Gtk.Picture.new_for_filename(path)
        pic.set_content_fit(Gtk.ContentFit.COVER)
        pic.set_size_request(84, 84)
        pic.add_css_class("thumb")

        rm = Gtk.Button(icon_name="window-close-symbolic")
        rm.add_css_class("circular")
        rm.set_valign(Gtk.Align.START)
        rm.set_halign(Gtk.Align.END)
        rm.set_tooltip_text("移除")
        rm.connect("clicked", lambda *a, p=path: self.remove_attachment(p))

        ov = Gtk.Overlay()
        ov.set_child(pic)
        ov.add_overlay(rm)
        ov.path = path
        self.attach_box.append(ov)
        self.scroll_bottom()

    def remove_attachment(self, path):
        self.attachments = [a for a in self.attachments if a["path"] != path]
        child = self.attach_box.get_first_child()
        while child is not None:
            nxt = child.get_next_sibling()
            if getattr(child, "path", None) == path:
                self.attach_box.remove(child)
            child = nxt
        if not self.attachments:
            self.set_status("就绪")

    # ---------- 截图 ----------

    def do_screenshot(self):
        if self._shot_active:
            return
        self._shot_active = True
        self.set_status("请框选要截取的区域…（Esc 取消）")
        self.hide()

        def start():
            run_screenshot(
                on_done=lambda p, o: GLib.idle_add(lambda: self.on_shot_done(p, o)),
                on_error=lambda e: GLib.idle_add(lambda: self.on_shot_error(e)),
            )
            return False

        GLib.timeout_add(600, start)

    def on_shot_done(self, path, ocr):
        self._shot_active = False
        try:
            self.add_attachment(path, ocr)
        except Exception:
            self.set_status("截图附件添加失败")
            return False
        self.present()
        self.entry.grab_focus()
        if ocr:
            self.set_status("已添加截图附件（OCR 识别完成）")
        else:
            self.set_status("已添加截图附件（未识别出文字）")
        self.scroll_bottom()
        return False

    def on_shot_error(self, msg):
        self._shot_active = False
        self.present()
        self.set_status(f"截图：{msg}")
        return False

    def do_context(self):
        if self._app.backend.busy:
            self.set_status("AI 正忙，请稍候再获取界面上下文")
            return
        self.set_status("正在读取界面元素…")
        self.present()

        def run_tree():
            try:
                result = subprocess.run(
                    ["tine", "tree"],
                    capture_output=True, text=True, timeout=30,
                )
            except FileNotFoundError:
                GLib.idle_add(lambda: self._on_context_done(None, "tine 未安装"))
                return
            except subprocess.TimeoutExpired:
                GLib.idle_add(lambda: self._on_context_done(None, "读取界面超时"))
                return
            except Exception as e:
                GLib.idle_add(lambda e=e: self._on_context_done(None, str(e)))
                return
            if result.returncode != 0:
                err = result.stderr.strip() or "tine tree 执行失败"
                GLib.idle_add(lambda: self._on_context_done(None, err))
                return
            output = result.stdout.strip()
            if not output:
                GLib.idle_add(lambda: self._on_context_done(None, "界面控件列表为空"))
                return
            GLib.idle_add(lambda: self._on_context_done(output, None))

        threading.Thread(target=run_tree, daemon=True).start()

    def _on_context_done(self, tree_text, error):
        if error:
            self.set_status(f"获取界面上下文失败：{error}")
            return
        self._tree_text = tree_text
        lines = tree_text.count("\n") + 1
        self.add_bubble("ai", f"已获取当前界面元素控件树（{lines} 行）。\n请直接输入你的问题，AI 将参照这些界面信息回答。")
        self.set_status(f"已捕获界面元素（{lines} 行）—— 请提问")
        self.scroll_bottom()
        return False

    # ---------- 快捷键 ----------

    def on_key_pressed(self, _ctrl, keyval, _keycode, state):
        if keyval in (Gdk.KEY_Return, Gdk.KEY_KP_Enter):
            if not (state & Gdk.ModifierType.SHIFT_MASK):
                self.send()
                return True
        return False

    def handle_ipc(self, cmd):
        print(f"[Window.handle_ipc] cmd={cmd!r}", flush=True)
        cmd = (cmd or "").strip().lstrip("-")
        if cmd == "wake":
            self.present()
            self.entry.grab_focus()
        elif cmd == "screenshot":
            self.present()
            GLib.timeout_add(150, lambda: (self.do_screenshot(), False)[1])
        elif cmd == "context":
            self.do_context()
        return False

    def on_close_request(self, *_a):
        self.hide()
        return True

    # ---------- 工具 ----------

    def set_status(self, text):
        self.status_label.set_label(text)

    def scroll_bottom(self):
        def do_scroll():
            adj = self.chat_sw.get_vadjustment()
            adj.set_value(adj.get_upper())
            return False

        GLib.idle_add(do_scroll)


class AssistantApp(Gtk.Application):
    def __init__(self, start_hidden=False, pending_cmd=None):
        super().__init__(
            application_id="com.local.AiAssistant",
            flags=Gio.ApplicationFlags.NON_UNIQUE,
        )
        self.backend = AimBackend()
        self.new_chat = True
        self.win = None
        self.start_hidden = start_hidden
        self.pending_cmd = pending_cmd
        self._ipc_server = None
        self._accel = None
        self._accel_ids = {}  # aid -> cmd

    def do_startup(self):
        Gtk.Application.do_startup(self)
        print("[App] do_startup", flush=True)
        try:
            provider = Gtk.CssProvider()
            provider.load_from_string(CSS)
            display = Gdk.Display.get_default()
            if display:
                Gtk.StyleContext.add_provider_for_display(
                    display, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
                )
        except Exception as e:
            print(f"[App] 样式加载失败: {e}", flush=True)

        # 通过 GNOME Shell D-Bus 接口注册全局快捷键
        self._accel = AcceleratorManager()
        if self._accel.is_available():
            self._accel.connect(self._on_accel_activated)
            for accel, cmd in (("<Alt>s", "wake"), ("<Alt>t", "screenshot"), ("<Alt>d", "context")):
                aid = self._accel.register(accel, cmd)
                if aid is not None:
                    self._accel_ids[aid] = cmd
            print(f"[App] 快捷键已通过 D-Bus 注册: {self._accel_ids}", flush=True)
        else:
            print("[App] GNOME Shell Accelerator 接口不可用，依赖 gsettings", flush=True)

    def do_shutdown(self):
        if self._accel:
            self._accel.unregister_all()
            self._accel = None
        Gtk.Application.do_shutdown(self)

    def _on_accel_activated(self, aid):
        cmd = self._accel_ids.get(aid)
        if cmd:
            print(f"[Accel] 快捷键触发: id={aid}, cmd={cmd}", flush=True)
            self._dispatch_ipc(cmd)

    def do_activate(self, *_a):
        print("[App] do_activate, win=%s, hidden=%s" % (self.win is not None, self.start_hidden), flush=True)
        if self.win is None:
            self.win = AssistantWindow(self, start_hidden=self.start_hidden)

            self._ipc_server = ipc.Server(self._dispatch_ipc)
            if not self._ipc_server.start():
                self._ipc_server = None
                print("[App] IPC 启动失败，仍将继续运行", flush=True)
        if self.start_hidden:
            self.hold()
        else:
            self.win.present()
        if self.pending_cmd:
            GLib.timeout_add(200, lambda: self._run_pending() or False)

    def _handle_bind_failure(self, ipc):
        if self.pending_cmd:
            def try_forward():
                if ipc.Client.send(self.pending_cmd):
                    self.quit()
                return False

            GLib.timeout_add(150, try_forward)
            self.pending_cmd = None

    def _dispatch_ipc(self, cmd):
        cmd = (cmd or "").strip().lstrip("-")
        print(f"[App._dispatch_ipc] cmd={cmd!r}, win={self.win is not None}", flush=True)
        if self.win is None:
            def activate_and_run():
                self.activate()
                self.pending_cmd = cmd
                return False
            GLib.idle_add(activate_and_run)
            return False
        GLib.idle_add(self.win.handle_ipc, cmd)
        return False

    def _run_pending(self):
        if self.win and self.pending_cmd:
            self.win.handle_ipc(self.pending_cmd)
            self.pending_cmd = None
        return False
