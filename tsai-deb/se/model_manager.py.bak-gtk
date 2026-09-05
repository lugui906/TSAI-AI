#!/usr/bin/env python3
"""AI 模型管理器 - 管理 opencode / aim 的默认模型、Provider 与 AI 引擎。

- 统一读写 ~/.config/opencode/opencode.jsonc（aim 底层委托 opencode，二者共用）。
- 支持设置默认模型 (model) 与小型模型 (small_model)。
- 支持添加/编辑/删除自定义 Provider（baseURL + apiKey + models）。
- 支持 AIM 引擎切换（opencode / openclaw，对应 `aim oc`）。
- 支持管理 Provider API Key（对应 `aim apikey`）。
"""

import json
import os
import subprocess
import sys

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
from gi.repository import Gtk, Gdk, GLib
GLib.set_prgname("org.chindows.se-model-manager")
Gtk.Window.set_default_icon_name("preferences-system")


import jsonc

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


def _is_vision_model(model):
    """Return True if a model dict is configured as vision/multimodal."""
    if not isinstance(model, dict):
        return False
    if model.get("attachment"):
        return True
    mod = model.get("modalities")
    if isinstance(mod, dict) and isinstance(mod.get("input"), list):
        return "image" in mod.get("input", [])
    return False


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


# ---------------------------------------------------------------- OpenCode Zen

ZEN_PROVIDER_ID = "zen"
ZEN_BASE_URL = "https://opencode.ai/zen/v1"
ZEN_MODELS = [
    ("big-pickle", "Big Pickle"),
    ("mimo-v2.5-free", "MiMo-V2.5 Free"),
    ("hy3-free", "Hy3 Free"),
    ("nemotron-3-ultra-free", "Nemotron 3 Ultra Free"),
    ("nemotron-3.5-lightning-free", "Nemotron 3.5 Lightning Free"),
]
AUTH_PATH = os.path.expanduser("~/.local/share/opencode/auth.json")


def zen_provider_configured():
    """Return True when the 'zen' provider exists in opencode.jsonc."""
    cfg = read_config()
    prov = cfg.get("provider", {})
    return isinstance(prov.get(ZEN_PROVIDER_ID), dict)


def zen_write_provider():
    """Enable the zen free-model provider in opencode.jsonc."""
    provider = {
        "npm": DEFAULT_NPM,
        "name": "OpenCode Zen 免费模型",
        "options": {"baseURL": ZEN_BASE_URL},
        "models": {mid: {"name": name} for mid, name in ZEN_MODELS},
    }
    text = read_config_text()
    text = jsonc.set_value(text, ["provider", ZEN_PROVIDER_ID], provider)
    write_config_text(text)


def zen_remove_provider():
    """Remove the zen provider from opencode.jsonc."""
    text = read_config_text()
    try:
        text = jsonc.delete_key(text, ["provider", ZEN_PROVIDER_ID])
    except jsonc.JsoncError:
        return
    cfg = read_config()
    if "provider" in cfg and not cfg.get("provider"):
        try:
            text = jsonc.delete_key(text, ["provider"])
        except jsonc.JsoncError:
            pass
    write_config_text(text)


def _load_auth():
    try:
        with open(AUTH_PATH, encoding="utf-8") as f:
            auth = json.load(f)
        return auth if isinstance(auth, dict) else {}
    except (OSError, ValueError):
        return {}


def _save_auth(auth):
    os.makedirs(os.path.dirname(AUTH_PATH), exist_ok=True)
    tmp = AUTH_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(auth, f, ensure_ascii=False, indent=2)
    os.replace(tmp, AUTH_PATH)


def zen_get_key():
    """Return the OpenCode Zen API key stored in opencode's auth.json."""
    entry = _load_auth().get("opencode")
    if isinstance(entry, dict):
        return entry.get("key", "")
    return ""


def zen_set_key(key):
    """Set the OpenCode Zen API key (empty string clears it)."""
    auth = _load_auth()
    key = (key or "").strip()
    if key:
        auth["opencode"] = {"type": "api", "key": key}
    else:
        auth.pop("opencode", None)
    _save_auth(auth)


class MainWindow(Gtk.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title="AI 模型管理器")
        self.set_default_size(680, 520)

        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.set_child(vbox)

        header = Gtk.HeaderBar()
        header.set_show_title_buttons(True)
        title_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        title_lbl = Gtk.Label(label="AI 模型管理器")
        sub_lbl = Gtk.Label(label="模型 / Provider / 引擎 (opencode·openclaw)")
        sub_lbl.add_css_class("dim-label")
        title_box.append(title_lbl)
        title_box.append(sub_lbl)
        header.set_title_widget(title_box)
        self.set_titlebar(header)

        self.status_label = Gtk.Label(label="就绪")
        self.status_label.set_halign(Gtk.Align.START)
        self.status_label.set_margin_start(10)
        self.status_label.set_margin_end(10)
        self.status_label.set_margin_top(6)
        self.status_label.set_margin_bottom(6)

        notebook = Gtk.Notebook()
        notebook.set_vexpand(True)
        vbox.append(notebook)

        self._build_default_tab(notebook)
        self._build_provider_tab(notebook)
        self._build_engine_tab(notebook)
        self._build_zen_tab(notebook)

        vbox.append(self.status_label)

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

        note = Gtk.Label(label="AIM 底层委托 opencode，两者共用该配置。")
        note.set_halign(Gtk.Align.START)
        note.add_css_class("dim-label")
        box.append(note)

        grid = Gtk.Grid(column_spacing=10, row_spacing=8)
        box.append(grid)

        def _right_lbl(text):
            lbl = Gtk.Label(label=text)
            lbl.set_halign(Gtk.Align.END)
            return lbl

        grid.attach(_right_lbl("默认模型 (model)"), 0, 0, 1, 1)
        self.model_combo = self._make_combo()
        grid.attach(self.model_combo, 1, 0, 1, 1)

        grid.attach(_right_lbl("小型模型 (small_model)"), 0, 1, 1, 1)
        self.small_combo = self._make_combo()
        grid.attach(self.small_combo, 1, 1, 1, 1)

        hint = Gtk.Label(label="可在下拉框中输入自定义模型 ID（如 provider/model）")
        hint.set_halign(Gtk.Align.START)
        hint.add_css_class("dim-label")
        box.append(hint)

        btn_row = Gtk.Box(spacing=8)
        box.append(btn_row)

        refresh_btn = Gtk.Button(label="刷新模型列表")
        refresh_btn.connect("clicked", self._on_refresh)
        btn_row.append(refresh_btn)

        save_btn = Gtk.Button(label="保存默认模型")
        save_btn.add_css_class("suggested-action")
        save_btn.connect("clicked", self._on_save_defaults)
        btn_row.append(save_btn)

        # model list view
        list_scroll = Gtk.ScrolledWindow()
        list_scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        list_scroll.set_vexpand(True)
        box.append(list_scroll)

        self.models_store = Gtk.ListStore(str)
        self.models_view = Gtk.TreeView(model=self.models_store)
        renderer = Gtk.CellRendererText()
        col = Gtk.TreeViewColumn("可用模型", renderer, text=0)
        self.models_view.append_column(col)
        self.models_view.set_headers_visible(False)
        self.models_view.get_selection().connect("changed", self._on_models_selection)
        list_scroll.set_child(self.models_view)

        use_row = Gtk.Box(spacing=8)
        box.append(use_row)
        b1 = Gtk.Button(label="设为主模型")
        b1.connect("clicked", lambda w: self._set_from_selection(self.model_combo))
        use_row.append(b1)
        b2 = Gtk.Button(label="设为小模型")
        b2.connect("clicked", lambda w: self._set_from_selection(self.small_combo))
        use_row.append(b2)

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
            label="配置 AIM 使用的 AI 引擎（opencode / openclaw）与 Provider API Key。")
        note.set_halign(Gtk.Align.START)
        note.add_css_class("dim-label")
        box.append(note)

        # ---- engine switch frame
        eng_frame = Gtk.Frame(label="AI 引擎")
        eng_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        eng_box.set_margin_start(12)
        eng_box.set_margin_end(12)
        eng_box.set_margin_top(8)
        eng_box.set_margin_bottom(12)
        eng_frame.set_child(eng_box)
        box.append(eng_frame)

        eng_row = Gtk.Box(spacing=8)
        eng_box.append(eng_row)

        self.engine_label = Gtk.Label(label="当前引擎: ...")
        self.engine_label.set_halign(Gtk.Align.START)
        self.engine_label.set_hexpand(True)
        eng_row.append(self.engine_label)

        self.btn_openclaw = Gtk.Button(label="切换到 openclaw")
        self.btn_openclaw.connect("clicked", lambda w: self._switch_engine("openclaw"))
        eng_row.append(self.btn_openclaw)

        self.btn_opencode = Gtk.Button(label="切换回 opencode")
        self.btn_opencode.connect("clicked", lambda w: self._switch_engine("opencode"))
        eng_row.append(self.btn_opencode)

        # ---- provider config buttons
        cfg_row = Gtk.Box(spacing=8)
        eng_box.append(cfg_row)

        cfg_note = Gtk.Label(label="配置 Provider：")
        cfg_note.set_halign(Gtk.Align.START)
        cfg_row.append(cfg_note)

        b_aim = Gtk.Button(label="aim 提供方")
        b_aim.set_tooltip_text("运行 aim model switch（委托 opencode providers）")
        b_aim.connect("clicked", self._on_configure_aim)
        cfg_row.append(b_aim)

        b_oc = Gtk.Button(label="openclaw 提供方")
        b_oc.set_tooltip_text("运行 openclaw configure --section model")
        b_oc.connect("clicked", self._on_configure_openclaw)
        cfg_row.append(b_oc)

        # ---- api key management frame
        key_frame = Gtk.Frame(label="Provider API Key (aim apikey)")
        key_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        key_box.set_margin_start(12)
        key_box.set_margin_end(12)
        key_box.set_margin_top(8)
        key_box.set_margin_bottom(12)
        key_frame.set_child(key_box)
        box.append(key_frame)

        key_scroll = Gtk.ScrolledWindow()
        key_scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        key_scroll.set_vexpand(True)
        key_box.append(key_scroll)

        self.apikey_store = Gtk.ListStore(str, str)
        self.apikey_view = Gtk.TreeView(model=self.apikey_store)
        for title, idx in (("Provider", 0), ("Key", 1)):
            col = Gtk.TreeViewColumn(title, Gtk.CellRendererText(), text=idx)
            self.apikey_view.append_column(col)
        self.apikey_view.set_headers_visible(True)
        key_scroll.set_child(self.apikey_view)

        key_btn_row = Gtk.Box(spacing=8)
        key_box.append(key_btn_row)

        b_add = Gtk.Button(label="添加/修改 Key")
        b_add.connect("clicked", self._on_apikey_add)
        key_btn_row.append(b_add)

        b_del = Gtk.Button(label="删除 Key")
        b_del.connect("clicked", self._on_apikey_delete)
        key_btn_row.append(b_del)

        b_refresh = Gtk.Button(label="刷新")
        b_refresh.connect("clicked", lambda w: self._load_apikeys())
        key_btn_row.append(b_refresh)

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
        box.append(grid)

        def _right_lbl(text):
            lbl = Gtk.Label(label=text)
            lbl.set_halign(Gtk.Align.END)
            return lbl

        grid.attach(_right_lbl("Provider"), 0, 0, 1, 1)
        prov_entry = Gtk.Entry()
        prov_entry.set_placeholder_text("如 openai / anthropic / deepseek")
        grid.attach(prov_entry, 1, 0, 1, 1)

        grid.attach(_right_lbl("API Key"), 0, 1, 1, 1)
        key_entry = Gtk.Entry()
        key_entry.set_visibility(False)
        grid.attach(key_entry, 1, 1, 1, 1)

        # prefill when a row is selected
        cur = self._selected_apikey()
        if cur:
            prov_entry.set_text(cur)
            prov_entry.set_sensitive(False)

        dlg.connect("response", self._on_apikey_add_response, prov_entry, key_entry)
        dlg.present()

    def _on_apikey_add_response(self, dlg, response, prov_entry, key_entry):
        if response == Gtk.ResponseType.OK:
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
        dlg.connect("response", self._on_apikey_delete_response, prov)
        dlg.present()

    def _on_apikey_delete_response(self, dlg, response, prov):
        dlg.destroy()
        if response != Gtk.ResponseType.YES:
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
            label="自定义 Provider 写入 opencode.jsonc 的 provider 段，含 baseURL / apiKey / models。")
        note.set_halign(Gtk.Align.START)
        note.add_css_class("dim-label")
        box.append(note)

        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        scroll.set_vexpand(True)
        box.append(scroll)

        self.provider_store = Gtk.ListStore(str, str, str)  # id, name, baseURL
        self.provider_view = Gtk.TreeView(model=self.provider_store)
        for title, idx in (("Provider ID", 0), ("名称", 1), ("BaseURL", 2)):
            col = Gtk.TreeViewColumn(title, Gtk.CellRendererText(), text=idx)
            self.provider_view.append_column(col)
        scroll.set_child(self.provider_view)

        btn_row = Gtk.Box(spacing=8)
        box.append(btn_row)

        add_btn = Gtk.Button(label="添加")
        add_btn.connect("clicked", self._on_provider_add)
        btn_row.append(add_btn)
        edit_btn = Gtk.Button(label="编辑")
        edit_btn.connect("clicked", self._on_provider_edit)
        btn_row.append(edit_btn)
        del_btn = Gtk.Button(label="删除")
        del_btn.connect("clicked", self._on_provider_delete)
        btn_row.append(del_btn)

        notebook.append_page(box, Gtk.Label(label="自定义 Provider"))

    def _selected_provider(self):
        sel = self.provider_view.get_selection()
        model, it = sel.get_selected()
        if it is None:
            return None
        return model[it][0]

    def _on_provider_add(self, w):
        dialog = ProviderDialog(self)
        dialog.connect("response", self._on_provider_dialog_response, dialog)
        dialog.present()

    def _on_provider_edit(self, w):
        pid = self._selected_provider()
        if not pid:
            self.set_status("请先选择要编辑的 Provider", error=True)
            return
        cfg = read_config()
        prov = cfg.get("provider", {}).get(pid, {})
        dialog = ProviderDialog(self, pid=pid, data=prov)
        dialog.connect("response", self._on_provider_dialog_response, dialog)
        dialog.present()

    def _on_provider_dialog_response(self, _dlg, response, dialog):
        if response == Gtk.ResponseType.OK:
            data = dialog.get_data()
            self._save_provider(data)
        dialog.destroy()

    def _on_provider_delete(self, w):
        pid = self._selected_provider()
        if not pid:
            self.set_status("请先选择要删除的 Provider", error=True)
            return
        dlg = Gtk.MessageDialog(
            transient_for=self, modal=True,
            message_type=Gtk.MessageType.QUESTION,
            buttons=Gtk.ButtonsType.YES_NO,
            text="删除 Provider '%s'？" % pid)
        dlg.format_secondary_text("将从 opencode.jsonc 中移除该 provider 配置。")
        dlg.connect("response", self._on_provider_delete_response, pid)
        dlg.present()

    def _on_provider_delete_response(self, dlg, response, pid):
        dlg.destroy()
        if response != Gtk.ResponseType.YES:
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
        for entry in data.get("models", []):
            mid = entry
            vision = False
            if "|" in entry:
                mid, flag = entry.split("|", 1)
                mid = mid.strip()
                vision = flag.strip().lower() in (
                    "vision", "v", "image", "img", "mm", "multimodal")
            if not mid:
                continue
            if vision:
                models[mid] = {
                    "name": mid,
                    "attachment": True,
                    "modalities": {"input": ["text", "image"], "output": ["text"]},
                }
            else:
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

    # ---------------------------------------------------- zen free-model tab
    def _build_zen_tab(self, notebook):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        box.set_margin_start(16)
        box.set_margin_end(16)
        box.set_margin_top(16)
        box.set_margin_bottom(16)

        note = Gtk.Label(
            label="OpenCode Zen 提供一批免费模型（big-pickle / MiMo-V2.5 Free / Hy3 Free / Nemotron 免费）。"
                  "\n免费模型无需 Key 即可使用；如需付费模型或在 Zen 平台登记用量，可在此填写 API Key。",
            wrap=True)
        note.set_halign(Gtk.Align.START)
        note.add_css_class("dim-label")
        box.append(note)

        # ---- status + enable/disable
        status_box = Gtk.Box(spacing=8)
        box.append(status_box)

        self.zen_status = Gtk.Label(label="…")
        self.zen_status.set_halign(Gtk.Align.START)
        self.zen_status.set_hexpand(True)
        status_box.append(self.zen_status)

        enable_btn = Gtk.Button(label="一键启用")
        enable_btn.add_css_class("suggested-action")
        enable_btn.connect("clicked", self._on_zen_enable)
        status_box.append(enable_btn)

        disable_btn = Gtk.Button(label="停用")
        disable_btn.connect("clicked", self._on_zen_disable)
        status_box.append(disable_btn)

        # ---- api key
        key_frame = Gtk.Frame(label="Zen API Key（可选）")
        key_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        key_box.set_margin_start(12)
        key_box.set_margin_end(12)
        key_box.set_margin_top(8)
        key_box.set_margin_bottom(12)
        key_frame.set_child(key_box)
        box.append(key_frame)

        key_hint = Gtk.Label(
            label="到 https://opencode.ai/zen 获取。免费模型可留空。写入 opencode auth.json。",
            wrap=True)
        key_hint.set_halign(Gtk.Align.START)
        key_hint.add_css_class("dim-label")
        key_box.append(key_hint)

        key_row = Gtk.Box(spacing=8)
        key_box.append(key_row)

        self.zen_key_entry = Gtk.Entry()
        self.zen_key_entry.set_visibility(False)
        self.zen_key_entry.set_placeholder_text("sk-…")
        self.zen_key_entry.set_hexpand(True)
        key_row.append(self.zen_key_entry)

        save_key = Gtk.Button(label="保存 Key")
        save_key.connect("clicked", self._on_zen_save_key)
        key_row.append(save_key)

        clear_key = Gtk.Button(label="清除 Key")
        clear_key.connect("clicked", self._on_zen_clear_key)
        key_row.append(clear_key)

        # ---- set default model
        model_frame = Gtk.Frame(label="设为默认模型")
        model_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        model_box.set_margin_start(12)
        model_box.set_margin_end(12)
        model_box.set_margin_top(8)
        model_box.set_margin_bottom(12)
        model_frame.set_child(model_box)
        box.append(model_frame)

        model_row = Gtk.Box(spacing=8)
        model_box.append(model_row)

        self.zen_model_combo = Gtk.ComboBoxText()
        for mid, name in ZEN_MODELS:
            self.zen_model_combo.append_text("zen/%s (%s)" % (mid, name))
        self.zen_model_combo.set_active(0)
        self.zen_model_combo.set_hexpand(True)
        model_row.append(self.zen_model_combo)

        set_model = Gtk.Button(label="设为默认模型")
        set_model.connect("clicked", self._on_zen_set_default)
        model_row.append(set_model)

        sm_hint = Gtk.Label(
            label="同时会把该模型设为默认 model，小模型不变。",
            wrap=True)
        sm_hint.set_halign(Gtk.Align.START)
        sm_hint.add_css_class("dim-label")
        model_box.append(sm_hint)

        notebook.append_page(box, Gtk.Label(label="Zen 免费模型"))

    def _load_zen(self):
        if zen_provider_configured():
            self.zen_status.set_text("状态: 已启用（%d 个免费模型）" % len(ZEN_MODELS))
        else:
            self.zen_status.set_text("状态: 未启用")
        key = zen_get_key()
        if key:
            masked = key[:4] + "*" * (len(key) - 8) + key[-4:] if len(key) > 8 else "***"
            self.zen_key_entry.set_text(key)
            self.zen_key_entry.set_tooltip_text("已配置 Key: %s" % masked)
        else:
            self.zen_key_entry.set_text("")
            self.zen_key_entry.set_tooltip_text("未配置 Key（免费模型无需 Key）")

    def _on_zen_enable(self, w):
        zen_write_provider()
        self._load_zen()
        self._populate_models()
        self._load_providers()
        self.set_status("已启用 OpenCode Zen 免费模型")

    def _on_zen_disable(self, w):
        zen_remove_provider()
        self._load_zen()
        self._populate_models()
        self._load_providers()
        self.set_status("已停用 OpenCode Zen 免费模型")

    def _on_zen_save_key(self, w):
        key = self.zen_key_entry.get_text().strip()
        zen_set_key(key)
        self._load_zen()
        self.set_status("Zen Key 已%s" % ("保存" if key else "清除"))

    def _on_zen_clear_key(self, w):
        zen_set_key("")
        self._load_zen()
        self.set_status("Zen Key 已清除")

    def _on_zen_set_default(self, w):
        idx = self.zen_model_combo.get_active()
        if idx < 0:
            return
        mid = ZEN_MODELS[idx][0]
        model_id = "%s/%s" % (ZEN_PROVIDER_ID, mid)
        text = read_config_text()
        text = jsonc.set_value(text, ["model"], model_id)
        write_config_text(text)
        self._load_zen()
        self._load_defaults()
        self.set_status("默认模型已设为 %s" % model_id)

    # ------------------------------------------------------------ loading
    def _load_all(self):
        self._populate_models()
        self._load_defaults()
        self._load_providers()
        self._load_engine()
        self._load_apikeys()
        self._load_zen()

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
        box.append(grid)

        def _right_lbl(text):
            lbl = Gtk.Label(label=text)
            lbl.set_halign(Gtk.Align.END)
            return lbl

        grid.attach(_right_lbl("Provider ID"), 0, 0, 1, 1)
        self.id_entry = Gtk.Entry(text=pid or "")
        self.id_entry.set_placeholder_text("如 my-provider")
        grid.attach(self.id_entry, 1, 0, 1, 1)

        grid.attach(_right_lbl("显示名称"), 0, 1, 1, 1)
        self.name_entry = Gtk.Entry(text=data.get("name", ""))
        grid.attach(self.name_entry, 1, 1, 1, 1)

        grid.attach(_right_lbl("npm 包"), 0, 2, 1, 1)
        self.npm_entry = Gtk.Entry(text=data.get("npm", DEFAULT_NPM))
        grid.attach(self.npm_entry, 1, 2, 1, 1)

        grid.attach(_right_lbl("Base URL"), 0, 3, 1, 1)
        options = data.get("options") or {}
        opts = options if isinstance(options, dict) else {}
        self.url_entry = Gtk.Entry(text=opts.get("baseURL", ""))
        self.url_entry.set_placeholder_text("http://127.0.0.1:8000/v1")
        grid.attach(self.url_entry, 1, 3, 1, 1)

        grid.attach(_right_lbl("API Key"), 0, 4, 1, 1)
        self.key_entry = Gtk.Entry(text=opts.get("apiKey", ""))
        self.key_entry.set_visibility(False)
        grid.attach(self.key_entry, 1, 4, 1, 1)

        grid.attach(_right_lbl("模型 ID"), 0, 5, 1, 1)
        self.models_text = Gtk.TextView()
        self.models_text.set_size_request(-1, 120)
        self.models_text.set_accepts_tab(False)
        mod = data.get("models")
        if isinstance(mod, dict):
            existing = "\n".join(
                mid + ("|vision" if _is_vision_model(m) else "")
                for mid, m in mod.items())
        else:
            existing = ""
        self.models_text.get_buffer().set_text(existing)
        sw = Gtk.ScrolledWindow()
        sw.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        sw.set_vexpand(True)
        sw.set_child(self.models_text)
        grid.attach(sw, 1, 5, 1, 1)

        hint = Gtk.Label(label="每行一个模型 ID；支持视觉(多模态)的模型请加 |vision，如 qwen3-coder:a3b|vision")
        hint.set_halign(Gtk.Align.START)
        hint.add_css_class("dim-label")
        grid.attach(hint, 1, 6, 1, 1)

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


def main():
    if chstyle:
        chstyle.apply_gtk4()
    provider = Gtk.CssProvider()
    provider.load_from_data(b"#status-error { color: #cc0000; }")
    Gtk.StyleContext.add_provider_for_display(
        Gdk.Display.get_default(), provider,
        Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

    app = Gtk.Application(application_id="org.chindows.se-model-manager")
    state = {"win": None}

    def activate(application):
        if state["win"] is None:
            state["win"] = MainWindow(application)
        state["win"].present()

    app.connect("activate", activate)
    app.run(None)


if __name__ == "__main__":
    main()
