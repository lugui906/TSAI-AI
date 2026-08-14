import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
from gi.repository import Gtk, Gdk, GLib, Gio, Pango
from pathlib import Path

from editor import EditorPane, Document
from ai_panel import AiPanel


class MainWindow(Gtk.ApplicationWindow):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.set_title("AI Note Editor")
        self.set_default_size(1200, 800)

        self._current_dir = Path.home() / "文档"
        self._build_ui()
        self._load_css()
        self._setup_actions()
        self._scan_files()

    def _build_ui(self):
        header = Gtk.HeaderBar()
        header.set_show_title_buttons(True)

        open_btn = Gtk.Button(label="打开")
        open_btn.connect("clicked", self._on_open)
        header.pack_start(open_btn)

        save_btn = Gtk.Button(label="保存")
        save_btn.add_css_class("suggested-action")
        save_btn.connect("clicked", self._on_save)
        header.pack_start(save_btn)

        new_btn = Gtk.Button(label="新建")
        new_btn.connect("clicked", self._on_new)
        header.pack_start(new_btn)

        self.set_titlebar(header)

        hpaned = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL)
        hpaned.set_position(220)

        sidebar_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        sidebar_box.set_size_request(180, -1)

        dir_label = Gtk.Label(label="文件浏览器")
        dir_label.add_css_class("heading")
        dir_label.set_margin_start(8)
        dir_label.set_margin_top(8)
        dir_label.set_margin_bottom(4)
        dir_label.set_xalign(0)
        sidebar_box.append(dir_label)

        dir_chooser = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        dir_chooser.set_margin_start(8)
        dir_chooser.set_margin_end(8)
        dir_chooser.set_margin_bottom(4)

        self._dir_entry = Gtk.Entry()
        self._dir_entry.set_text(str(self._current_dir))
        self._dir_entry.connect("activate", self._on_dir_changed)
        dir_chooser.append(self._dir_entry)

        browse_btn = Gtk.Button(label="...")
        browse_btn.connect("clicked", self._on_browse_dir)
        dir_chooser.append(browse_btn)
        sidebar_box.append(dir_chooser)

        self._file_filter = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        self._file_filter.set_margin_start(8)
        self._file_filter.set_margin_end(8)
        self._file_filter.set_margin_bottom(4)

        ext_filter = Gtk.DropDown.new_from_strings(["全部", "md", "docx", "xlsx", "txt"])
        ext_filter.connect("notify::selected", self._on_filter_changed)
        self._ext_filter = ext_filter
        self._file_filter.append(ext_filter)

        refresh_btn = Gtk.Button(label="刷新")
        refresh_btn.connect("clicked", lambda *a: self._scan_files())
        self._file_filter.append(refresh_btn)
        sidebar_box.append(self._file_filter)

        sidebar_scroll = Gtk.ScrolledWindow()
        sidebar_scroll.set_vexpand(True)

        self._file_list = Gtk.ListBox()
        self._file_list.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self._file_list.connect("row-activated", self._on_file_activated)
        sidebar_scroll.set_child(self._file_list)
        sidebar_box.append(sidebar_scroll)

        hpaned.set_start_child(sidebar_box)

        center_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)

        self.editor = EditorPane()
        center_box.append(self.editor)

        hpaned.set_end_child(center_box)

        self._ai_panel = AiPanel()
        self._ai_panel.set_size_request(280, -1)
        self._ai_panel.connect("replace-text", self._on_ai_replace)
        self._ai_panel.connect("replace-full-text", self._on_ai_replace_full)
        self.editor._buffer.connect("changed", self._on_editor_changed)

        vpaned = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL)
        vpaned.set_position(900)
        vpaned.set_start_child(hpaned)
        vpaned.set_end_child(self._ai_panel)

        self._main_paned = vpaned
        self.set_child(vpaned)

        self._connect_editor_signals()

    def _setup_actions(self):
        open_action = Gio.SimpleAction.new("open", None)
        open_action.connect("activate", self._on_open)
        self.add_action(open_action)

        save_action = Gio.SimpleAction.new("save", None)
        save_action.connect("activate", self._on_save)
        self.add_action(save_action)

        app = self.get_application()
        if app:
            app.set_accels_for_action("win.open", ["<Control>o"])
            app.set_accels_for_action("win.save", ["<Control>s"])

    def _on_open(self, *args):
        dialog = Gtk.FileDialog.new()
        dialog.set_title("打开文件")
        f = Gtk.FileFilter()
        f.set_name("所有文件")
        f.add_pattern("*")
        dialog.set_default_filter(f)
        dialog.open(self, None, self._on_open_result, None)

    def _migrate_to_dir(self, path):
        parent = Path(path).parent
        if parent.is_dir():
            self._current_dir = parent
            self._dir_entry.set_text(str(parent))
            self._scan_files()

    def _on_open_result(self, dialog, result, data):
        try:
            file = dialog.open_finish(result)
            if file:
                ok = self.editor.open_file(file.get_path())
                if ok:
                    self._migrate_to_dir(file.get_path())
                    self.set_title(f"AI Note Editor - {file.get_path().rsplit('/', 1)[-1]}")
                else:
                    print(f"open_file failed for {file.get_path()}")
            else:
                print("open_finish returned None")
        except GLib.Error as e:
            print(f"Open error: {e.message}")

    def _on_save(self, *args):
        if not self.editor.filepath:
            dialog = Gtk.FileDialog.new()
            dialog.set_title("保存文件")
            f = Gtk.FileFilter()
            f.set_name("所有文件")
            f.add_pattern("*")
            dialog.set_default_filter(f)
            dialog.save(self, None, self._on_save_result, None)
        else:
            self.editor.save()
            self.set_title(f"AI Note Editor - {self.editor.filepath.name}")

    def _on_save_result(self, dialog, result, data):
        try:
            file = dialog.save_finish(result)
            if file:
                ok = self.editor.save_as(file.get_path())
                if ok:
                    self._migrate_to_dir(file.get_path())
                    self._scan_files()
                    self.set_title(f"AI Note Editor - {file.get_path().rsplit('/', 1)[-1]}")
                else:
                    print(f"save_as failed for {file.get_path()}")
            else:
                print("save_finish returned None")
        except GLib.Error as e:
            print(f"Save error: {e.message}")

    def _on_new(self, *args):
        self.editor._buffer.set_text("")
        self.editor.filepath = None
        self.editor.document = None
        self.editor._modified = False
        self.editor._title_label.set_label("未命名")
        self.editor._format_label.set_label("")
        self.set_title("AI Note Editor - 未命名")
        self._main_paned.get_end_child().set_visible(False)
        new_panel = AiPanel()
        new_panel.set_size_request(280, -1)
        new_panel.connect("replace-text", self._on_ai_replace)
        new_panel.connect("replace-full-text", self._on_ai_replace_full)
        self._main_paned.set_end_child(new_panel)
        self._ai_panel = new_panel

    def _on_browse_dir(self, *args):
        dialog = Gtk.FileDialog.new()
        dialog.set_title("选择文件夹")
        dialog.select_folder(self, None, self._on_folder_result, None)

    def _on_folder_result(self, dialog, result, data):
        try:
            folder = dialog.select_folder_finish(result)
            if folder:
                self._current_dir = Path(folder.get_path())
                self._dir_entry.set_text(str(self._current_dir))
                self._scan_files()
        except GLib.Error:
            pass

    def _on_dir_changed(self, *args):
        path = Path(self._dir_entry.get_text())
        if path.is_dir():
            self._current_dir = path
            self._scan_files()

    def _on_filter_changed(self, *args):
        self._scan_files()

    def _on_file_activated(self, listbox, row):
        path = getattr(row, "filepath", None)
        if path:
            self.editor.open_file(path)
            self._migrate_to_dir(path)

    def _connect_editor_signals(self):
        buf = self.editor._textview.get_buffer()
        buf.connect("mark-set", self._on_mark_set)
        click = Gtk.GestureClick.new()
        click.connect("released", self._on_mouse_release)
        self.editor._textview.add_controller(click)
        key = Gtk.EventControllerKey.new()
        key.connect("key-released", self._on_key_release)
        self.editor._textview.add_controller(key)

    def _on_mark_set(self, buffer, location, mark):
        GLib.idle_add(self._update_selection)

    def _on_mouse_release(self, gesture, n_press, x, y):
        self._update_selection()

    def _on_key_release(self, controller, keyval, keycode, state):
        self._update_selection()

    def _update_selection(self):
        sel = self.editor._buffer.get_selection_bounds()
        if len(sel) == 2:
            text = self.editor._buffer.get_text(sel[0], sel[1], False)
            if text.strip():
                self._ai_panel.set_context(text)
                return
        self._ai_panel.set_context("")

    def _on_editor_changed(self, *args):
        self._ai_panel.set_full_doc(self.editor.get_all_text())

    def _on_ai_replace(self, panel, text):
        if self.editor.get_selected_text():
            self.editor.replace_selection(text)
        else:
            self.editor.insert_at_cursor(text)

    def _on_ai_replace_full(self, panel, text):
        bounds = self.editor._buffer.get_bounds()
        self.editor._buffer.delete(bounds[0], bounds[1])
        self.editor._buffer.insert_at_cursor(text)

    def _scan_files(self):
        self._file_list.remove_all()
        selected_filter = self._ext_filter.get_selected()
        ext_map = {1: ".md", 2: ".docx", 3: ".xlsx", 4: ".txt"}
        filter_ext = ext_map.get(selected_filter)

        if not self._current_dir.is_dir():
            return

        files = []
        try:
            for f in sorted(self._current_dir.iterdir(), key=lambda p: (not p.is_file(), p.name.lower())):
                if f.is_file():
                    if filter_ext and f.suffix.lower() != filter_ext:
                        continue
                    files.append(f)
        except PermissionError:
            pass

        for f in files:
            row = Gtk.ListBoxRow()
            row.filepath = f
            box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
            box.set_margin_start(8)
            box.set_margin_end(8)
            box.set_margin_top(4)
            box.set_margin_bottom(4)

            icon_map = {".md": "📝", ".docx": "📄", ".xlsx": "📊", ".txt": "📃", ".json": "📋", ".yaml": "📋", ".yml": "📋", ".xml": "📋", ".html": "🌐", ".css": "🎨", ".js": "📜", ".py": "🐍", ".c": "⚙️", ".cpp": "⚙️", ".h": "⚙️", ".java": "☕", ".sh": "💻", ".csv": "📊"}
            icon = Gtk.Label(label=icon_map.get(f.suffix.lower(), "📄"))
            box.append(icon)

            label = Gtk.Label(label=f.name, xalign=0)
            label.set_hexpand(True)
            label.set_ellipsize(Pango.EllipsizeMode.END)
            box.append(label)

            row.set_child(box)
            self._file_list.append(row)

    def _load_css(self):
        css = b"""
        textview {
            font-size: 12pt;
            font-family: sans-serif;
        }
        .debug-log textview {
            font-family: monospace;
            font-size: 9pt;
        }
        .heading {
            font-weight: bold;
            font-size: 13px;
        }
        .message-frame {
            border-radius: 6px;
            border: none;
        }
        .message-user {
            background-color: rgba(52, 122, 235, 0.1);
        }
        .message-assistant {
            background-color: rgba(46, 160, 67, 0.08);
        }
        .message-system {
            background-color: rgba(255, 193, 7, 0.1);
        }
        .loading-label {
            font-style: italic;
            opacity: 0.6;
            padding: 4px 8px;
        }
        .small-button {
            font-size: 11px;
            padding: 2px 4px;
        }
        .dim-label {
            opacity: 0.6;
            font-size: 11px;
        }
        """
        provider = Gtk.CssProvider()
        provider.load_from_data(css)
        Gtk.StyleContext.add_provider_for_display(
            self.get_display(),
            provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )
