#!/usr/bin/env python3
"""AI 模型管理器 - 管理 opencode / aim 的默认模型、Provider 与 AI 引擎。

- 统一读写 ~/.config/opencode/opencode.jsonc（aim 底层委托 opencode，二者共用）。
- 支持设置默认模型 (model) 与小型模型 (small_model)。
- 支持添加/编辑/删除自定义 Provider（baseURL + apiKey + models）。
- 支持 AIM 引擎切换（opencode / openclaw，对应 `aim oc`）。
- 支持管理 Provider API Key（对应 `aim apikey`）。
"""

import os
import subprocess
import sys

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gtk, Gdk, GLib

import jsonc

CONFIG_PATH = os.path.expanduser("~/.config/opencode/opencode.jsonc")
DEFAULT_NPM = "@ai-sdk/openai-compatible"


def ensure_config():
    os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
    if not os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            f.write('{\n  "$schema": "https://opencode.ai/config.json"\n}\n')


def read_config():
    ensure_config()
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        text = f.read()
    try:
        _, value = jsonc.parse(text)
    except jsonc.JsoncError:
        return {}
    return value


def write_config_text(text):
    ensure_config()
    tmp = CONFIG_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp, CONFIG_PATH)


def read_config_text():
    ensure_config()
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return f.read()


def list_models():
    """Return available models from `opencode models`."""
    try:
        out = subprocess.run(["opencode", "models"],
                             capture_output=True, text=True, timeout=30)
        lines = [l.strip() for l in out.stdout.splitlines() if l.strip()]
        return lines
    except (subprocess.SubprocessError, FileNotFoundError):
        return []


# ---------------------------------------------------------------- aim engine

def aim_current_engine():
    """Return the persisted AIM engine name (opencode/openclaw)."""
    try:
        out = subprocess.run(["aim", "oc", "status"],
                             capture_output=True, text=True, timeout=10)
        name = out.stdout.strip()
        return name if name else "opencode"
    except (subprocess.SubprocessError, FileNotFoundError):
        return "opencode"


def aim_switch_engine(target):
    """Switch AIM engine: target in ('opencode', 'openclaw')."""
    arg = "default" if target == "opencode" else "openclaw"
    try:
        out = subprocess.run(["aim", "oc", arg],
                             capture_output=True, text=True, timeout=15)
        if out.returncode != 0:
            return False, out.stderr.strip() or "aim oc 返回失败"
        return True, out.stdout.strip() or ("已切换到 " + target)
    except (subprocess.SubprocessError, FileNotFoundError) as e:
        return False, str(e)


def aim_list_apikeys():
    """Return list of (provider, masked_key) from `aim apikey list`."""
    try:
        out = subprocess.run(["aim", "apikey", "list"],
                             capture_output=True, text=True, timeout=10)
        lines = [l for l in out.stdout.splitlines() if l.strip()]
        # skip the header line "Configured API keys:"
        pairs = []
        for l in lines[1:]:
            if ":" in l:
                prov, key = l.split(":", 1)
                pairs.append((prov.strip(), key.strip()))
        return pairs
    except (subprocess.SubprocessError, FileNotFoundError):
        return []


def aim_set_apikey(provider, key):
    try:
        out = subprocess.run(["aim", "apikey", "set", provider, key],
                             capture_output=True, text=True, timeout=15)
        if out.returncode != 0:
            return False, out.stderr.strip() or "设置失败"
        return True, out.stdout.strip()
    except (subprocess.SubprocessError, FileNotFoundError) as e:
        return False, str(e)


def aim_remove_apikey(provider):
    try:
        out = subprocess.run(["aim", "apikey", "remove", provider],
                             capture_output=True, text=True, timeout=15)
        if out.returncode != 0:
            return False, out.stderr.strip() or "删除失败"
        return True, out.stdout.strip()
    except (subprocess.SubprocessError, FileNotFoundError) as e:
        return False, str(e)


class MainWindow(Gtk.Window):
    def __init__(self):
        super().__init__(title="AI 模型管理器")
        self.set_default_size(680, 520)

        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.add(vbox)

        header = Gtk.HeaderBar()
        header.set_show_close_button(True)
        header.props.title = "AI 模型管理器"
        header.props.subtitle = "模型 / Provider / 引擎 (opencode·openclaw)"
        self.set_titlebar(header)

        self.status_label = Gtk.Label(label="就绪", xalign=0)
        self.status_label.set_margin_start(10)
        self.status_label.set_margin_end(10)
        self.status_label.set_margin_top(6)
        self.status_label.set_margin_bottom(6)
        vbox.pack_end(self.status_label, False, False, 0)

        notebook = Gtk.Notebook()
        vbox.pack_start(notebook, True, True, 0)

        self._build_default_tab(notebook)
        self._build_provider_tab(notebook)
        self._build_engine_tab(notebook)

        self._load_all()

    # ------------------------------------------------------------ status
    def set_status(self, msg, error=False):
        self.status_label.set_text(msg)
        if error:
            self.status_label.set_name("status-error")
        else:
            self.status_label.set_name("")

    # ---------------------------------------------------- default model tab
    def _build_default_tab(self, notebook):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        box.set_margin_start(16)
        box.set_margin_end(16)
        box.set_margin_top(16)
        box.set_margin_bottom(16)

        note = Gtk.Label(label="AIM 底层委托 opencode，两者共用该配置。", xalign=0)
        note.set_halign(Gtk.Align.START)
        note.get_style_context().add_class("dim-label")
        box.pack_start(note, False, False, 0)

        grid = Gtk.Grid(column_spacing=10, row_spacing=8)
        box.pack_start(grid, False, False, 0)

        grid.attach(Gtk.Label(label="默认模型 (model)", xalign=1), 0, 0, 1, 1)
        self.model_combo = self._make_combo()
        grid.attach(self.model_combo, 1, 0, 1, 1)

        grid.attach(Gtk.Label(label="小型模型 (small_model)", xalign=1), 0, 1, 1, 1)
        self.small_combo = self._make_combo()
        grid.attach(self.small_combo, 1, 1, 1, 1)

        hint = Gtk.Label(label="可在下拉框中输入自定义模型 ID（如 provider/model）", xalign=0)
        hint.set_halign(Gtk.Align.START)
        hint.get_style_context().add_class("dim-label")
        box.pack_start(hint, False, False, 0)

        btn_row = Gtk.Box(spacing=8)
        box.pack_start(btn_row, False, False, 0)

        refresh_btn = Gtk.Button(label="刷新模型列表")
        refresh_btn.connect("clicked", self._on_refresh)
        btn_row.pack_start(refresh_btn, False, False, 0)

        save_btn = Gtk.Button(label="保存默认模型")
        save_btn.get_style_context().add_class("suggested-action")
        save_btn.connect("clicked", self._on_save_defaults)
        btn_row.pack_start(save_btn, False, False, 0)

        # model list view
        list_scroll = Gtk.ScrolledWindow()
        list_scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        list_scroll.set_vexpand(True)
        box.pack_start(list_scroll, True, True, 0)

        self.models_store = Gtk.ListStore(str)
        self.models_view = Gtk.TreeView(model=self.models_store)
        renderer = Gtk.CellRendererText()
        col = Gtk.TreeViewColumn("可用模型", renderer, text=0)
        self.models_view.append_column(col)
        self.models_view.set_headers_visible(False)
        self.models_view.get_selection().connect("changed", self._on_models_selection)
        list_scroll.add(self.models_view)

        use_row = Gtk.Box(spacing=8)
        box.pack_start(use_row, False, False, 0)
        b1 = Gtk.Button(label="设为主模型")
        b1.connect("clicked", lambda w: self._set_from_selection(self.model_combo))
        use_row.pack_start(b1, False, False, 0)
        b2 = Gtk.Button(label="设为小模型")
        b2.connect("clicked", lambda w: self._set_from_selection(self.small_combo))
        use_row.pack_start(b2, False, False, 0)

        notebook.append_page(box, Gtk.Label(label="默认模型"))

    def _make_combo(self):
        combo = Gtk.ComboBoxText.new_with_entry()
        entry = combo.get_child()
        entry.set_activates_default(True)
        return combo

    def _combo_text(self, combo):
        entry = combo.get_child()
        return entry.get_text().strip()

    def _combo_set(self, combo, value):
        entry = combo.get_child()
        entry.set_text(value or "")

    def _set_from_selection(self, combo):
        sel = self.models_view.get_selection()
        model, it = sel.get_selected()
        if it is not None:
            self._combo_set(combo, model[it][0])

    def _on_models_selection(self, sel):
        pass

    def _on_refresh(self, btn):
        self._populate_models()

    def _populate_models(self):
        models = list_models()
        self.models_store.clear()
        for m in models:
            self.models_store.append([m])

        for combo in (self.model_combo, self.small_combo):
            entry = combo.get_child()
            current = entry.get_text().strip()
            combo.remove_all()
            for m in models:
                combo.append_text(m)
            if current:
                entry.set_text(current)

        self.set_status("已刷新 %d 个模型" % len(models))

    def _on_save_defaults(self, w):
        model = self._combo_text(self.model_combo)
        small = self._combo_text(self.small_combo)
        text = read_config_text()
        try:
            text = jsonc.set_value(text, ["model"], model) if model else text
            text = jsonc.set_value(text, ["small_model"], small) if small else text
        except jsonc.JsoncError as e:
            self.set_status("保存失败: %s" % e, error=True)
            return
        write_config_text(text)
        self.set_status("已保存默认模型: model=%s, small_model=%s" % (model or "(未设置)", small or "(未设置)"))

    # ---------------------------------------------------- aim engine tab
    def _build_engine_tab(self, notebook):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        box.set_margin_start(16)
        box.set_margin_end(16)
        box.set_margin_top(16)
        box.set_margin_bottom(16)

        note = Gtk.Label(
            label="配置 AIM 使用的 AI 引擎（opencode / openclaw）与 Provider API Key。",
            xalign=0)
        note.set_halign(Gtk.Align.START)
        note.get_style_context().add_class("dim-label")
        box.pack_start(note, False, False, 0)

        # ---- engine switch frame
        eng_frame = Gtk.Frame(label="AI 引擎")
        eng_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        eng_box.set_margin_start(12)
        eng_box.set_margin_end(12)
        eng_box.set_margin_top(8)
        eng_box.set_margin_bottom(12)
        eng_frame.add(eng_box)
        box.pack_start(eng_frame, False, False, 0)

        eng_row = Gtk.Box(spacing=8)
        eng_box.pack_start(eng_row, False, False, 0)

        self.engine_label = Gtk.Label(label="当前引擎: ...", xalign=0)
        eng_row.pack_start(self.engine_label, True, True, 0)

        self.btn_openclaw = Gtk.Button(label="切换到 openclaw")
        self.btn_openclaw.connect("clicked", lambda w: self._switch_engine("openclaw"))
        eng_row.pack_start(self.btn_openclaw, False, False, 0)

        self.btn_opencode = Gtk.Button(label="切换回 opencode")
        self.btn_opencode.connect("clicked", lambda w: self._switch_engine("opencode"))
        eng_row.pack_start(self.btn_opencode, False, False, 0)

        # ---- provider config buttons
        cfg_row = Gtk.Box(spacing=8)
        eng_box.pack_start(cfg_row, False, False, 0)

        cfg_note = Gtk.Label(
            label="配置 Provider：", xalign=0)
        cfg_note.set_halign(Gtk.Align.START)
        cfg_row.pack_start(cfg_note, False, False, 0)

        b_aim = Gtk.Button(label="aim 提供方")
        b_aim.set_tooltip_text("运行 aim model switch（委托 opencode providers）")
        b_aim.connect("clicked", self._on_configure_aim)
        cfg_row.pack_start(b_aim, False, False, 0)

        b_oc = Gtk.Button(label="openclaw 提供方")
        b_oc.set_tooltip_text("运行 openclaw configure --section model")
        b_oc.connect("clicked", self._on_configure_openclaw)
        cfg_row.pack_start(b_oc, False, False, 0)

        # ---- api key management frame
        key_frame = Gtk.Frame(label="Provider API Key (aim apikey)")
        key_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        key_box.set_margin_start(12)
        key_box.set_margin_end(12)
        key_box.set_margin_top(8)
        key_box.set_margin_bottom(12)
        key_frame.add(key_box)
        box.pack_start(key_frame, True, True, 0)

        key_scroll = Gtk.ScrolledWindow()
        key_scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        key_scroll.set_vexpand(True)
        key_box.pack_start(key_scroll, True, True, 0)

        self.apikey_store = Gtk.ListStore(str, str)
        self.apikey_view = Gtk.TreeView(model=self.apikey_store)
        for title, idx in (("Provider", 0), ("Key", 1)):
            col = Gtk.TreeViewColumn(title, Gtk.CellRendererText(), text=idx)
            self.apikey_view.append_column(col)
        self.apikey_view.set_headers_visible(True)
        key_scroll.add(self.apikey_view)

        key_btn_row = Gtk.Box(spacing=8)
        key_box.pack_start(key_btn_row, False, False, 0)

        b_add = Gtk.Button(label="添加/修改 Key")
        b_add.connect("clicked", self._on_apikey_add)
        key_btn_row.pack_start(b_add, False, False, 0)

        b_del = Gtk.Button(label="删除 Key")
        b_del.connect("clicked", self._on_apikey_delete)
        key_btn_row.pack_start(b_del, False, False, 0)

        b_refresh = Gtk.Button(label="刷新")
        b_refresh.connect("clicked", lambda w: self._load_apikeys())
        key_btn_row.pack_start(b_refresh, False, False, 0)

        notebook.append_page(box, Gtk.Label(label="AIM 引擎"))

    def _switch_engine(self, target):
        ok, msg = aim_switch_engine(target)
        if not ok:
            self.set_status("切换失败: %s" % msg, error=True)
            return
        self._load_engine()
        self.set_status(msg)

    def _load_engine(self):
        engine = aim_current_engine()
        self.engine_label.set_text("当前引擎: %s" % engine)
        self.btn_openclaw.set_sensitive(engine != "openclaw")
        self.btn_opencode.set_sensitive(engine != "opencode")

    def _load_apikeys(self):
        self.apikey_store.clear()
        for prov, key in aim_list_apikeys():
            self.apikey_store.append([prov, key])

    def _selected_apikey(self):
        sel = self.apikey_view.get_selection()
        model, it = sel.get_selected()
        if it is None:
            return None
        return model[it][0]

    def _on_apikey_add(self, w):
        dlg = Gtk.Dialog(transient_for=self, modal=True, title="配置 Provider API Key")
        dlg.set_default_size(420, 140)
        dlg.add_button("取消", Gtk.ResponseType.CANCEL)
        dlg.add_button("保存", Gtk.ResponseType.OK)

        box = dlg.get_content_area()
        box.set_spacing(8)
        box.set_margin_start(12)
        box.set_margin_end(12)
        box.set_margin_top(12)
        box.set_margin_bottom(12)

        grid = Gtk.Grid(column_spacing=8, row_spacing=8)
        box.pack_start(grid, False, False, 0)

        grid.attach(Gtk.Label(label="Provider", xalign=1), 0, 0, 1, 1)
        prov_entry = Gtk.Entry()
        prov_entry.set_placeholder_text("如 openai / anthropic / deepseek")
        grid.attach(prov_entry, 1, 0, 1, 1)

        grid.attach(Gtk.Label(label="API Key", xalign=1), 0, 1, 1, 1)
        key_entry = Gtk.Entry()
        key_entry.set_visibility(False)
        grid.attach(key_entry, 1, 1, 1, 1)

        # prefill when a row is selected
        cur = self._selected_apikey()
        if cur:
            prov_entry.set_text(cur)
            prov_entry.set_sensitive(False)

        dlg.show_all()
        if dlg.run() == Gtk.ResponseType.OK:
            provider = prov_entry.get_text().strip()
            key = key_entry.get_text().strip()
            if provider and key:
                ok, msg = aim_set_apikey(provider, key)
                if ok:
                    self._load_apikeys()
                    self.set_status("已保存 %s 的 API Key" % provider)
                else:
                    self.set_status("设置失败: %s" % msg, error=True)
        dlg.destroy()

    def _on_apikey_delete(self, w):
        prov = self._selected_apikey()
        if not prov:
            self.set_status("请先选择要删除的 Provider", error=True)
            return
        dlg = Gtk.MessageDialog(
            transient_for=self, modal=True,
            message_type=Gtk.MessageType.QUESTION,
            buttons=Gtk.ButtonsType.YES_NO,
            text="删除 Provider '%s' 的 API Key？" % prov)
        resp = dlg.run()
        dlg.destroy()
        if resp != Gtk.ResponseType.YES:
            return
        ok, msg = aim_remove_apikey(prov)
        if ok:
            self._load_apikeys()
            self.set_status("已删除 %s 的 API Key" % prov)
        else:
            self.set_status("删除失败: %s" % msg, error=True)

    def _on_configure_aim(self, w):
        self._run_terminal(["aim", "model", "switch"])

    def _on_configure_openclaw(self, w):
        self._run_terminal(["openclaw", "configure", "--section", "model"])

    def _run_terminal(self, argv):
        cmdline = " ".join("'%s'" % a if " " in a else a for a in argv)
        for term in ("ptyxis", "x-terminal-emulator", "gnome-terminal", "kgx"):
            path = subprocess.run(["which", term], capture_output=True,
                                  text=True).stdout.strip()
            if path:
                if term == "ptyxis":
                    cmd = [path, "--", "bash", "-c",
                           "%s; echo -e '\n[按回车关闭...]'; read" % cmdline]
                elif term == "gnome-terminal":
                    cmd = [path, "--", "bash", "-c",
                           "%s; echo -e '\n[按回车关闭...]'; read" % cmdline]
                else:
                    cmd = [path, "-e", "bash", "-c",
                           "%s; echo -e '\n[按回车关闭...]'; read" % cmdline]
                try:
                    subprocess.Popen(cmd)
                    self.set_status("已启动终端: %s" % argv[0])
                except Exception as e:
                    self.set_status("启动终端失败: %s" % e, error=True)
                return
        self.set_status("未找到可用终端程序", error=True)

    # ---------------------------------------------------- provider tab
    def _build_provider_tab(self, notebook):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        box.set_margin_start(16)
        box.set_margin_end(16)
        box.set_margin_top(16)
        box.set_margin_bottom(16)

        note = Gtk.Label(
            label="自定义 Provider 写入 opencode.jsonc 的 provider 段，含 baseURL / apiKey / models。",
            xalign=0)
        note.set_halign(Gtk.Align.START)
        note.get_style_context().add_class("dim-label")
        box.pack_start(note, False, False, 0)

        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        scroll.set_vexpand(True)
        box.pack_start(scroll, True, True, 0)

        self.provider_store = Gtk.ListStore(str, str, str)  # id, name, baseURL
        self.provider_view = Gtk.TreeView(model=self.provider_store)
        for title, idx in (("Provider ID", 0), ("名称", 1), ("BaseURL", 2)):
            col = Gtk.TreeViewColumn(title, Gtk.CellRendererText(), text=idx)
            self.provider_view.append_column(col)
        scroll.add(self.provider_view)

        btn_row = Gtk.Box(spacing=8)
        box.pack_start(btn_row, False, False, 0)

        add_btn = Gtk.Button(label="添加")
        add_btn.connect("clicked", self._on_provider_add)
        btn_row.pack_start(add_btn, False, False, 0)
        edit_btn = Gtk.Button(label="编辑")
        edit_btn.connect("clicked", self._on_provider_edit)
        btn_row.pack_start(edit_btn, False, False, 0)
        del_btn = Gtk.Button(label="删除")
        del_btn.connect("clicked", self._on_provider_delete)
        btn_row.pack_start(del_btn, False, False, 0)

        notebook.append_page(box, Gtk.Label(label="自定义 Provider"))

    def _selected_provider(self):
        sel = self.provider_view.get_selection()
        model, it = sel.get_selected()
        if it is None:
            return None
        return model[it][0]

    def _on_provider_add(self, w):
        dialog = ProviderDialog(self)
        if dialog.run() == Gtk.ResponseType.OK:
            data = dialog.get_data()
            self._save_provider(data)
        dialog.destroy()

    def _on_provider_edit(self, w):
        pid = self._selected_provider()
        if not pid:
            self.set_status("请先选择要编辑的 Provider", error=True)
            return
        cfg = read_config()
        prov = cfg.get("provider", {}).get(pid, {})
        dialog = ProviderDialog(self, pid=pid, data=prov)
        if dialog.run() == Gtk.ResponseType.OK:
            data = dialog.get_data()
            self._save_provider(data)
        dialog.destroy()

    def _on_provider_delete(self, w):
        pid = self._selected_provider()
        if not pid:
            self.set_status("请先选择要删除的 Provider", error=True)
            return
        dialog = Gtk.MessageDialog(
            transient_for=self, modal=True,
            message_type=Gtk.MessageType.QUESTION,
            buttons=Gtk.ButtonsType.YES_NO,
            text="删除 Provider '%s'？" % pid)
        dialog.format_secondary_text("将从 opencode.jsonc 中移除该 provider 配置。")
        resp = dialog.run()
        dialog.destroy()
        if resp != Gtk.ResponseType.YES:
            return
        text = read_config_text()
        try:
            text = jsonc.delete_key(text, ["provider", pid])
            # remove empty provider object if left behind
            cfg = read_config()
            if "provider" in cfg and not cfg.get("provider"):
                text = jsonc.delete_key(text, ["provider"])
        except jsonc.JsoncError as e:
            self.set_status("删除失败: %s" % e, error=True)
            return
        write_config_text(text)
        self._load_providers()
        self.set_status("已删除 Provider: %s" % pid)

    def _save_provider(self, data):
        text = read_config_text()
        pid = data["id"]
        if not pid:
            self.set_status("Provider ID 不能为空", error=True)
            return
        provider = {"npm": data.get("npm") or DEFAULT_NPM}
        if data.get("name"):
            provider["name"] = data["name"]
        options = {}
        if data.get("baseURL"):
            options["baseURL"] = data["baseURL"]
        if data.get("apiKey"):
            options["apiKey"] = data["apiKey"]
        if options:
            provider["options"] = options
        models = {}
        for mid in data.get("models", []):
            models[mid] = {"name": mid}
        if models:
            provider["models"] = models
        try:
            text = jsonc.set_value(text, ["provider", pid], provider)
        except jsonc.JsoncError as e:
            self.set_status("保存 Provider 失败: %s" % e, error=True)
            return
        write_config_text(text)
        self._load_providers()
        self.set_status("已保存 Provider: %s" % pid)

    # ------------------------------------------------------------ loading
    def _load_all(self):
        self._populate_models()
        self._load_defaults()
        self._load_providers()
        self._load_engine()
        self._load_apikeys()

    def _load_defaults(self):
        cfg = read_config()
        self._combo_set(self.model_combo, cfg.get("model", ""))
        self._combo_set(self.small_combo, cfg.get("small_model", ""))

    def _load_providers(self):
        self.provider_store.clear()
        cfg = read_config()
        provs = cfg.get("provider", {})
        for pid, prov in provs.items():
            if not isinstance(prov, dict):
                continue
            name = prov.get("name", "")
            options = prov.get("options") or {}
            base_url = options.get("baseURL", "") if isinstance(options, dict) else ""
            self.provider_store.append([pid, name, base_url])


class ProviderDialog(Gtk.Dialog):
    """Add/edit provider dialog."""

    def __init__(self, parent, pid=None, data=None):
        super().__init__(transient_for=parent, modal=True, title="Provider 配置")
        self.set_default_size(440, 420)
        self.add_button("取消", Gtk.ResponseType.CANCEL)
        self.add_button("保存", Gtk.ResponseType.OK)

        data = data or {}
        box = self.get_content_area()
        box.set_spacing(8)
        box.set_margin_start(12)
        box.set_margin_end(12)
        box.set_margin_top(12)
        box.set_margin_bottom(12)

        grid = Gtk.Grid(column_spacing=8, row_spacing=8)
        box.pack_start(grid, False, False, 0)

        grid.attach(Gtk.Label(label="Provider ID", xalign=1), 0, 0, 1, 1)
        self.id_entry = Gtk.Entry(text=pid or "")
        self.id_entry.set_placeholder_text("如 my-provider")
        grid.attach(self.id_entry, 1, 0, 1, 1)

        grid.attach(Gtk.Label(label="显示名称", xalign=1), 0, 1, 1, 1)
        self.name_entry = Gtk.Entry(text=data.get("name", ""))
        grid.attach(self.name_entry, 1, 1, 1, 1)

        grid.attach(Gtk.Label(label="npm 包", xalign=1), 0, 2, 1, 1)
        self.npm_entry = Gtk.Entry(text=data.get("npm", DEFAULT_NPM))
        grid.attach(self.npm_entry, 1, 2, 1, 1)

        grid.attach(Gtk.Label(label="Base URL", xalign=1), 0, 3, 1, 1)
        options = data.get("options") or {}
        opts = options if isinstance(options, dict) else {}
        self.url_entry = Gtk.Entry(text=opts.get("baseURL", ""))
        self.url_entry.set_placeholder_text("http://127.0.0.1:8000/v1")
        grid.attach(self.url_entry, 1, 3, 1, 1)

        grid.attach(Gtk.Label(label="API Key", xalign=1), 0, 4, 1, 1)
        self.key_entry = Gtk.Entry(text=opts.get("apiKey", ""))
        self.key_entry.set_visibility(False)
        grid.attach(self.key_entry, 1, 4, 1, 1)

        grid.attach(Gtk.Label(label="模型 ID", xalign=1), 0, 5, 1, 1)
        self.models_text = Gtk.TextView()
        self.models_text.set_size_request(-1, 120)
        self.models_text.set_accepts_tab(False)
        mod = data.get("models")
        if isinstance(mod, dict):
            existing = "\n".join(mod.keys())
        else:
            existing = ""
        self.models_text.get_buffer().set_text(existing)
        sw = Gtk.ScrolledWindow()
        sw.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        sw.add(self.models_text)
        grid.attach(sw, 1, 5, 1, 1)

        hint = Gtk.Label(label="每行一个模型 ID，如 qwen3-coder:a3b", xalign=0)
        hint.get_style_context().add_class("dim-label")
        grid.attach(hint, 1, 6, 1, 1)

        self.show_all()

    def get_data(self):
        pid = self.id_entry.get_text().strip()
        buf = self.models_text.get_buffer()
        models = [l.strip() for l in buf.get_text(buf.get_start_iter(), buf.get_end_iter(), True).splitlines() if l.strip()]
        return {
            "id": pid,
            "name": self.name_entry.get_text().strip(),
            "npm": self.npm_entry.get_text().strip(),
            "baseURL": self.url_entry.get_text().strip(),
            "apiKey": self.key_entry.get_text().strip(),
            "models": models,
        }


class App(object):
    def __init__(self):
        self.win = None

    def run(self):
        self.win = MainWindow()
        self.win.show_all()
        Gtk.main()


def main():
    css = """
    #status-error { color: #cc0000; }
    """
    provider = Gtk.CssProvider()
    provider.load_from_data(css.encode())
    Gtk.StyleContext.add_provider_for_screen(
        Gdk.Screen.get_default(), provider,
        Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
    app = App()
    app.run()


if __name__ == "__main__":
    main()
