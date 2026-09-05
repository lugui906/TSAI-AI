import os
import sys
import threading
import json
import requests
import subprocess
import tempfile
import re
import shutil
import time
import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
from gi.repository import Gtk, GLib, Gio, Pango, Gdk

CONFIG_DIR = os.path.expanduser("~/.ai-assistant")
CONFIG_FILE = os.path.join(CONFIG_DIR, "config.json")
HISTORY_DIR = os.path.expanduser("~/.chinai2")
HISTORY_FILE = os.path.join(HISTORY_DIR, "history.json")
MAX_HISTORY = 200

DEFAULT_CONFIG = {
    "backend": "aim",
    "ollama_url": "http://localhost:11434",
    "ollama_model": "llama3",
    "aim_model": "opencode/deepseek-v4-flash-free",
    "workspace": "",
    "system_prompt": "",
    "search_provider": "duckduckgo",
    "window_width": 900,
    "window_height": 600,
}


def load_config():
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r") as f:
                config = json.load(f)
                for key, value in DEFAULT_CONFIG.items():
                    if key not in config:
                        config[key] = value
                return config
        except Exception:
            return DEFAULT_CONFIG.copy()
    return DEFAULT_CONFIG.copy()


def save_config(config):
    os.makedirs(CONFIG_DIR, exist_ok=True)
    with open(CONFIG_FILE, "w") as f:
        json.dump(config, f, indent=2)


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


def box_children(box):
    out = []
    child = box.get_first_child()
    while child is not None:
        out.append(child)
        child = child.get_next_sibling()
    return out


def clear_box(box):
    child = box.get_first_child()
    while child is not None:
        nxt = child.get_next_sibling()
        box.remove(child)
        child = nxt


class AIBackend:
    def chat(self, messages, model, callback=None):
        pass
    def get_models(self):
        return []
    def get_status(self):
        return "未知"
    def upload_file(self, file_path):
        return "不支持"
    def reset_conversation(self):
        pass


class OllamaBackend(AIBackend):
    def __init__(self, url="http://localhost:11434"):
        self.url = url.rstrip("/")
    def chat(self, messages, model, callback=None):
        payload = {"model": model, "messages": messages, "stream": True}
        try:
            response = requests.post(f"{self.url}/api/chat", json=payload, stream=True, timeout=300)
            response.raise_for_status()
            full_response = ""
            for line in response.iter_lines():
                if line:
                    try:
                        data = json.loads(line.decode("utf-8"))
                        if "message" in data and "content" in data["message"]:
                            content = data["message"]["content"]
                            full_response += content
                            if callback:
                                callback(content)
                        if data.get("done"):
                            break
                    except json.JSONDecodeError:
                        continue
            return full_response
        except requests.exceptions.RequestException as e:
            if callback:
                callback(f"错误: {str(e)}")
            return f"错误: {str(e)}"
    def get_models(self):
        try:
            response = requests.get(f"{self.url}/api/tags", timeout=10)
            response.raise_for_status()
            return [m["name"] for m in response.json().get("models", [])]
        except Exception:
            return []
    def get_status(self):
        try:
            r = requests.get(f"{self.url}/api/tags", timeout=5)
            return "已连接" if r.status_code == 200 else f"错误: {r.status_code}"
        except Exception:
            return "未连接"
    def upload_file(self, file_path):
        try:
            with open(file_path, "rb") as f:
                requests.post(f"{self.url}/api/chat", json={"model": "llama3", "messages": [{"role": "user", "content": f"分析文件: {file_path}"}]}, files={"file": f}, timeout=300)
            return "文件已上传"
        except Exception as e:
            return f"上传错误: {str(e)}"


class AimBackend(AIBackend):
    def __init__(self, workspace=""):
        self._conversation_started = False
        self._proc = None
        self.workspace = workspace if workspace and os.path.isdir(workspace) else None

    def stop(self):
        if self._proc is not None and self._proc.poll() is None:
            try:
                self._proc.kill()
            except Exception:
                pass
            self._proc = None

    def _switch_model(self, model):
        subprocess.run(["aim", "model", "switch", model], capture_output=True, text=True, timeout=30, cwd=self.workspace)
    def chat(self, messages, model, callback=None):
        self._switch_model(model)
        if not messages:
            return ""
        parts = []
        for m in messages:
            role = m.get("role", "user")
            content = m.get("content", "")
            if role == "system":
                parts.append(f"[系统设定]: {content}")
            elif role == "user":
                parts.append(f"[用户]: {content}")
            elif role == "assistant":
                parts.append(f"[助手]: {content}")
        prompt = "\n".join(parts)
        try:
            cmd = ["aim", "run" if self._conversation_started else "newrun", prompt]
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, cwd=self.workspace)
            self._proc = proc
            self._conversation_started = True
            full_response = ""
            for line in proc.stdout:
                if self._proc is not proc or proc.poll() is not None:
                    break
                full_response += line
                if callback:
                    callback(line)
            proc.wait(timeout=300)
            self._proc = None
            return full_response
        except subprocess.TimeoutExpired:
            proc.kill()
            e = "错误: AIM 执行超时"
            if callback:
                callback(e)
            return e
        except Exception as e:
            e = f"错误: {str(e)}"
            if callback:
                callback(e)
            return e
    def get_models(self):
        try:
            r = subprocess.run(["aim", "model", "list"], capture_output=True, text=True, timeout=30, cwd=self.workspace)
            if r.returncode == 0:
                models = [m.strip() for m in r.stdout.strip().splitlines() if m.strip()]
                if models:
                    return models
            return ["opencode/deepseek-v4-flash-free"]
        except Exception:
            return ["opencode/deepseek-v4-flash-free"]
    def get_status(self):
        try:
            r = subprocess.run(["aim", "model", "list"], capture_output=True, text=True, timeout=10, cwd=self.workspace)
            return "已连接" if r.returncode == 0 else f"错误: {r.returncode}"
        except Exception:
            return "未连接"
    def upload_file(self, file_path):
        try:
            with open(file_path, "rb") as f:
                content = f.read()
            content_str = content.decode("utf-8", errors="replace")
            r = subprocess.run(["aim", "newrun", f"分析这个文件: {file_path}\n\n{content_str[:2000]}"], capture_output=True, text=True, timeout=120, cwd=self.workspace)
            return f"文件已上传. 分析: {r.stdout.strip()[:500]}" if r.returncode == 0 else f"分析错误: {r.stderr.strip()}"
        except Exception as e:
            return f"上传错误: {str(e)}"
    def reset_conversation(self):
        self._conversation_started = False


def escape_pango(text):
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _copy_text(text):
    display = Gdk.Display.get_default()
    if display is None:
        return
    clipboard = display.get_clipboard()
    provider = Gdk.ContentProvider.new_for_bytes(GLib.Bytes.new(text.encode("utf-8")))
    clipboard.set_content(provider)


def render_markdown(text, on_run_code=None):
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)

    lines = text.split("\n")
    i = 0
    while i < len(lines):
        line = lines[i]

        if line.startswith("```"):
            lang = line[3:].strip()
            code_lines = []
            i += 1
            while i < len(lines) and not lines[i].startswith("```"):
                code_lines.append(lines[i])
                i += 1
            i += 1
            code_text = "\n".join(code_lines)

            frame = Gtk.Frame()
            frame.add_css_class("code-frame")

            vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)

            header = Gtk.Box(spacing=4)
            lang_label = Gtk.Label(label=lang if lang else "code")
            lang_label.set_halign(Gtk.Align.START)
            lang_label.add_css_class("code-lang")
            lang_label.set_margin_start(4)
            lang_label.set_hexpand(True)
            header.append(lang_label)

            if on_run_code:
                run_btn = Gtk.Button(label="运行")
                run_btn.set_size_request(50, 24)
                run_btn.connect("clicked", lambda b, t=code_text, l=lang: on_run_code(t, l))
                header.append(run_btn)

            copy_btn = Gtk.Button(label="复制")
            copy_btn.set_size_request(50, 24)
            copy_btn.connect("clicked", lambda b, t=code_text: _copy_text(t))
            header.append(copy_btn)

            vbox.append(header)

            tv = Gtk.TextView()
            tv.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
            tv.set_editable(False)
            tv.set_cursor_visible(False)
            tv.set_monospace(True)
            tv.get_buffer().set_text(code_text)
            tv.set_margin_start(4)
            tv.set_margin_end(4)
            tv.set_margin_top(2)
            tv.set_margin_bottom(2)
            vbox.append(tv)

            frame.set_child(vbox)
            box.append(frame)
            continue

        if line.startswith("|") and "|" in line[1:]:
            table_lines = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                table_lines.append(lines[i].strip())
                i += 1
            rows = []
            for tl in table_lines:
                cells = [c.strip() for c in tl.strip("|").split("|")]
                rows.append(cells)
            if len(rows) > 1:
                grid = Gtk.Grid()
                grid.set_row_spacing(2)
                grid.set_column_spacing(8)
                for ri, row in enumerate(rows):
                    if ri == 1 and all(re.match(r"^[-:]+$", c) for c in row if c):
                        continue
                    for ci, cell in enumerate(row):
                        lbl = Gtk.Label(label=escape_pango(cell))
                        lbl.set_halign(Gtk.Align.START)
                        lbl.set_use_markup(True)
                        if ri == 0 or (ri == 1 and len(rows) > 2 and all(re.match(r"^[-:]+$", c) for c in rows[1] if c)):
                            lbl.set_markup(f"<b>{escape_pango(cell)}</b>")
                        grid.attach(lbl, ci, ri, 1, 1)
                frame = Gtk.Frame()
                frame.set_child(grid)
                box.append(frame)
            continue

        if line.strip():
            formatted = _format_inline(line)
            lbl = Gtk.Label()
            lbl.set_halign(Gtk.Align.START)
            lbl.set_valign(Gtk.Align.START)
            lbl.set_markup(formatted)
            lbl.set_wrap(True)
            lbl.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
            lbl.set_margin_bottom(2)
            box.append(lbl)
        else:
            box.append(Gtk.Label(label=""))

        i += 1

    return box


def _format_inline(text):
    text = escape_pango(text)
    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)
    text = re.sub(r"\*(.+?)\*", r"<i>\1</i>", text)
    text = re.sub(r"`(.+?)`", r"<tt>\1</tt>", text)
    text = re.sub(r"^# (.+)$", r"<b><big>\1</big></b>", text, flags=re.MULTILINE)
    text = re.sub(r"^## (.+)$", r"<b>\1</b>", text, flags=re.MULTILINE)
    text = re.sub(r"^- (.+)$", r"\342\200\242 \1", text, flags=re.MULTILINE)
    return text


class ChatMessage(Gtk.Box):
    def __init__(self, role, content, on_retry=None, on_delete=None):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self.role = role
        self.on_retry = on_retry
        self.on_delete = on_delete

        header = Gtk.Box(spacing=4)
        role_label = Gtk.Label(label="你" if role == "user" else "AI")
        role_label.set_halign(Gtk.Align.START)
        role_label.add_css_class("message-role")
        role_label.set_hexpand(True)
        header.append(role_label)

        if on_retry and role == "assistant":
            retry_btn = Gtk.Button(label="重试")
            retry_btn.set_size_request(40, 20)
            retry_btn.connect("clicked", lambda b: on_retry(self))
            header.append(retry_btn)

        if on_delete:
            del_btn = Gtk.Button(label="删除")
            del_btn.set_size_request(40, 20)
            del_btn.connect("clicked", lambda b: on_delete(self))
            header.append(del_btn)

        copy_btn = Gtk.Button(label="复制")
        copy_btn.set_size_request(40, 20)
        copy_btn.connect("clicked", lambda b: _copy_text(content))
        header.append(copy_btn)

        self.append(header)

        scrolled = Gtk.ScrolledWindow()
        scrolled.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.NEVER)
        scrolled.set_propagate_natural_height(True)
        scrolled.set_vexpand(True)
        self.content_widget = render_markdown(content, on_run_code=self._run_code)
        scrolled.set_child(self.content_widget)
        self.append(scrolled)

        if role == "user":
            self.add_css_class("user-message")
        else:
            self.add_css_class("assistant-message")

    def _run_code(self, code, lang):
        threading.Thread(target=self._execute_code, args=(code, lang), daemon=True).start()

    def _execute_code(self, code, lang):
        output_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        output_box.set_margin_start(8)
        output_label = Gtk.Label()
        output_label.set_halign(Gtk.Align.START)
        output_label.set_markup("<i>运行中...</i>")
        output_box.append(output_label)
        GLib.idle_add(lambda: self.append(output_box))

        try:
            tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".py" if lang == "python" else ".sh", delete=False)
            tmp.write(code)
            tmp.close()
            os.chmod(tmp.name, 0o755)

            if lang == "python":
                proc = subprocess.run(["python3", tmp.name], capture_output=True, text=True, timeout=30)
            else:
                proc = subprocess.run(["bash", tmp.name], capture_output=True, text=True, timeout=30)

            out_text = proc.stdout.strip() or proc.stderr.strip() or "无输出"
            GLib.idle_add(lambda: output_label.set_markup(f"<b>输出:</b>\n{escape_pango(out_text[:2000])}"))
            os.unlink(tmp.name)
        except subprocess.TimeoutExpired:
            GLib.idle_add(lambda: output_label.set_markup("<b>错误:</b> 执行超时"))
        except Exception as e:
            GLib.idle_add(lambda: output_label.set_markup(f"<b>错误:</b> {escape_pango(str(e))}"))

    def update_content(self, content):
        scrolled = self.content_widget.get_parent()
        self.content_widget = render_markdown(content, on_run_code=self._run_code)
        scrolled.set_child(self.content_widget)


class SettingsDialog(Gtk.Dialog):
    def __init__(self, parent, config):
        super().__init__(title="设置", transient_for=parent, modal=True)
        self.config = config.copy()
        self.set_default_size(500, 500)
        ca = self.get_content_area()
        ca.set_spacing(12)
        ca.set_margin_start(12)
        ca.set_margin_end(12)
        ca.set_margin_top(12)
        ca.set_margin_bottom(12)
        nb = Gtk.Notebook()
        nb.set_vexpand(True)
        nb.append_page(self._create_ollama_page(), Gtk.Label(label="Ollama"))
        nb.append_page(self._create_aim_page(), Gtk.Label(label="AIM"))
        nb.append_page(self._create_agent_page(), Gtk.Label(label="智能体"))
        ca.append(nb)
        self.add_button("取消", Gtk.ResponseType.CANCEL)
        self.add_button("应用", Gtk.ResponseType.APPLY)

    def _create_ollama_page(self):
        b = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        b.set_margin_start(12); b.set_margin_end(12); b.set_margin_top(12); b.set_margin_bottom(12)
        lbl = Gtk.Label(label="Ollama 地址:")
        lbl.set_halign(Gtk.Align.START)
        self.ollama_url_entry = Gtk.Entry()
        self.ollama_url_entry.set_text(self.config.get("ollama_url", "http://localhost:11434"))
        b.append(lbl); b.append(self.ollama_url_entry)
        lbl2 = Gtk.Label(label="默认模型:")
        lbl2.set_halign(Gtk.Align.START)
        self.ollama_model_entry = Gtk.Entry()
        self.ollama_model_entry.set_text(self.config.get("ollama_model", "llama3"))
        b.append(lbl2); b.append(self.ollama_model_entry)
        return b

    def _create_aim_page(self):
        b = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        b.set_margin_start(12); b.set_margin_end(12); b.set_margin_top(12); b.set_margin_bottom(12)
        lbl = Gtk.Label(label="默认模型:")
        lbl.set_halign(Gtk.Align.START)
        self.aim_model_entry = Gtk.Entry()
        self.aim_model_entry.set_text(self.config.get("aim_model", "opencode/deepseek-v4-flash-free"))
        b.append(lbl); b.append(self.aim_model_entry)
        return b

    def _create_agent_page(self):
        b = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        b.set_margin_start(12); b.set_margin_end(12); b.set_margin_top(12); b.set_margin_bottom(12)
        lbl = Gtk.Label(label="系统提示（每次对话前发送给 AI）:")
        lbl.set_halign(Gtk.Align.START)
        b.append(lbl)
        sw = Gtk.ScrolledWindow()
        sw.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        sw.set_min_content_height(200)
        sw.set_vexpand(True)
        self.system_prompt_view = Gtk.TextView()
        self.system_prompt_view.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        if self.config.get("system_prompt"):
            self.system_prompt_view.get_buffer().set_text(self.config["system_prompt"])
        sw.set_child(self.system_prompt_view)
        b.append(sw)
        return b

    def get_config(self):
        self.config["ollama_url"] = self.ollama_url_entry.get_text()
        self.config["ollama_model"] = self.ollama_model_entry.get_text()
        self.config["aim_model"] = self.aim_model_entry.get_text()
        buf = self.system_prompt_view.get_buffer()
        self.config["system_prompt"] = buf.get_text(buf.get_start_iter(), buf.get_end_iter(), False)
        return self.config


class MainWindow(Gtk.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title="AI 助手")
        self.config = load_config()
        self.messages = []
        self.backend = None
        self.current_model = ""
        self.is_generating = False
        self._current_generation_buffer = ""
        self.model_changed_handler = None
        self.set_default_size(self.config.get("window_width", 900), self.config.get("window_height", 600))
        self._build_ui()
        self._init_backend()

    def _build_ui(self):
        css = """
            .user-message { background-color: rgba(66,133,244,0.08); border-radius: 6px; padding: 6px; margin-bottom: 4px; }
            .assistant-message { background-color: rgba(76,175,80,0.08); border-radius: 6px; padding: 6px; margin-bottom: 4px; }
            .message-role { font-weight: bold; font-size: 12px; }
            .code-frame { margin: 4px 0; }
            .code-lang { font-size: 11px; color: #888; }
            .status-bar { font-size: 12px; padding: 2px 8px; }
        """
        provider = Gtk.CssProvider()
        provider.load_from_data(css.encode())
        Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.set_child(vbox)

        toolbar = Gtk.HeaderBar()
        toolbar.set_show_title_buttons(True)
        self.set_titlebar(toolbar)

        bc = Gtk.ComboBoxText()
        bc.append("ollama", "Ollama"); bc.append("aim", "AIM")
        bc.set_active_id(self.config.get("backend", "aim"))
        bc.connect("changed", self._on_backend_changed)
        toolbar.pack_start(bc)

        self.model_combo = Gtk.ComboBoxText()
        toolbar.pack_start(self.model_combo)

        nc = Gtk.Button(label="新对话")
        nc.connect("clicked", self._on_new_chat)
        toolbar.pack_start(nc)

        hb = Gtk.Button(label="📜 历史记录")
        hb.connect("clicked", self._on_history_toggle)
        toolbar.pack_start(hb)

        ws = Gtk.Button(label="工作区")
        ws.connect("clicked", self._on_select_workspace)
        toolbar.pack_end(ws)

        st = Gtk.Button(label="设置")
        st.connect("clicked", self._on_settings_clicked)
        toolbar.pack_end(st)

        self.history_expander = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self.history_expander.set_visible(False)
        self.history_expander.set_margin_start(4)
        self.history_expander.set_margin_end(4)
        history_toolbar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        hl = Gtk.Label(label="对话记录")
        hl.set_halign(Gtk.Align.START)
        hl.add_css_class("message-role")
        hl.set_hexpand(True)
        history_toolbar.append(hl)
        clear_btn = Gtk.Button(label="清空历史")
        clear_btn.connect("clicked", self._on_history_clear)
        history_toolbar.append(clear_btn)
        self.history_expander.append(history_toolbar)
        self.history_list = Gtk.ListBox()
        self.history_list.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.history_list.connect("row-activated", self._on_history_activated)
        history_scroll = Gtk.ScrolledWindow()
        history_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        history_scroll.set_min_content_height(80)
        history_scroll.set_max_content_height(200)
        history_scroll.set_child(self.history_list)
        self.history_expander.append(history_scroll)
        vbox.append(self.history_expander)

        self.scrolled_window = Gtk.ScrolledWindow()
        self.scrolled_window.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        self.scrolled_window.set_hexpand(True); self.scrolled_window.set_vexpand(True)
        vbox.append(self.scrolled_window)

        self.chat_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self.chat_box.set_margin_start(8); self.chat_box.set_margin_end(8)
        self.chat_box.set_margin_top(8); self.chat_box.set_margin_bottom(8)
        self.scrolled_window.set_child(self.chat_box)

        input_box = Gtk.Box(spacing=4)
        input_box.set_margin_start(8); input_box.set_margin_end(8); input_box.set_margin_bottom(8)

        ocr_btn = Gtk.Button(label="\U0001f5bc")
        ocr_btn.connect("clicked", self._on_ocr_upload)
        input_box.append(ocr_btn)

        upload_btn = Gtk.Button(label="上传")
        upload_btn.connect("clicked", self._on_upload_clicked)
        input_box.append(upload_btn)

        voice_btn = Gtk.Button(label="\u23f0")
        voice_btn.connect("clicked", self._on_voice_input)
        input_box.append(voice_btn)

        search_btn = Gtk.Button(label="\U0001f50d")
        search_btn.connect("clicked", self._on_web_search)
        input_box.append(search_btn)

        self.entry = Gtk.Entry()
        self.entry.set_hexpand(True)
        self.entry.set_placeholder_text("输入消息...")
        self.entry.connect("activate", self._on_send_message)
        input_box.append(self.entry)

        send_btn = Gtk.Button(label="发送")
        send_btn.add_css_class("suggested-action")
        send_btn.connect("clicked", self._on_send_message)
        input_box.append(send_btn)

        self.stop_btn = Gtk.Button(label="停止")
        self.stop_btn.set_sensitive(False)
        self.stop_btn.connect("clicked", self._on_stop_generation)
        input_box.append(self.stop_btn)

        vbox.append(input_box)

        self.status_bar = Gtk.Statusbar()
        self.status_context = self.status_bar.get_context_id("backend")
        self.status_bar.push(self.status_context, "初始化...")
        vbox.append(self.status_bar)

        self.connect("close-request", self._on_close)

    def _init_backend(self):
        bt = self.config.get("backend", "ollama")
        if bt == "ollama":
            self.backend = OllamaBackend(self.config.get("ollama_url", "http://localhost:11434"))
            self.current_model = self.config.get("ollama_model", "llama3")
        else:
            self.backend = AimBackend(workspace=self.config.get("workspace", ""))
            self.current_model = self.config.get("aim_model", "opencode/deepseek-v4-flash-free")
        self._refresh_models()
        self._update_status()

    def _refresh_models(self):
        self.model_combo.remove_all()
        models = self.backend.get_models()
        if not models:
            models = ["llama3", "mistral", "phi3"] if self.config.get("backend") == "ollama" else ["opencode/deepseek-v4-flash-free", "opencode/hy3-free"]
        for m in models:
            self.model_combo.append_text(m)
        if self.current_model in models:
            self.model_combo.set_active(models.index(self.current_model))
        else:
            self.model_combo.set_active(0)
            self.current_model = models[0]
        if self.model_changed_handler:
            self.model_combo.disconnect(self.model_changed_handler)
        self.model_changed_handler = self.model_combo.connect("changed", self._on_model_changed)

    def _update_status(self):
        ws = self.config.get("workspace", "")
        ws_t = f" [工作区: {os.path.basename(ws)}]" if ws else ""
        self.status_bar.push(self.status_context, f"后端: {self.config.get('backend')} - {self.backend.get_status()}{ws_t}")

    def _on_backend_changed(self, combo):
        bid = combo.get_active_id()
        if bid:
            self.config["backend"] = bid
            save_config(self.config)
            self._init_backend()
            self._new_chat()

    def _on_model_changed(self, combo):
        m = combo.get_active_text()
        if m:
            self.current_model = m
            if self.config.get("backend") == "ollama":
                self.config["ollama_model"] = m
            else:
                self.config["aim_model"] = m
            save_config(self.config)

    def _on_settings_clicked(self, btn):
        dlg = SettingsDialog(self, self.config)
        dlg.connect("response", self._on_settings_response, dlg)
        dlg.present()

    def _on_settings_response(self, _dlg, response, dlg):
        if response == Gtk.ResponseType.APPLY:
            self.config.update(dlg.get_config())
            save_config(self.config)
            self._init_backend()
        dlg.destroy()

    def _on_new_chat(self, btn=None):
        self._new_chat()

    def _new_chat(self):
        self._save_current_to_history()
        self.messages = []
        clear_box(self.chat_box)
        self.backend.reset_conversation()

    def _on_select_workspace(self, btn):
        dialog = Gtk.FileDialog(title="选择工作区目录")
        if self.config.get("workspace"):
            dialog.set_initial_folder(Gio.File.new_for_path(self.config["workspace"]))
        dialog.select_folder(self, self._on_workspace_selected)

    def _on_workspace_selected(self, dialog, result):
        try:
            folder = dialog.select_folder_finish(result)
        except GLib.Error:
            return
        path = folder.get_path() if folder else None
        if path:
            self.config["workspace"] = path
            save_config(self.config)
            self._init_backend()

    # ---- history ------------------------------------------------------
    def _save_current_to_history(self):
        msgs = [m for m in self.messages if m.get("content", "").strip()]
        if not msgs:
            return
        title = ""
        for m in msgs:
            if m.get("role") == "user":
                title = m["content"][:40]
                break
        if not title:
            title = "对话"
        add_history({
            "title": title,
            "time": time.strftime("%Y-%m-%d %H:%M:%S"),
            "messages": msgs,
        })

    def _on_history_toggle(self, _btn):
        vis = not self.history_expander.get_visible()
        self.history_expander.set_visible(vis)
        if vis:
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
        self._save_current_to_history()
        self.messages = []
        clear_box(self.chat_box)
        self.backend.reset_conversation()
        for msg in rec.get("messages", []):
            self.add_message(msg.get("role", "user"), msg.get("content", ""))
        self.status_bar.push(self.status_context, f"已加载: {rec.get('title', '')}")

    def _on_history_clear(self, _btn):
        save_history([])
        self._refresh_history_ui()
        self.status_bar.push(self.status_context, "历史记录已清空")

    def _on_ocr_upload(self, btn):
        dialog = Gtk.FileDialog(title="选择图片进行OCR")
        ff = Gtk.FileFilter()
        ff.set_name("图片"); ff.add_pattern("*.png"); ff.add_pattern("*.jpg"); ff.add_pattern("*.jpeg"); ff.add_pattern("*.bmp")
        store = Gio.ListStore.new(Gtk.FileFilter)
        store.append(ff)
        dialog.set_filters(store)
        dialog.open(self, self._on_ocr_selected)

    def _on_ocr_selected(self, dialog, result):
        try:
            file = dialog.open_finish(result)
        except GLib.Error:
            return
        path = file.get_path() if file else None
        if not path:
            return
        if "\0" in path:
            self.add_message("assistant", "OCR 错误: 文件名包含无效字符")
            return
        threading.Thread(target=self._do_ocr, args=(path,), daemon=True).start()

    def _do_ocr(self, path):
        def ui(msg):
            GLib.idle_add(lambda: self.add_message("user", msg))
        ui(f"\U0001f5bc OCR: {os.path.basename(path)}")
        try:
            has_tesseract = shutil.which("tesseract")
            if not has_tesseract:
                ui("OCR 错误: 未安装 tesseract，请运行 sudo apt install tesseract-ocr")
                return
            result = subprocess.run(["tesseract", path, "stdout"], capture_output=True, text=True, timeout=60)
            if result.returncode == 0 and result.stdout.strip():
                text = result.stdout.strip()
                ui(f"OCR 结果:\n{text[:2000]}")
                GLib.idle_add(lambda: self.entry.set_text(text[:500]))
            else:
                ui(f"OCR 失败: {result.stderr.strip()}")
        except Exception as e:
            ui(f"OCR 错误: {str(e)}")

    def _on_voice_input(self, btn):
        threading.Thread(target=self._record_and_transcribe, daemon=True).start()

    def _record_and_transcribe(self):
        def ui_msg(text):
            GLib.idle_add(lambda: self.add_message("user", text))
        try:
            uidir = tempfile.mkdtemp()
            wav_path = os.path.join(uidir, "input.wav")
            r = subprocess.run(["arecord", "-f", "S16_LE", "-r", "16000", "-c", "1", "-d", "5", wav_path], capture_output=True, text=True, timeout=10)
            if r.returncode != 0:
                ui_msg("语音: 录音失败（未找到 arecord）")
                return
            ui_msg("语音: 已录制 5 秒，正在识别...")
            from faster_whisper import WhisperModel
            model_path = os.path.expanduser("~/.cache/whisper-local/tiny")
            model = WhisperModel(model_path, device="cpu", compute_type="int8")
            segments, _ = model.transcribe(wav_path, language="zh")
            text = "".join(seg.text for seg in segments).strip()
            if text:
                GLib.idle_add(lambda: self.entry.set_text(text))
            else:
                ui_msg("语音: 无法识别")
        except Exception as e:
            GLib.idle_add(lambda e=e: self.add_message("user", f"语音错误: {str(e)}"))

    def _on_web_search(self, btn):
        q = self.entry.get_text().strip()
        if not q:
            self.entry.set_placeholder_text("请先输入搜索关键词")
            return
        threading.Thread(target=self._web_search, args=(q,), daemon=True).start()

    def _web_search(self, query):
        def ui_add(text):
            GLib.idle_add(lambda: self.add_message("user", text))
        ui_add(f"正在搜索: {query}")
        try:
            resp = requests.get("https://api.duckduckgo.com/", params={"q": query, "format": "json", "no_html": 1, "skip_disambig": 1}, timeout=15)
            data = resp.json()
            results = []
            if data.get("AbstractText"):
                results.append(f"摘要: {data['AbstractText']}")
            for topic in data.get("RelatedTopics", []):
                if isinstance(topic, dict) and topic.get("Text"):
                    results.append(topic["Text"])
                if isinstance(topic, dict) and topic.get("Topics"):
                    for sub in topic["Topics"]:
                        if sub.get("Text"):
                            results.append(sub["Text"])
            if results:
                ctx = "\n".join(results[:10])
                self.messages.append({"role": "user", "content": f"搜索结果:\n{ctx}\n\n基于以上内容，{query}"})
                GLib.idle_add(lambda: self.add_message("assistant", f"搜索结果 '{query}':\n{ctx}"))
            else:
                ui_add(f"未找到搜索结果: {query}")
        except Exception as e:
            ui_add(f"搜索错误: {str(e)}")

    def _on_upload_clicked(self, btn):
        dialog = Gtk.FileDialog(title="选择文件")
        ff = Gtk.FileFilter(); ff.set_name("所有文件"); ff.add_pattern("*")
        store = Gio.ListStore.new(Gtk.FileFilter)
        store.append(ff)
        dialog.set_filters(store)
        dialog.open(self, self._on_upload_selected)

    def _on_upload_selected(self, dialog, result):
        try:
            file = dialog.open_finish(result)
        except GLib.Error:
            return
        path = file.get_path() if file else None
        if path:
            self._upload_file(path)

    def _upload_file(self, file_path):
        if not file_path:
            return
        if "\0" in file_path:
            self.add_message("assistant", "上传错误: 文件名包含无效字符")
            return
        self.add_message("user", f"已上传文件: {os.path.basename(file_path)}")
        threading.Thread(target=self._process_upload, args=(file_path,), daemon=True).start()

    def _process_upload(self, file_path):
        result = self.backend.upload_file(file_path)
        GLib.idle_add(lambda: self.add_message("assistant", result))

    def _on_stop_generation(self, btn):
        if not self.is_generating:
            return
        if hasattr(self.backend, "stop"):
            self.backend.stop()
        self._finalize_response(self._current_generation_buffer or "")
        self.status_bar.push(self.status_context, "已停止")

    def _on_send_message(self, widget):
        text = self.entry.get_text().strip()
        if not text or self.is_generating:
            return
        self.entry.set_text("")
        self.add_message("user", text)
        self.is_generating = True
        self.entry.set_sensitive(False)
        self.stop_btn.set_sensitive(True)
        self._current_generation_buffer = ""
        threading.Thread(target=self._generate_response, daemon=True).start()

    def _generate_response(self):
        messages_for_ai = list(self.messages)
        sp = self.config.get("system_prompt", "").strip()
        ws = self.config.get("workspace", "").strip()
        ws_ctx = ""
        if ws and os.path.isdir(ws):
            files = os.listdir(ws)
            ws_ctx = f"\n工作区: {ws}\n文件: {', '.join(files[:30])}"
        system_content = sp + ws_ctx
        if system_content:
            messages_for_ai.insert(0, {"role": "system", "content": system_content})

        response_message = None
        def create_response_message():
            nonlocal response_message
            response_message = ChatMessage("assistant", "", on_retry=self._on_retry, on_delete=self._on_delete_message)
            self._append_message(response_message)
        GLib.idle_add(create_response_message)

        content_buffer = ""
        def callback(content):
            nonlocal content_buffer
            content_buffer += content
            self._current_generation_buffer = content_buffer
            GLib.idle_add(lambda cb=content_buffer, rm=response_message: rm.update_content(cb) if rm else None)
        self.backend.chat(messages_for_ai, self.current_model, callback)
        GLib.idle_add(lambda: self._finalize_response(content_buffer))

    def _finalize_response(self, cb):
        if not self.is_generating:
            return
        self.messages.append({"role": "assistant", "content": cb})
        self._on_response_complete()
    def _on_retry(self, msg_widget):
        if len(self.messages) < 2:
            return
        self.messages.pop()
        for c in box_children(self.chat_box):
            if c == msg_widget:
                self.chat_box.remove(c)
                break
        last_user_msg = None
        for m in reversed(self.messages):
            if m["role"] == "user":
                last_user_msg = m
                break
        if last_user_msg:
            self.is_generating = True
            self.entry.set_sensitive(False)
            self.stop_btn.set_sensitive(True)
            self._current_generation_buffer = ""
            threading.Thread(target=self._generate_response, daemon=True).start()

    def _on_delete_message(self, msg_widget):
        idx = None
        for i, c in enumerate(box_children(self.chat_box)):
            if c == msg_widget:
                idx = i
                break
        if idx is not None:
            self.chat_box.remove(msg_widget)
            if idx < len(self.messages):
                self.messages.pop(idx)

    def add_message(self, role, content):
        msg = ChatMessage(role, content, on_retry=self._on_retry if role == "assistant" else None, on_delete=self._on_delete_message)
        self._append_message(msg)
        self.messages.append({"role": role, "content": content})

    def _append_message(self, message):
        self.chat_box.append(message)
        GLib.idle_add(self._scroll_to_bottom)

    def _scroll_to_bottom(self):
        if self.scrolled_window:
            va = self.scrolled_window.get_vadjustment()
            if va:
                va.set_value(va.get_upper() - va.get_page_size())

    def _on_response_complete(self):
        self.is_generating = False
        self.stop_btn.set_sensitive(False)
        if self.entry:
            self.entry.set_sensitive(True)
            self.entry.grab_focus()
        self._update_status()

    def _on_close(self, widget):
        if self.is_generating and hasattr(self.backend, "stop"):
            self.backend.stop()
        self._save_current_to_history()
        w, h = self.get_size()
        self.config["window_width"] = w
        self.config["window_height"] = h
        save_config(self.config)
        return False
