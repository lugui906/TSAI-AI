import os
import threading
import json
import requests
import subprocess
import tempfile
import re
import shutil
from faster_whisper import WhisperModel
import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, GLib, Pango, Gdk

CONFIG_DIR = os.path.expanduser("~/.ai-assistant")
CONFIG_FILE = os.path.join(CONFIG_DIR, "config.json")
HISTORY_DIR = os.path.join(CONFIG_DIR, "history")

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
        self.workspace = workspace if workspace and os.path.isdir(workspace) else None
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
            self._conversation_started = True
            full_response = ""
            for line in proc.stdout:
                full_response += line
                if callback:
                    callback(line)
            proc.wait(timeout=300)
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
            frame.set_shadow_type(Gtk.ShadowType.ETCHED_IN)
            style = frame.get_style_context()
            style.add_class("code-frame")

            vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)

            header = Gtk.Box(spacing=4)
            lang_label = Gtk.Label(label=lang if lang else "code", xalign=0)
            lang_label.get_style_context().add_class("code-lang")
            lang_label.set_margin_start(4)
            header.pack_start(lang_label, True, True, 0)

            copy_btn = Gtk.Button(label="复制")
            copy_btn.set_size_request(50, 24)
            copy_btn.connect("clicked", lambda b, t=code_text: _copy_text(t))
            header.pack_end(copy_btn, False, False, 0)

            if on_run_code:
                run_btn = Gtk.Button(label="运行")
                run_btn.set_size_request(50, 24)
                run_btn.connect("clicked", lambda b, t=code_text, l=lang: on_run_code(t, l))
                header.pack_end(run_btn, False, False, 0)

            vbox.pack_start(header, False, False, 0)

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
            vbox.pack_start(tv, False, False, 0)

            frame.add(vbox)
            box.pack_start(frame, False, False, 0)
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
                        lbl = Gtk.Label(label=escape_pango(cell), xalign=0)
                        lbl.set_use_markup(True)
                        if ri == 0 or (ri == 1 and len(rows) > 2 and all(re.match(r"^[-:]+$", c) for c in rows[1] if c)):
                            lbl.set_markup(f"<b>{escape_pango(cell)}</b>")
                        grid.attach(lbl, ci, ri, 1, 1)
                frame = Gtk.Frame()
                frame.set_shadow_type(Gtk.ShadowType.ETCHED_IN)
                frame.add(grid)
                box.pack_start(frame, False, False, 0)
            continue

        if line.strip():
            formatted = _format_inline(line)
            lbl = Gtk.Label(xalign=0, yalign=0)
            lbl.set_markup(formatted)
            lbl.set_line_wrap(True)
            lbl.set_line_wrap_mode(Pango.WrapMode.WORD_CHAR)
            lbl.set_margin_bottom(2)
            box.pack_start(lbl, False, False, 0)
        else:
            box.pack_start(Gtk.Label(label=""), False, False, 0)

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


def _copy_text(text):
    clip = Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD)
    clip.set_text(text, -1)


class ChatMessage(Gtk.Box):
    def __init__(self, role, content, on_retry=None, on_delete=None):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self.role = role
        self.on_retry = on_retry
        self.on_delete = on_delete

        header = Gtk.Box(spacing=4)
        role_label = Gtk.Label(label="你" if role == "user" else "AI", xalign=0)
        role_label.get_style_context().add_class("message-role")
        header.pack_start(role_label, True, True, 0)

        copy_btn = Gtk.Button(label="复制")
        copy_btn.set_size_request(40, 20)
        copy_btn.connect("clicked", lambda b: _copy_text(content))
        header.pack_end(copy_btn, False, False, 0)

        if on_delete:
            del_btn = Gtk.Button(label="删除")
            del_btn.set_size_request(40, 20)
            del_btn.connect("clicked", lambda b: on_delete(self))
            header.pack_end(del_btn, False, False, 0)

        if on_retry and role == "assistant":
            retry_btn = Gtk.Button(label="重试")
            retry_btn.set_size_request(40, 20)
            retry_btn.connect("clicked", lambda b: on_retry(self))
            header.pack_end(retry_btn, False, False, 0)

        self.pack_start(header, False, False, 0)

        scrolled = Gtk.ScrolledWindow()
        scrolled.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.NEVER)
        scrolled.set_propagate_natural_height(True)
        self.content_widget = render_markdown(content, on_run_code=self._run_code)
        scrolled.add(self.content_widget)
        self.pack_start(scrolled, True, True, 0)

        if role == "user":
            self.get_style_context().add_class("user-message")
        else:
            self.get_style_context().add_class("assistant-message")

    def _run_code(self, code, lang):
        threading.Thread(target=self._execute_code, args=(code, lang), daemon=True).start()

    def _execute_code(self, code, lang):
        try:
            output_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
            output_box.set_margin_start(8)
            output_label = Gtk.Label(label="\u23f3 运行中...", xalign=0)
            output_label.set_markup("<i>运行中...</i>")
            output_box.pack_start(output_label, False, False, 0)
            GLib.idle_add(lambda: self.pack_start(output_box, False, False, 0) or output_box.show_all())

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
            GLib.idle_add(lambda e=e: output_label.set_markup(f"<b>错误:</b> {escape_pango(str(e))}"))

    def update_content(self, content):
        old = self.content_widget
        scrolled = old.get_parent()
        scrolled.remove(old)
        self.content_widget = render_markdown(content, on_run_code=self._run_code)
        scrolled.add(self.content_widget)
        self.content_widget.show_all()


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
        nb.append_page(self._create_ollama_page(), Gtk.Label(label="Ollama"))
        nb.append_page(self._create_aim_page(), Gtk.Label(label="AIM"))
        nb.append_page(self._create_agent_page(), Gtk.Label(label="智能体"))
        ca.pack_start(nb, True, True, 0)
        self.add_button("取消", Gtk.ResponseType.CANCEL)
        self.add_button("应用", Gtk.ResponseType.APPLY)

    def _create_ollama_page(self):
        b = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        b.set_margin_start(12); b.set_margin_end(12); b.set_margin_top(12); b.set_margin_bottom(12)
        lbl = Gtk.Label(label="Ollama 地址:", xalign=0)
        self.ollama_url_entry = Gtk.Entry()
        self.ollama_url_entry.set_text(self.config.get("ollama_url", "http://localhost:11434"))
        b.pack_start(lbl, False, False, 0); b.pack_start(self.ollama_url_entry, False, False, 0)
        lbl2 = Gtk.Label(label="默认模型:", xalign=0)
        self.ollama_model_entry = Gtk.Entry()
        self.ollama_model_entry.set_text(self.config.get("ollama_model", "llama3"))
        b.pack_start(lbl2, False, False, 0); b.pack_start(self.ollama_model_entry, False, False, 0)
        return b

    def _create_aim_page(self):
        b = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        b.set_margin_start(12); b.set_margin_end(12); b.set_margin_top(12); b.set_margin_bottom(12)
        lbl = Gtk.Label(label="默认模型:", xalign=0)
        self.aim_model_entry = Gtk.Entry()
        self.aim_model_entry.set_text(self.config.get("aim_model", "opencode/deepseek-v4-flash-free"))
        b.pack_start(lbl, False, False, 0); b.pack_start(self.aim_model_entry, False, False, 0)
        return b

    def _create_agent_page(self):
        b = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        b.set_margin_start(12); b.set_margin_end(12); b.set_margin_top(12); b.set_margin_bottom(12)
        lbl = Gtk.Label(label="系统提示（每次对话前发送给 AI）:", xalign=0)
        b.pack_start(lbl, False, False, 0)
        sw = Gtk.ScrolledWindow()
        sw.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        sw.set_min_content_height(200)
        self.system_prompt_view = Gtk.TextView()
        self.system_prompt_view.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        if self.config.get("system_prompt"):
            self.system_prompt_view.get_buffer().set_text(self.config["system_prompt"])
        sw.add(self.system_prompt_view)
        b.pack_start(sw, True, True, 0)
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
        Gtk.StyleContext.add_provider_for_screen(self.get_screen(), provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.add(vbox)

        toolbar = Gtk.Box(spacing=4)
        toolbar.set_margin_start(4); toolbar.set_margin_end(4); toolbar.set_margin_top(4)

        bc = Gtk.ComboBoxText()
        bc.append("ollama", "Ollama"); bc.append("aim", "AIM")
        bc.set_active_id(self.config.get("backend", "aim"))
        bc.connect("changed", self._on_backend_changed)
        toolbar.pack_start(bc, False, False, 0)

        self.model_combo = Gtk.ComboBoxText()
        toolbar.pack_start(self.model_combo, False, False, 0)

        nc = Gtk.Button(label="新对话")
        nc.connect("clicked", self._on_new_chat)
        toolbar.pack_start(nc, False, False, 0)

        sv = Gtk.Button(label="保存")
        sv.connect("clicked", self._on_save_conversation)
        toolbar.pack_start(sv, False, False, 0)

        ld = Gtk.Button(label="加载")
        ld.connect("clicked", self._on_load_conversation)
        toolbar.pack_start(ld, False, False, 0)

        ws = Gtk.Button(label="工作区")
        ws.connect("clicked", self._on_select_workspace)
        toolbar.pack_end(ws, False, False, 0)

        st = Gtk.Button(label="设置")
        st.connect("clicked", self._on_settings_clicked)
        toolbar.pack_end(st, False, False, 0)

        vbox.pack_start(toolbar, False, False, 0)

        self.scrolled_window = Gtk.ScrolledWindow()
        self.scrolled_window.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        self.scrolled_window.set_hexpand(True); self.scrolled_window.set_vexpand(True)
        vbox.pack_start(self.scrolled_window, True, True, 0)

        self.chat_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self.chat_box.set_margin_start(8); self.chat_box.set_margin_end(8)
        self.chat_box.set_margin_top(8); self.chat_box.set_margin_bottom(8)
        self.scrolled_window.add(self.chat_box)

        input_box = Gtk.Box(spacing=4)
        input_box.set_margin_start(8); input_box.set_margin_end(8); input_box.set_margin_bottom(8)

        ocr_btn = Gtk.Button(label="\U0001f5bc")
        ocr_btn.connect("clicked", self._on_ocr_upload)
        input_box.pack_start(ocr_btn, False, False, 0)

        upload_btn = Gtk.Button(label="上传")
        upload_btn.connect("clicked", self._on_upload_clicked)
        input_box.pack_start(upload_btn, False, False, 0)

        voice_btn = Gtk.Button(label="\u23f0")
        voice_btn.connect("clicked", self._on_voice_input)
        input_box.pack_start(voice_btn, False, False, 0)

        search_btn = Gtk.Button(label="\U0001f50d")
        search_btn.connect("clicked", self._on_web_search)
        input_box.pack_start(search_btn, False, False, 0)

        self.entry = Gtk.Entry()
        self.entry.set_hexpand(True)
        self.entry.set_placeholder_text("输入消息...")
        self.entry.connect("activate", self._on_send_message)
        input_box.pack_start(self.entry, True, True, 0)

        send_btn = Gtk.Button(label="发送")
        send_btn.connect("clicked", self._on_send_message)
        input_box.pack_start(send_btn, False, False, 0)

        vbox.pack_start(input_box, False, False, 0)

        self.status_bar = Gtk.Statusbar()
        self.status_context = self.status_bar.get_context_id("backend")
        self.status_bar.push(self.status_context, "初始化...")
        vbox.pack_start(self.status_bar, False, False, 0)

        self.connect("delete-event", self._on_close)

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
        if dlg.run() == Gtk.ResponseType.APPLY:
            self.config.update(dlg.get_config())
            save_config(self.config)
            self._init_backend()
        dlg.destroy()

    def _on_new_chat(self, btn=None):
        self._new_chat()

    def _new_chat(self):
        self.messages = []
        for c in self.chat_box.get_children():
            self.chat_box.remove(c)
        self.backend.reset_conversation()

    def _on_select_workspace(self, btn):
        dlg = Gtk.FileChooserDialog(title="选择工作区目录", parent=self, action=Gtk.FileChooserAction.SELECT_FOLDER,
            buttons=(Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL, Gtk.STOCK_OPEN, Gtk.ResponseType.OK))
        if self.config.get("workspace"):
            dlg.set_filename(self.config["workspace"])
        if dlg.run() == Gtk.ResponseType.OK:
            self.config["workspace"] = dlg.get_filename()
            save_config(self.config)
            self._init_backend()
        dlg.destroy()

    def _on_save_conversation(self, btn):
        os.makedirs(HISTORY_DIR, exist_ok=True)
        ts = subprocess.run(["date", "+%Y%m%d_%H%M%S"], capture_output=True, text=True).stdout.strip()
        path = os.path.join(HISTORY_DIR, f"chat_{ts}.json")
        data = {"messages": self.messages, "config": self.config.copy()}
        with open(path, "w") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        self.status_bar.push(self.status_context, f"已保存: {os.path.basename(path)}")

    def _on_load_conversation(self, btn):
        dlg = Gtk.FileChooserDialog(title="加载对话记录", parent=self, action=Gtk.FileChooserAction.OPEN,
            buttons=(Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL, Gtk.STOCK_OPEN, Gtk.ResponseType.OK))
        if os.path.isdir(HISTORY_DIR):
            dlg.set_current_folder(HISTORY_DIR)
        ff = Gtk.FileFilter()
        ff.set_name("JSON"); ff.add_pattern("*.json")
        dlg.add_filter(ff)
        if dlg.run() == Gtk.ResponseType.OK:
            try:
                with open(dlg.get_filename(), "r") as f:
                    data = json.load(f)
                self._new_chat()
                for msg in data.get("messages", []):
                    self.add_message(msg["role"], msg["content"])
            except Exception as e:
                self.status_bar.push(self.status_context, f"加载失败: {str(e)}")
        dlg.destroy()

    def _on_ocr_upload(self, btn):
        dlg = Gtk.FileChooserDialog(title="选择图片进行OCR", parent=self, action=Gtk.FileChooserAction.OPEN,
            buttons=(Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL, Gtk.STOCK_OPEN, Gtk.ResponseType.OK))
        ff = Gtk.FileFilter()
        ff.set_name("图片"); ff.add_pattern("*.png"); ff.add_pattern("*.jpg"); ff.add_pattern("*.jpeg"); ff.add_pattern("*.bmp")
        dlg.add_filter(ff)
        if dlg.run() == Gtk.ResponseType.OK:
            path = dlg.get_filename()
            dlg.destroy()
            threading.Thread(target=self._do_ocr, args=(path,), daemon=True).start()
        else:
            dlg.destroy()

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
            _candidates = [
                os.environ.get("AIM_MODEL_ROOT"),
                os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                             "..", "ai-voice", "share", "models", "faster-small"),
                "/usr/share/chinai2/models/tiny",
            ]
            model_path = next((p for p in _candidates if p and os.path.isdir(p)), "/usr/share/chinai2/models/tiny")
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
        dlg = Gtk.FileChooserDialog(title="选择文件", parent=self, action=Gtk.FileChooserAction.OPEN,
            buttons=(Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL, Gtk.STOCK_OPEN, Gtk.ResponseType.OK))
        ff = Gtk.FileFilter(); ff.set_name("所有文件"); ff.add_pattern("*")
        dlg.add_filter(ff)
        if dlg.run() == Gtk.ResponseType.OK:
            path = dlg.get_filename()
            dlg.destroy()
            self._upload_file(path)
        else:
            dlg.destroy()

    def _upload_file(self, file_path):
        if not file_path:
            return
        self.add_message("user", f"已上传文件: {os.path.basename(file_path)}")
        threading.Thread(target=self._process_upload, args=(file_path,), daemon=True).start()

    def _process_upload(self, file_path):
        result = self.backend.upload_file(file_path)
        GLib.idle_add(lambda: self.add_message("assistant", result))

    def _on_send_message(self, widget):
        text = self.entry.get_text().strip()
        if not text or self.is_generating:
            return
        self.entry.set_text("")
        self.add_message("user", text)
        self.is_generating = True
        self.entry.set_sensitive(False)
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
            GLib.idle_add(lambda cb=content_buffer, rm=response_message: rm.update_content(cb) if rm else None)
        self.backend.chat(messages_for_ai, self.current_model, callback)
        GLib.idle_add(lambda: self._finalize_response(content_buffer))

    def _finalize_response(self, cb):
        self.messages.append({"role": "assistant", "content": cb})
        self._on_response_complete()

    def _on_retry(self, msg_widget):
        if len(self.messages) < 2:
            return
        self.messages.pop()
        for c in self.chat_box.get_children():
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
            threading.Thread(target=self._generate_response, daemon=True).start()

    def _on_delete_message(self, msg_widget):
        idx = None
        for i, c in enumerate(self.chat_box.get_children()):
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
        self.chat_box.pack_start(message, False, False, 0)
        message.show_all()
        GLib.idle_add(self._scroll_to_bottom)

    def _scroll_to_bottom(self):
        if self.scrolled_window:
            va = self.scrolled_window.get_vadjustment()
            if va:
                va.set_value(va.get_upper() - va.get_page_size())

    def _on_response_complete(self):
        self.is_generating = False
        if self.entry:
            self.entry.set_sensitive(True)
            self.entry.grab_focus()
        self._update_status()

    def _on_close(self, widget, event):
        w, h = self.get_size()
        self.config["window_width"] = w
        self.config["window_height"] = h
        save_config(self.config)
        return False
