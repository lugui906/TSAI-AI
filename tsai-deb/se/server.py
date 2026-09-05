"""AI 模型管理器 — chindshell 套壳后端（Flask）。

chindshell 套壳后端。页面：默认模型 / AIM 引擎(仅引擎切换) / 自定义 Provider(唯一 API 页面)。
后端逻辑与原版一致：读写 ~/.config/opencode/opencode.jsonc（jsonc 保格式）、aim oc 命令。
"""
import json
import os
import re
import subprocess
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
for p in (BASE_DIR, "/usr/chindows"):
    if p not in sys.path:
        sys.path.insert(0, p)

from flask import Flask, jsonify, render_template, request  # noqa: E402

from chindshell import flask as csf  # noqa: E402
import jsonc  # noqa: E402

app = Flask(__name__)
csf.register(app)

CONFIG_PATH = os.path.expanduser("~/.config/opencode/opencode.jsonc")
DEFAULT_NPM = "@ai-sdk/openai-compatible"


def _ensure_config():
    os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
    if not os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            f.write('{\n  "$schema": "https://opencode.ai/config.json"\n}\n')


def _read_cfg():
    _ensure_config()
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        text = f.read()
    try:
        _, v = jsonc.parse(text)
    except jsonc.JsoncError:
        v = {}
    return (v or {}) if isinstance(v, dict) else {}


def _read_text():
    _ensure_config()
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return f.read()


def _write_text(text):
    _ensure_config()
    tmp = CONFIG_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp, CONFIG_PATH)


def _is_vision_model(model):
    if not isinstance(model, dict):
        return False
    if model.get("attachment"):
        return True
    mod = model.get("modalities")
    if isinstance(mod, dict) and isinstance(mod.get("input"), list):
        return "image" in mod["input"]
    return False


def _aim_oc_status():
    try:
        out = subprocess.run(["aim", "oc", "status"],
                             capture_output=True, text=True, timeout=10)
        return out.stdout.strip() or "opencode"
    except Exception:
        return "opencode"


def _aim_oc_switch(target):
    arg = "default" if target == "opencode" else "openclaw"
    try:
        out = subprocess.run(["aim", "oc", arg],
                             capture_output=True, text=True, timeout=15)
        if out.returncode != 0:
            return False, out.stderr.strip() or "aim oc 返回失败"
        return True, out.stdout.strip() or ("已切换到 " + target)
    except Exception as e:
        return False, str(e)


def _aim_list_apikeys():
    try:
        out = subprocess.run(["aim", "apikey", "list"],
                             capture_output=True, text=True, timeout=10)
        pairs = []
        for line in out.stdout.splitlines()[1:]:
            if ":" in line:
                prov, key = line.split(":", 1)
                pairs.append({"provider": prov.strip(), "key": key.strip()})
        return pairs
    except Exception:
        return []


def _aim_set_apikey(provider, key):
    try:
        out = subprocess.run(["aim", "apikey", "set", provider, key],
                             capture_output=True, text=True, timeout=15)
        return (True, out.stdout.strip()) if out.returncode == 0 else (False, out.stderr.strip() or "设置失败")
    except Exception as e:
        return False, str(e)


def _aim_remove_apikey(provider):
    try:
        out = subprocess.run(["aim", "apikey", "remove", provider],
                             capture_output=True, text=True, timeout=15)
        return (True, out.stdout.strip()) if out.returncode == 0 else (False, out.stderr.strip() or "删除失败")
    except Exception as e:
        return False, str(e)


def _list_models():
    try:
        out = subprocess.run(["opencode", "models"],
                             capture_output=True, text=True, timeout=30)
        return [l.strip() for l in out.stdout.splitlines() if l.strip()]
    except Exception:
        return []



    """在用户终端里运行命令（configure 交互用）。"""
    cmdline = " ".join(f"'{a}'" if " " in a else a for a in argv)
    for term in ("ptyxis", "x-terminal-emulator", "gnome-terminal", "kgx"):
        path = subprocess.run(["which", term], capture_output=True,
                              text=True).stdout.strip()
        if not path:
            continue
        suffix = "%s; echo -e '\\n[按回车关闭...]'; read" % cmdline
        if term in ("ptyxis", "gnome-terminal"):
            cmd = [path, "--", "bash", "-c", suffix]
        else:
            cmd = [path, "-e", "bash", "-c", suffix]
        try:
            subprocess.Popen(cmd)
            return True, "已启动终端: " + argv[0]
        except Exception as e:
            return False, str(e)
    return False, "未找到可用终端程序"


@app.route("/")
def index():
    return render_template("index.html")


# ---- 配置原始文本 ----
@app.route("/api/config")
def api_config():
    return jsonify({"text": _read_text()})


@app.route("/api/config", methods=["POST"])
def api_config_save():
    data = request.get_json(silent=True) or {}
    text = data.get("text")
    if text is not None:
        _write_text(text)
    return jsonify({"ok": True})


# ---- 可用模型 + 默认模型 ----
@app.route("/api/models")
def api_models():
    return jsonify({"models": _list_models()})


@app.route("/api/defaults")
def api_defaults():
    cfg = _read_cfg()
    return jsonify({"model": cfg.get("model", ""),
                    "small_model": cfg.get("small_model", "")})


@app.route("/api/model/default", methods=["POST"])
def api_model_default():
    data = request.get_json(silent=True) or {}
    text = _read_text()
    if data.get("model"):
        text = jsonc.set_value(text, ["model"], data["model"])
    if data.get("small_model"):
        text = jsonc.set_value(text, ["small_model"], data["small_model"])
    _write_text(text)
    return jsonify({"ok": True})


# ---- AIM 引擎 ----
@app.route("/api/engine")
def api_engine():
    return jsonify({"engine": _aim_oc_status()})


@app.route("/api/engine", methods=["POST"])
def api_engine_switch():
    data = request.get_json(silent=True) or {}
    target = (data.get("target") or "").lower()
    ok, msg = _aim_oc_switch(target)
    return jsonify({"ok": ok, "engine": _aim_oc_status(), "msg": msg})


@app.route("/api/apikeys")
def api_apikeys():
    return jsonify({"apikeys": _aim_list_apikeys()})


@app.route("/api/apikey", methods=["POST"])
def api_apikey_set():
    data = request.get_json(silent=True) or {}
    provider = (data.get("provider") or "").strip()
    key = (data.get("key") or "").strip()
    if not provider or not key:
        return jsonify({"ok": False, "error": "provider/key 必填"}), 400
    ok, msg = _aim_set_apikey(provider, key)
    return jsonify({"ok": ok, "msg": msg})


@app.route("/api/apikey", methods=["DELETE"])
def api_apikey_remove():
    data = request.get_json(silent=True) or {}
    provider = (data.get("provider") or "").strip()
    if not provider:
        return jsonify({"ok": False, "error": "provider 必填"}), 400
    ok, msg = _aim_remove_apikey(provider)
    return jsonify({"ok": ok, "msg": msg})


@app.route("/api/apikey", methods=["PUT"])
def api_apikey_update():
    # alias for set (前端可复用)
    return api_apikey_set()


# ---- 自定义 Provider ----
@app.route("/api/providers")
def api_providers():
    cfg = _read_cfg()
    provs = cfg.get("provider", {})
    rows = []
    for pid, prov in provs.items():
        if not isinstance(prov, dict):
            continue
        options = prov.get("options") or {}
        opts = options if isinstance(options, dict) else {}
        models = prov.get("models")
        model_list = []
        if isinstance(models, dict):
            model_list = [mid + ("|vision" if _is_vision_model(m) else "")
                          for mid, m in models.items()]
        rows.append({
            "id": pid,
            "name": prov.get("name", ""),
            "npm": prov.get("npm", DEFAULT_NPM),
            "baseURL": opts.get("baseURL", ""),
            "hasKey": bool(opts.get("apiKey")),
            "models": model_list,
        })
    return jsonify({"providers": rows})


@app.route("/api/provider", methods=["POST"])
def api_provider_save():
    data = request.get_json(silent=True) or {}
    pid = (data.get("id") or "").strip()
    if not pid:
        return jsonify({"ok": False, "error": "Provider ID 不能为空"}), 400
    provider = {"npm": (data.get("npm") or DEFAULT_NPM)}
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
    for entry in (data.get("models") or []):
        mid = entry
        vision = False
        if "|" in entry:
            mid, flag = entry.split("|", 1)
            mid = mid.strip()
            vision = flag.strip().lower() in ("vision", "v", "image", "img", "mm", "multimodal")
        if not mid:
            continue
        if vision:
            models[mid] = {"name": mid, "attachment": True,
                           "modalities": {"input": ["text", "image"], "output": ["text"]}}
        else:
            models[mid] = {"name": mid}
    if models:
        provider["models"] = models
    try:
        text = jsonc.set_value(_read_text(), ["provider", pid], provider)
    except jsonc.JsoncError as e:
        return jsonify({"ok": False, "error": f"保存失败: {e}"}), 400
    _write_text(text)
    return jsonify({"ok": True})


@app.route("/api/provider", methods=["DELETE"])
def api_provider_delete():
    data = request.get_json(silent=True) or {}
    pid = (data.get("id") or "").strip()
    if not pid:
        return jsonify({"ok": False, "error": "Provider ID 必填"}), 400
    text = _read_text()
    try:
        text = jsonc.delete_key(text, ["provider", pid])
    except jsonc.JsoncError as e:
        return jsonify({"ok": False, "error": f"删除失败: {e}"}), 400
    if "provider" in _read_cfg() and not _read_cfg().get("provider"):
        try:
            text = jsonc.delete_key(text, ["provider"])
        except jsonc.JsoncError:
            pass
    _write_text(text)
    return jsonify({"ok": True})


# ---- 交互式 configure（打开终端） ----
@app.route("/api/configure", methods=["POST"])
def api_configure():
    data = request.get_json(silent=True) or {}
    which = data.get("which")
    if which == "aim":
        ok, msg = _run_terminal(["aim", "model", "switch"])
    elif which == "openclaw":
        ok, msg = _run_terminal(["openclaw", "configure", "--section", "model"])
    else:
        return jsonify({"ok": False, "error": "未知配置目标"}), 400
    return jsonify({"ok": ok, "msg": msg})
