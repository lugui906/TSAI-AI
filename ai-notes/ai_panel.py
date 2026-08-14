import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
from gi.repository import Gtk, Gdk, GLib, GObject

from aim_engine import AimSession
import datetime


ACTION_PROMPTS = {
    "改写": "请改写以下文本，保持原意但改进表达：\n\n{text}",
    "翻译成中文": "请将以下文本翻译成中文：\n\n{text}",
    "翻译成英文": "请将以下文本翻译成英文：\n\n{text}",
    "续写": "请续写以下文本：\n\n{text}",
    "总结": "请总结以下文本的要点：\n\n{text}",
    "扩写": "请详细扩写以下文本：\n\n{text}",
    "简化": "请简化以下文本，使其更易读：\n\n{text}",
}


class AiPanel(Gtk.Box):
    __gsignals__ = {
        "insert-text": (GObject.SignalFlags.RUN_FIRST, None, (str,)),
        "replace-text": (GObject.SignalFlags.RUN_FIRST, None, (str,)),
        "replace-full-text": (GObject.SignalFlags.RUN_FIRST, None, (str,)),
    }

    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.session = AimSession.new_session()
        self.messages = []
        self._waiting = False
        self._context_text = ""
        self._full_doc = ""
        self._pending_mode = ""
        self._debug_visible = False
        self._debug_log = []
        self._build_ui()

    def _build_ui(self):
        header_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        header_box.set_margin_top(8)
        header_box.set_margin_start(8)
        header_box.set_margin_end(8)

        header = Gtk.Label(label="AI 助手")
        header.add_css_class("heading")
        header.set_hexpand(True)
        header.set_xalign(0)
        header_box.append(header)

        self._debug_btn = Gtk.ToggleButton(label="🐞")
        self._debug_btn.set_tooltip_text("显示调试面板")
        self._debug_btn.connect("toggled", self._on_debug_toggle)
        header_box.append(self._debug_btn)

        self.append(header_box)

        self._context_frame = Gtk.Frame()
        self._context_frame.set_margin_start(8)
        self._context_frame.set_margin_end(8)
        self._context_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self._context_box.set_margin_start(6)
        self._context_box.set_margin_end(6)
        self._context_box.set_margin_top(4)
        self._context_box.set_margin_bottom(4)
        self._context_label = Gtk.Label(label="未选中文本")
        self._context_label.set_xalign(0)
        self._context_label.set_wrap(True)
        self._context_label.set_max_width_chars(30)
        self._context_box.append(self._context_label)
        self._context_frame.set_child(self._context_box)
        self._context_frame.set_visible(False)
        self.append(self._context_frame)

        self._scrolled = Gtk.ScrolledWindow()
        self._scrolled.set_vexpand(True)

        self.message_list = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.message_list.set_margin_start(8)
        self.message_list.set_margin_end(8)
        self.message_list.set_margin_top(4)
        self.message_list.set_margin_bottom(4)
        self._scrolled.set_child(self.message_list)
        self.append(self._scrolled)

        actions = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        actions.set_margin_start(8)
        actions.set_margin_end(8)
        actions.set_homogeneous(True)
        for label in ("改写", "翻译成中文", "翻译成英文", "总结"):
            btn = Gtk.Button(label=label)
            btn.connect("clicked", self._on_action, label)
            btn.add_css_class("small-button")
            actions.append(btn)
        self.append(actions)

        actions2 = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        actions2.set_margin_start(8)
        actions2.set_margin_end(8)
        actions2.set_homogeneous(True)
        for label in ("续写", "扩写", "简化", "全文改写"):
            btn = Gtk.Button(label=label)
            btn.connect("clicked", self._on_action, label)
            btn.add_css_class("small-button")
            actions2.append(btn)
        self.append(actions2)

        actions3 = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        actions3.set_margin_start(8)
        actions3.set_margin_end(8)
        actions3.set_homogeneous(True)
        for label in ("全文总结", "全文翻译", "自定义"):
            btn = Gtk.Button(label=label)
            btn.connect("clicked", self._on_action, label)
            btn.add_css_class("small-button")
            actions3.append(btn)
        self.append(actions3)

        input_bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        input_bar.set_margin_start(8)
        input_bar.set_margin_end(8)
        input_bar.set_margin_bottom(8)

        self.entry = Gtk.TextView()
        self.entry.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        self.entry.set_accepts_tab(False)
        self.entry.set_size_request(-1, 50)
        self.entry_buffer = self.entry.get_buffer()

        input_frame = Gtk.Frame()
        input_frame.set_child(self.entry)
        input_frame.set_hexpand(True)

        send_button = Gtk.Button(label="发送")
        send_button.add_css_class("suggested-action")
        send_button.connect("clicked", self._on_send)

        send_key = Gtk.EventControllerKey.new()
        send_key.connect("key-pressed", self._on_key_pressed)
        self.entry.add_controller(send_key)

        input_bar.append(input_frame)
        input_bar.append(send_button)
        self.append(input_bar)

        self._debug_revealer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self._debug_revealer.set_visible(False)
        debug_header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        debug_header.set_margin_start(8)
        debug_header.set_margin_end(8)
        debug_header.set_margin_top(2)
        debug_header.set_margin_bottom(2)
        dl = Gtk.Label(label="调试日志")
        dl.add_css_class("dim-label")
        dl.set_xalign(0)
        dl.set_hexpand(True)
        debug_header.append(dl)
        clear_btn = Gtk.Button(label="清空")
        clear_btn.connect("clicked", self._on_debug_clear)
        debug_header.append(clear_btn)
        self._debug_revealer.append(debug_header)

        self._debug_scrolled = Gtk.ScrolledWindow()
        self._debug_scrolled.set_size_request(-1, 150)
        self._debug_scrolled.set_vexpand(False)
        self._debug_view = Gtk.TextView()
        self._debug_view.set_editable(False)
        self._debug_view.set_monospace(True)
        self._debug_view.set_wrap_mode(Gtk.WrapMode.CHAR)
        self._debug_view.set_left_margin(4)
        self._debug_view.set_right_margin(4)
        self._debug_view.add_css_class("debug-log")
        self._debug_buffer = self._debug_view.get_buffer()
        self._debug_scrolled.set_child(self._debug_view)
        self._debug_revealer.append(self._debug_scrolled)
        self.append(self._debug_revealer)

    def _on_debug_toggle(self, btn):
        self._debug_visible = btn.get_active()
        self._debug_revealer.set_visible(self._debug_visible)

    def _on_debug_clear(self, *args):
        self._debug_buffer.set_text("")
        self._debug_log.clear()

    def _on_debug_log(self, kind, msg):
        self._debug_log.append((kind, msg))
        if not self._debug_visible:
            return
        ts = datetime.datetime.now().strftime("%H:%M:%S")
        emoji = {"cmd": "⚡", "event": "📩", "done": "✅", "error": "❌", "session": "🔑", "pid": "🔢", "warn": "⚠️"}
        e = emoji.get(kind, "•")
        line = f"{ts} {e} [{kind}] {msg}\n"
        end = self._debug_buffer.get_end_iter()
        self._debug_buffer.insert(end, line)
        adj = self._debug_scrolled.get_vadjustment()
        if adj:
            GLib.idle_add(lambda: adj.set_value(adj.get_upper() - adj.get_page_size()))

    def set_context(self, text):
        self._context_text = text
        if text.strip():
            self._context_frame.set_visible(True)
            display = text[:150] + ("..." if len(text) > 150 else "")
            self._context_label.set_markup(f"<b>选中文本:</b>\n{GLib.markup_escape_text(display)}")
        else:
            self._context_frame.set_visible(False)

    def set_full_doc(self, text):
        self._full_doc = text

    def _on_key_pressed(self, controller, keyval, keycode, state):
        if keyval == Gdk.KEY_Return and not (state & Gdk.ModifierType.SHIFT_MASK):
            self._on_send()
            return True
        return False

    def _on_send(self, *args):
        if self._waiting:
            return
        buffer = self.entry.get_buffer()
        start = buffer.get_start_iter()
        end = buffer.get_end_iter()
        text = buffer.get_text(start, end, False).strip()
        if not text:
            return
        buffer.set_text("")
        self._pending_mode = "chat"
        self._send_to_ai(text, mode="chat")

    def _on_action(self, button, action_name):
        if self._waiting:
            return
        if action_name == "自定义":
            return
        if action_name == "全文改写":
            doc = getattr(self, "_full_doc", "")
            if not doc.strip():
                self._add_message("没有打开的文档", "system")
                return
            self._pending_mode = "full"
            message = "请完整改写以下文档，改进表达和结构：\n---\n" + doc + "\n---"
            self._add_message("[全文改写]", "user")
            self._send_to_ai(message, mode="full")
            return
        if action_name in ("全文总结", "全文翻译"):
            doc = getattr(self, "_full_doc", "")
            if not doc.strip():
                self._add_message("没有打开的文档", "system")
                return
            prompt_map = {"全文总结": "请总结以下文档的要点：\n---\n{doc}\n---", "全文翻译": "请将以下文档翻译成中文：\n---\n{doc}\n---"}
            message = prompt_map[action_name].format(doc=doc)
            self._pending_mode = "full"
            self._add_message(f"[{action_name}]", "user")
            self._send_to_ai(message, mode="full")
            return
        prompt = ACTION_PROMPTS.get(action_name)
        if not self._context_text.strip():
            self._add_message("请先在编辑器中选择文本", "system")
            return
        message = prompt.format(text=self._context_text)
        self._pending_mode = "selection"
        self._add_message(f"[{action_name}] {self._context_text[:50]}...", "user")
        self._send_to_ai(message, mode="selection")

    def _send_to_ai(self, text, mode="chat"):
        full_text = text
        doc = getattr(self, "_full_doc", "")
        if doc.strip():
            if mode == "selection":
                context = f"当前文档内容：\n---\n{doc}\n---\n\n用户选中了以下文本，请按要求处理并只输出处理后的文本（不要包含文档其他部分）：\n{text}"
            else:
                context = f"当前文档内容：\n---\n{doc}\n---\n\n用户指令：{text}\n\n请根据指令输出完整的文档内容（包含所有修改后的完整文档，不要只输出修改部分）。"
            full_text = context
        self._add_message(text, "user")
        self._waiting = True
        self._show_loading()
        self.session.send(full_text, on_data=self._on_stream, on_done=self._on_done, on_error=self._on_error, on_debug=self._on_debug_log)

    def _add_message(self, text, role):
        label = Gtk.Label()
        import html
        safe = html.escape(text)
        prefix = "🧑 " if role == "user" else "🤖 " if role == "assistant" else "⚠️ " if role == "system" else ""
        label.set_markup(f"<b>{prefix}</b>{safe}")
        label.set_selectable(True)
        label.set_wrap(True)
        label.set_xalign(0.0)
        label.set_margin_start(8 if role == "assistant" else 0)
        label.set_margin_end(8 if role == "user" else 0)

        frame = Gtk.Frame()
        frame.set_child(label)
        frame.add_css_class("message-frame")
        frame.add_css_class(f"message-{role}" if role in ("user", "assistant") else "message-system")

        self.message_list.append(frame)
        self.messages.append({"role": role, "text": text})
        self._scroll_to_bottom()

    def _show_loading(self):
        self._streaming_text = ""
        self._loading_label = Gtk.Label(label="思考中...")
        self._loading_label.add_css_class("loading-label")
        self._loading_label.set_margin_start(8)
        self._loading_label.set_selectable(True)
        self._loading_label.set_wrap(True)
        self._loading_label.set_xalign(0.0)
        self.message_list.append(self._loading_label)
        self._scroll_to_bottom()

    def _remove_loading(self):
        if self._loading_label is None:
            return
        parent = self._loading_label.get_parent()
        if parent:
            self.message_list.remove(self._loading_label)
        self._loading_label = None
        self._streaming_text = None

    def _on_stream(self, chunk):
        GLib.idle_add(self._append_stream, chunk)

    def _on_done(self, full_text):
        GLib.idle_add(self._finish_response, full_text)

    def _on_error(self, error):
        GLib.idle_add(self._show_error, error)

    def _append_stream(self, chunk):
        if self._loading_label is None:
            return
        self._streaming_text += chunk
        import html
        safe = html.escape(self._streaming_text)
        self._loading_label.set_markup(f"<b>🤖 </b>{safe}")

    def _finish_response(self, full_text):
        self._remove_loading()
        text = full_text.strip()
        if text:
            self._add_message(text, "assistant")
            mode = getattr(self, "_pending_mode", "")
            if mode == "selection":
                self.emit("replace-text", text)
            else:
                self.emit("replace-full-text", text)
        self._waiting = False
        self._pending_mode = ""

    def _show_error(self, error):
        self._remove_loading()
        self._add_message(str(error), "system")
        self._waiting = False

    def _scroll_to_bottom(self):
        adj = self._scrolled.get_vadjustment()
        if adj is not None:
            GLib.idle_add(lambda: adj.set_value(adj.get_upper() - adj.get_page_size()))
