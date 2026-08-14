import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
from gi.repository import Gtk, Gdk, GLib, GObject

from aim_engine import AimSession


class ConversationPage(Gtk.Box):
    __gsignals__ = {
        "title-changed": (GObject.SignalFlags.RUN_FIRST, None, (str,)),
    }

    def __init__(self, session=None):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.session = session or AimSession.new_session()
        self.messages = []
        self._waiting = False
        self._title_set = False
        self._build_ui()

    def _build_ui(self):
        self._scrolled = Gtk.ScrolledWindow()
        self._scrolled.set_vexpand(True)

        self.message_list = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.message_list.set_margin_start(12)
        self.message_list.set_margin_end(12)
        self.message_list.set_margin_top(12)
        self.message_list.set_margin_bottom(12)

        self._scrolled.set_child(self.message_list)

        input_bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        input_bar.set_margin_start(12)
        input_bar.set_margin_end(12)
        input_bar.set_margin_bottom(12)

        self.entry = Gtk.TextView()
        self.entry.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        self.entry.set_accepts_tab(False)
        self.entry.set_size_request(-1, 60)
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

        self.append(self._scrolled)
        self.append(input_bar)

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
        self._add_message(text, "user")
        if not self._title_set:
            title = text[:30]
            self._title_set = True
            self.emit("title-changed", title)
        self._waiting = True
        self._show_loading()
        self.session.send(text, on_data=self._on_stream, on_done=self._on_done, on_error=self._on_error)

    def _add_message(self, text, role):
        label = Gtk.Label()
        label.set_markup(self._format_message(text, role))
        label.set_selectable(True)
        label.set_wrap(True)
        label.set_xalign(0.0)
        label.set_margin_start(16 if role == "assistant" else 0)
        label.set_margin_end(16 if role == "user" else 0)
        label.add_css_class("message-label")

        frame = Gtk.Frame()
        frame.set_child(label)
        frame.add_css_class("message-frame")
        frame.add_css_class(f"message-{role}")

        self.message_list.append(frame)
        self.messages.append({"role": role, "text": text})
        self._scroll_to_bottom()

    def _show_loading(self):
        self._streaming_text = ""
        label_text = "思考中..."
        self._loading_label = Gtk.Label(label=label_text)
        self._loading_label.add_css_class("loading-label")
        self._loading_label.set_margin_start(16)
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
        safe = safe.replace("\n", "<br>")
        self._loading_label.set_markup(f"<b>🤖 </b>{safe}")

    def _finish_response(self, full_text):
        self._remove_loading()
        if full_text.strip():
            self._add_message(full_text.strip(), "assistant")
        self._waiting = False

    def _show_error(self, error):
        self._remove_loading()
        self._add_message(f"错误: {error}", "system")
        self._waiting = False

    def _scroll_to_bottom(self):
        adj = self._scrolled.get_vadjustment()
        if adj is not None:
            GLib.idle_add(lambda: adj.set_value(adj.get_upper() - adj.get_page_size()))

    def _format_message(self, text, role):
        import html
        safe = html.escape(text)
        safe = safe.replace("\n", "<br>")
        prefix = "🧑 " if role == "user" else "🤖 " if role == "assistant" else ""
        return f"<b>{prefix}</b>{safe}"
