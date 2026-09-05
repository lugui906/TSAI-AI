import threading
import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
from gi.repository import Gtk, Gdk, GLib

Gtk.Window.set_default_icon_name("face-smile")
GLib.set_prgname("aim-gui")
from aim.config import ensure_dirs, load_config, save_config
from aim.agent import list_agents, get_agent, save_agent, delete_agent, build_system_prompt
from aim.conversation import new_conversation, get_conversation, list_conversations, add_message
from aim.llm import chat

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



class AgentDialog(Gtk.Dialog):
    def __init__(self, parent, name=None):
        title = "编辑智能体" if name else "创建智能体"
        super().__init__(title=title, transient_for=parent)
        self.set_default_size(500, 400)

        self.name = name
        self.agent_data = get_agent(name) if name else {}

        box = self.get_content_area()
        box.set_spacing(8)
        box.set_margin_start(12)
        box.set_margin_end(12)
        box.set_margin_top(12)
        box.set_margin_bottom(12)

        grid = Gtk.Grid(column_spacing=8, row_spacing=8)
        box.append(grid)

        def _lbl(text):
            l = Gtk.Label(label=text)
            l.set_halign(Gtk.Align.START)
            return l

        row = 0
        if not name:
            grid.attach(_lbl("名称:"), 0, row, 1, 1)
            self.name_entry = Gtk.Entry()
            grid.attach(self.name_entry, 1, row, 1, 1)
            row += 1

        labels = {
            "description": "简短描述:",
            "role": "职位/身份:",
            "personality": "性格特点:",
            "background": "背景设定:",
            "rules": "行为规则:",
        }
        self.entries = {}
        for key, label_text in labels.items():
            grid.attach(_lbl(label_text), 0, row, 1, 1)
            entry = Gtk.Entry()
            if self.agent_data.get(key):
                entry.set_text(self.agent_data[key])
            grid.attach(entry, 1, row, 1, 1)
            self.entries[key] = entry
            row += 1

        self.add_button("取消", Gtk.ResponseType.CANCEL)
        self.add_button("保存", Gtk.ResponseType.OK)

    def get_result(self):
        data = {}
        if not self.name:
            name = self.name_entry.get_text().strip()
            if not name:
                return None
            data["_name"] = name
        for key, entry in self.entries.items():
            val = entry.get_text().strip()
            if val:
                data[key] = val
        return data


class ConfigDialog(Gtk.Dialog):
    def __init__(self, parent):
        super().__init__(title="设置", transient_for=parent)
        self.set_default_size(450, 250)

        cfg = load_config()
        box = self.get_content_area()
        box.set_spacing(8)
        box.set_margin_start(12)
        box.set_margin_end(12)
        box.set_margin_top(12)
        box.set_margin_bottom(12)

        grid = Gtk.Grid(column_spacing=8, row_spacing=8)
        box.append(grid)

        def _lbl(text):
            l = Gtk.Label(label=text)
            l.set_halign(Gtk.Align.START)
            return l

        fields = [
            ("api_key", "API 密钥:", 60),
            ("api_base", "API 地址:", 50),
            ("model", "模型名称:", 30),
        ]
        self.entries = {}
        for i, (key, label_text, width) in enumerate(fields):
            grid.attach(_lbl(label_text), 0, i, 1, 1)
            entry = Gtk.Entry()
            entry.set_width_chars(width)
            if cfg.get(key):
                entry.set_text(cfg[key])
            if key == "api_key":
                entry.set_visibility(False)
            grid.attach(entry, 1, i, 1, 1)
            self.entries[key] = entry

        note = Gtk.Label(
            label="环境变量会覆盖此处设置:\nAIM_API_KEY, AIM_API_BASE, AIM_MODEL",
            wrap=True)
        note.set_halign(Gtk.Align.START)
        box.append(note)

        self.add_button("取消", Gtk.ResponseType.CANCEL)
        self.add_button("保存", Gtk.ResponseType.OK)

    def get_result(self):
        return {key: entry.get_text().strip() for key, entry in self.entries.items()}


class AIMGUI:
    def __init__(self, application):
        ensure_dirs()
        self.application = application
        self.current_agent_name = None
        self.current_conv_id = None
        self.conv_messages = []
        self.conv_history = []
        self._streaming = False
        self._stop_event = threading.Event()

        self.window = Gtk.ApplicationWindow(application=application,
                                            title="AIM - AI 智能体管理器")
        self.window.set_default_size(960, 680)

        self._build_ui()
        self._refresh_agent_list()

    def _build_ui(self):
        header = Gtk.HeaderBar()
        header.set_show_title_buttons(True)
        header.set_title_widget(Gtk.Label(label="AIM"))
        self.window.set_titlebar(header)

        new_chat_btn = Gtk.Button(label="新建对话")
        new_chat_btn.add_css_class("suggested-action")
        new_chat_btn.connect("clicked", self._on_new_chat)
        header.pack_start(new_chat_btn)

        settings_btn = Gtk.Button(label="设置")
        settings_btn.connect("clicked", self._on_settings)
        header.pack_end(settings_btn)

        hpane = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL)
        self.window.set_child(hpane)

        left_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        left_box.set_margin_start(4)
        left_box.set_margin_end(4)
        left_box.set_margin_top(4)
        left_box.set_margin_bottom(4)
        left_box.set_size_request(200, -1)
        hpane.set_start_child(left_box)
        hpane.set_resize_start_child(False)

        agent_label = Gtk.Label(label="<b>智能体</b>", use_markup=True)
        agent_label.set_halign(Gtk.Align.START)
        left_box.append(agent_label)

        agent_scroll = Gtk.ScrolledWindow()
        agent_scroll.set_min_content_width(180)
        agent_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        agent_scroll.set_vexpand(True)
        self.agent_store = Gtk.ListStore(str, str)
        self.agent_view = Gtk.TreeView(model=self.agent_store)
        renderer = Gtk.CellRendererText()
        col = Gtk.TreeViewColumn("名称", renderer, text=0)
        self.agent_view.append_column(col)
        self.agent_view.get_selection().connect("changed", self._on_agent_selected)
        self.agent_view.connect("row-activated", self._on_agent_activated)
        agent_scroll.set_child(self.agent_view)
        left_box.append(agent_scroll)

        agent_btn_box = Gtk.Box(spacing=4)
        add_agent_btn = Gtk.Button(label="+")
        add_agent_btn.set_tooltip_text("创建智能体")
        add_agent_btn.connect("clicked", self._on_add_agent)
        agent_btn_box.append(add_agent_btn)

        edit_agent_btn = Gtk.Button(label="✎")
        edit_agent_btn.set_tooltip_text("编辑智能体")
        edit_agent_btn.connect("clicked", self._on_edit_agent)
        agent_btn_box.append(edit_agent_btn)

        del_agent_btn = Gtk.Button(label="−")
        del_agent_btn.set_tooltip_text("删除智能体")
        del_agent_btn.connect("clicked", self._on_delete_agent)
        agent_btn_box.append(del_agent_btn)

        left_box.append(agent_btn_box)

        conv_label = Gtk.Label(label="<b>对话</b>", use_markup=True)
        conv_label.set_halign(Gtk.Align.START)
        left_box.append(conv_label)

        conv_scroll = Gtk.ScrolledWindow()
        conv_scroll.set_min_content_width(180)
        conv_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        conv_scroll.set_vexpand(True)
        self.conv_store = Gtk.ListStore(str, str, str)
        self.conv_view = Gtk.TreeView(model=self.conv_store)
        renderer = Gtk.CellRendererText()
        col = Gtk.TreeViewColumn("对话", renderer, text=1)
        self.conv_view.append_column(col)
        self.conv_view.get_selection().connect("changed", self._on_conversation_selected)
        self.conv_view.connect("row-activated", self._on_conversation_activated)
        conv_scroll.set_child(self.conv_view)
        left_box.append(conv_scroll)

        right_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        right_box.set_margin_start(4)
        right_box.set_margin_end(4)
        right_box.set_margin_top(4)
        right_box.set_margin_bottom(4)
        hpane.set_end_child(right_box)
        hpane.set_resize_end_child(True)

        self.chat_title = Gtk.Label(label="选择一个智能体开始对话", wrap=True)
        self.chat_title.set_halign(Gtk.Align.START)
        self.chat_title.add_css_class("dim-label")
        right_box.append(self.chat_title)

        chat_scroll = Gtk.ScrolledWindow()
        chat_scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        chat_scroll.set_vexpand(True)
        self.chat_buffer = Gtk.TextBuffer()
        self.chat_view = Gtk.TextView(buffer=self.chat_buffer)
        self.chat_view.set_editable(False)
        self.chat_view.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        self.chat_view.set_cursor_visible(False)
        chat_scroll.set_child(self.chat_view)
        right_box.append(chat_scroll)

        input_box = Gtk.Box(spacing=4)
        self.msg_entry = Gtk.Entry()
        self.msg_entry.set_placeholder_text("输入消息...")
        self.msg_entry.connect("activate", self._on_send)
        self.msg_entry.set_hexpand(True)
        input_box.append(self.msg_entry)

        self.send_btn = Gtk.Button(label="发送")
        self.send_btn.add_css_class("suggested-action")
        self.send_btn.connect("clicked", self._on_send)
        input_box.append(self.send_btn)

        self.stop_btn = Gtk.Button(label="停止")
        self.stop_btn.set_sensitive(False)
        self.stop_btn.connect("clicked", self._on_stop)
        input_box.append(self.stop_btn)

        right_box.append(input_box)

    def _refresh_agent_list(self):
        self.agent_store.clear()
        for name, desc in list_agents():
            self.agent_store.append([name, desc])

    def _refresh_conversation_list(self):
        self.conv_store.clear()
        if not self.current_agent_name:
            return
        convs = list_conversations(agent_name=self.current_agent_name)
        for pid, agent_name, msg_count, updated in convs:
            label = f"{pid} ({msg_count}条)"
            self.conv_store.append([pid, label, updated])

    def _on_agent_selected(self, selection):
        model, treeiter = selection.get_selected()
        if treeiter:
            self.current_agent_name = model[treeiter][0]
            self.current_conv_id = None
            self._refresh_conversation_list()
            self._clear_chat()
            self.chat_title.set_markup(f"<b>{self.current_agent_name}</b> — 选择一个对话或新建")
        else:
            self.current_agent_name = None

    def _on_agent_activated(self, view, path, col):
        self._on_new_chat(None)

    def _on_conversation_selected(self, selection):
        model, treeiter = selection.get_selected()
        if treeiter:
            self.current_conv_id = model[treeiter][0]
        else:
            self.current_conv_id = None

    def _on_conversation_activated(self, view, path, col):
        self._load_conversation()

    def _load_conversation(self):
        if not self.current_conv_id:
            return
        conv = get_conversation(self.current_conv_id)
        if not conv:
            return
        agent = get_agent(conv["agent"])
        if not agent:
            return

        self.current_agent_name = conv["agent"]
        self.conv_messages = [{"role": "system", "content": build_system_prompt(agent)}]
        self.conv_history = []
        for msg in conv["messages"]:
            self.conv_messages.append(msg)
            self.conv_history.append(msg)

        self._display_conversation()
        self.chat_title.set_markup(f"<b>{conv['agent']}</b> — 对话 {self.current_conv_id}")

    def _display_conversation(self):
        self._clear_chat()
        end_iter = self.chat_buffer.get_end_iter()
        for msg in self.conv_history:
            role_label = "你" if msg["role"] == "user" else self.current_agent_name
            tag = "user" if msg["role"] == "user" else "assistant"
            self.chat_buffer.insert_with_tags_by_name(end_iter, f"{role_label}:\n", tag)
            self.chat_buffer.insert(end_iter, f"{msg['content']}\n\n")

    def _clear_chat(self):
        self.chat_buffer.set_text("")
        tags = self.chat_buffer.get_tag_table()
        for tag_name in ["user", "assistant", "streaming"]:
            tag = tags.lookup(tag_name)
            if not tag:
                if tag_name == "user":
                    t = self.chat_buffer.create_tag("user", weight=700)
                elif tag_name == "assistant":
                    t = self.chat_buffer.create_tag("assistant", weight=700)
                elif tag_name == "streaming":
                    t = self.chat_buffer.create_tag("streaming", foreground="#2a7a2a")

    def _on_new_chat(self, _btn):
        if not self.current_agent_name:
            self._show_info("请先在左侧选择一个智能体")
            return
        agent = get_agent(self.current_agent_name)
        if not agent:
            self._show_info(f"智能体 '{self.current_agent_name}' 不存在")
            return

        conv_id = new_conversation(self.current_agent_name)
        self.current_conv_id = conv_id
        system_prompt = build_system_prompt(agent)
        self.conv_messages = [{"role": "system", "content": system_prompt}]
        self.conv_history = []
        self._clear_chat()
        self.chat_title.set_markup(f"<b>{self.current_agent_name}</b> — 新对话 {conv_id}")
        self._refresh_conversation_list()
        self.msg_entry.grab_focus()

    def _on_stop(self, _widget):
        if not self._streaming:
            return
        self._stop_event.set()
        self._streaming = False
        self.send_btn.set_sensitive(True)
        self.stop_btn.set_sensitive(False)
        self.msg_entry.set_sensitive(True)
        self.msg_entry.grab_focus()

    def _on_send(self, _widget):
        if self._streaming:
            return
        text = self.msg_entry.get_text().strip()
        if not text:
            return
        if not self.current_conv_id:
            self._show_info("请先新建或选择一个对话")
            return

        self.msg_entry.set_text("")
        self.msg_entry.set_sensitive(False)
        self.send_btn.set_sensitive(False)
        self._streaming = True
        self._stop_event.clear()
        self.stop_btn.set_sensitive(True)

        self.chat_buffer.insert_with_tags_by_name(
            self.chat_buffer.get_end_iter(), "你:\n", "user"
        )
        self.chat_buffer.insert(self.chat_buffer.get_end_iter(), f"{text}\n\n")

        label = f"{self.current_agent_name}:\n"
        self.chat_buffer.insert_with_tags_by_name(
            self.chat_buffer.get_end_iter(), label, "assistant"
        )
        self._stream_start_iter = self.chat_buffer.get_end_iter().copy()

        add_message(self.current_conv_id, "user", text)
        self.conv_messages.append({"role": "user", "content": text})
        self.conv_history.append({"role": "user", "content": text})

        def stream_callback(token):
            GLib.idle_add(self._append_stream_token, token)

        def chat_thread():
            reply = chat(self.conv_messages, stream=True, stream_callback=stream_callback,
                         stop_event=self._stop_event)
            GLib.idle_add(self._on_stream_done, reply)

        t = threading.Thread(target=chat_thread, daemon=True)
        t.start()

    def _append_stream_token(self, token):
        if not self._streaming:
            return False
        end_iter = self.chat_buffer.get_end_iter()
        self.chat_buffer.insert(end_iter, token)
        mark = self.chat_buffer.create_mark(None, end_iter, False)
        self.chat_view.scroll_to_mark(mark, 0.0, True, 0.0, 0.5)
        return False

    def _on_stream_done(self, reply):
        self._streaming = False
        self.send_btn.set_sensitive(True)
        self.stop_btn.set_sensitive(False)
        self.msg_entry.set_sensitive(True)
        if reply and not self._stop_event.is_set():
            self.chat_buffer.insert(self.chat_buffer.get_end_iter(), "\n\n")
            self.conv_messages.append({"role": "assistant", "content": reply})
            self.conv_history.append({"role": "assistant", "content": reply})
            add_message(self.current_conv_id, "assistant", reply)
            self._refresh_conversation_list()
        self.msg_entry.grab_focus()

    def _on_add_agent(self, _btn):
        dialog = AgentDialog(self.window)
        dialog.connect("response", self._on_add_agent_response, dialog)
        dialog.present()

    def _on_add_agent_response(self, _dlg, response, dialog):
        if response == Gtk.ResponseType.OK:
            data = dialog.get_result()
            if data:
                name = data.pop("_name")
                save_agent(name, data)
                self._refresh_agent_list()
        dialog.destroy()

    def _on_edit_agent(self, _btn):
        if not self.current_agent_name:
            self._show_info("请先选择一个智能体")
            return
        dialog = AgentDialog(self.window, name=self.current_agent_name)
        dialog.connect("response", self._on_edit_agent_response, dialog)
        dialog.present()

    def _on_edit_agent_response(self, _dlg, response, dialog):
        if response == Gtk.ResponseType.OK:
            data = dialog.get_result()
            if data:
                if "_name" in data:
                    data.pop("_name")
                save_agent(self.current_agent_name, data)
                self._refresh_agent_list()
        dialog.destroy()

    def _on_delete_agent(self, _btn):
        if not self.current_agent_name:
            self._show_info("请先选择一个智能体")
            return
        dialog = Gtk.MessageDialog(
            transient_for=self.window,
            modal=True,
            message_type=Gtk.MessageType.QUESTION,
            buttons=Gtk.ButtonsType.YES_NO,
            text=f"确认删除智能体 '{self.current_agent_name}'？",
        )
        dialog.connect("response", self._on_delete_agent_response)
        dialog.present()

    def _on_delete_agent_response(self, dialog, response):
        dialog.destroy()
        if response == Gtk.ResponseType.YES:
            delete_agent(self.current_agent_name)
            self.current_agent_name = None
            self._refresh_agent_list()
            self._refresh_conversation_list()
            self._clear_chat()

    def _on_settings(self, _btn):
        dialog = ConfigDialog(self.window)
        dialog.connect("response", self._on_settings_response, dialog)
        dialog.present()

    def _on_settings_response(self, _dlg, response, dialog):
        if response == Gtk.ResponseType.OK:
            data = dialog.get_result()
            cfg = load_config()
            cfg.update(data)
            save_config(cfg)
        dialog.destroy()

    def _show_info(self, msg):
        dialog = Gtk.MessageDialog(
            transient_for=self.window,
            modal=True,
            message_type=Gtk.MessageType.INFO,
            buttons=Gtk.ButtonsType.OK,
            text=msg,
        )
        dialog.connect("response", lambda d, _r: d.destroy())
        dialog.present()


def main():
    if chstyle:
        chstyle.apply_gtk4()
    app = Gtk.Application(application_id="org.chindows.bai-aim-gui")
    state = {"ui": None}

    def activate(application):
        if state["ui"] is None:
            state["ui"] = AIMGUI(application)
        state["ui"].window.present()

    app.connect("activate", activate)
    app.run(None)


if __name__ == "__main__":
    main()
