import glob
import json
import os
import re
import shlex
import subprocess
import sys
import threading
import time

from flask import Flask, Response, jsonify, render_template, request
import sys
for _p in [os.path.expanduser("~/.local/tsai-activity"),
           "/usr/chindows/tsai-activity",
           "/usr/chindows/tsai-activity",
           os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tsai-activity")]:
    if _p not in sys.path:
        sys.path.insert(0, _p)
import context as tsai_ctx
import ai_gate as ai_g

_MEMORY_SCHED_LOCK = threading.Lock()
_MEMORY_SCHED_NEXT = 0.0

from backends import AimBackend, AutoBackend, KeyBackend, OllamaBackend, ScheduleBackend, ScrBackend
import backends

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.expanduser("~/.chinai3")
CONFIG_FILE = os.path.join(DATA_DIR, "config.json")
HISTORY_FILE = os.path.join(DATA_DIR, "history.json")
AIM_STATE_FILE = os.path.expanduser("~/.local/share/aim/state.json")
CONVERSATIONS_FILE = os.path.expanduser("~/.local/share/aim/conversations.jsonl")
MAX_HISTORY = 200

DEFAULT_CONFIG = {
    "backend": "aim",
    "engine": "chat",
    "ollama_url": "http://localhost:11434",
    "ollama_model": "qwen3:0.6b",
    "aim_model": "opencode/hy3-free",
    "workspace": "",
    "sidebar_open": True,
    "ai_apps_collapsed": False,
    "ctx_share": False,
    "ctx_minutes": 10,          # 发送时附加上下文默认最近 10 分钟日志（用户可调）
    "memory_interval": "off",   # 记忆自动循环更新: off/daily/weekly/monthly/quarterly
    "memory_last": "",          # 上次记忆更新的时间戳
}

# AI 应用列表：type=engine 深度集成到聊天（key/scr），type=launch 直接打开应用
AI_APPS = {
    "key": {
        "name": "AI助手",
        "icon": "💬",
        "type": "engine",
        "cmd": [sys.executable, "/usr/chindows/key/main.py"],
        "desc": "通用对话助手",
    },
    "scr": {
        "name": "桌面控制",
        "icon": "🖥️",
        "type": "engine",
        "cmd": [sys.executable, "/usr/chindows/scr/main.py"],
        "desc": "AI 操控桌面",
    },
    "auto": {
        "name": "自动化",
        "icon": "🤖",
        "type": "engine",
        "cmd": [],
        "desc": "AI 自动化：对话生成脚本/规则并执行",
    },
    "schedule": {
        "name": "日程",
        "icon": "🗓️",
        "type": "engine",
        "cmd": [],
        "desc": "AI 日程：AI 澄清并安排当天任务，条件触发时执行",
    },
    "clockai": {
        "name": "AI定时器",
        "icon": "⏰",
        "type": "launch",
        "cmd": ["clockai", "gui"],
        "desc": "定时任务调度",
    },
    "bai": {
        "name": "智能体",
        "icon": "🤖",
        "type": "launch",
        "cmd": [sys.executable, "/usr/chindows/bai/ai-gui.py"],
        "desc": "AI Chat 应用",
    },
    "aai": {
        "name": "语音助手",
        "icon": "🎤",
        "type": "launch",
        "cmd": [sys.executable, "/usr/chindows/aai/main.py"],
        "desc": "语音对话",
    },
    "aioffice": {
        "name": "AI办公",
        "icon": "💼",
        "type": "launch",
        "cmd": ["/opt/aps/bin/lo-aps"],
        "desc": "LibreOffice AI 伴侣",
    },
}

ENGINE_ALIAS = {
    "key": "AI助手",
    "scr": "桌面控制",
    "auto": "自动化",
    "schedule": "日程",
}

app = Flask(__name__)


@app.after_request
def _no_cache(resp):
    """所有 API 响应禁用缓存：面板/上下文必须实时，WebKit 会对无头 GET 启发式缓存。"""
    if resp.mimetype == "application/json" or (request.path or "").startswith("/api/"):
        resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        resp.headers["Pragma"] = "no-cache"
    return resp

_lock = threading.Lock()
_active_backend = None
_ctx_tine = {"text": "", "ts": 0}   # 界面上下文(tine tree)缓存，随下条消息前置
_engines = {}  # engine -> 持久化的后端实例（会话状态保留）


def get_engine_backend(engine, cfg):
    """返回按 engine 持久化的后端实例。chat 也持久化，保证 newrun 后走 run。"""
    global _engines
    with _lock:
        if engine not in _engines:
            if engine == "scr":
                _engines[engine] = ScrBackend(workspace=cfg.get("workspace", ""))
            elif engine == "auto":
                _engines[engine] = AutoBackend(workspace=cfg.get("workspace", ""))
            elif engine == "schedule":
                _engines[engine] = ScheduleBackend(workspace=cfg.get("workspace", ""))
            elif engine == "key":
                _engines[engine] = KeyBackend(workspace=cfg.get("workspace", ""))
            elif engine == "chat":
                _engines[engine] = AimBackend(workspace=cfg.get("workspace", ""))
            else:
                _engines[engine] = None
        return _engines[engine]


def load_config():
    cfg = DEFAULT_CONFIG.copy()
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            for k, v in data.items():
                if k in cfg:
                    cfg[k] = v
    except Exception:
        pass
    return cfg


def save_config(cfg):
    os.makedirs(DATA_DIR, exist_ok=True)
    tmp = CONFIG_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
    os.replace(tmp, CONFIG_FILE)


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
    os.makedirs(DATA_DIR, exist_ok=True)
    tmp = HISTORY_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, indent=2)
    os.replace(tmp, HISTORY_FILE)


def _current_aim_session():
    """读取 aim 当前会话（state.json 里的 session 即 aim run 将继续的会话）。"""
    try:
        with open(AIM_STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f).get("session") or None
    except Exception:
        return None


def _session_to_rank(session):
    """把 aim session id 映射为 `aim se` 里的编号（aim change 用）。

    规则：conversations.jsonl 里该 session 最新条目的 id 相对最大 id 的排名。
    """
    try:
        with open(CONVERSATIONS_FILE, "r", encoding="utf-8") as f:
            entries = [json.loads(l) for l in f if l.strip()]
    except Exception:
        return None
    if not entries:
        return None
    ids = sorted(e.get("id", 0) for e in entries if e.get("session") == session)
    if not ids:
        return None
    latest = ids[-1]
    return sum(1 for e in entries if e.get("id", 0) > latest) + 1


def make_backend(cfg, engine="chat"):
    if engine in ("key", "scr", "auto", "schedule", "chat") and cfg.get("backend") != "ollama":
        backend = get_engine_backend(engine, cfg)
    elif cfg.get("backend") == "ollama":
        backend = OllamaBackend(cfg.get("ollama_url", "http://localhost:11434"))
    else:
        backend = AimBackend(workspace=cfg.get("workspace", ""))
    return backend


def get_active_backend():
    global _active_backend
    with _lock:
        return _active_backend


@app.route("/api/context", methods=["GET"])
def api_context():
    """实时活动上下文（只读，无 AI）。"""
    kind = request.args.get("kind", "markdown")
    if kind == "events":
        return jsonify({"events": tsai_ctx.recent_events(25)})
    try:
        minutes = int(request.args.get("minutes", ""))
    except Exception:
        minutes = int(load_config().get("ctx_minutes", 10) or 10)
    return jsonify({"context": tsai_ctx.context_markdown(),
                    "brief": tsai_ctx.brief_context(minutes=minutes),
                    "minutes": minutes})


@app.route("/api/activity", methods=["GET"])
def api_activity():
    """AI 窗口记录控制面板数据：记录器状态 + 最近窗口 + 最近文件 + 配置。"""
    return jsonify({
        "status": tsai_ctx.recorder_status(),
        "windows": tsai_ctx.recent_windows(12),
        "files": tsai_ctx.recent_files(12),
        "ctx_share": bool(load_config().get("ctx_share", False)),
    })


@app.route("/api/ctx_share", methods=["POST"])
def api_ctx_share():
    """开关"发送时拼接活动上下文"。"""
    data = request.get_json(silent=True) or {}
    cfg = load_config()
    on = bool(data.get("on", False))
    cfg["ctx_share"] = on
    save_config(cfg)
    return jsonify({"ok": True, "ctx_share": on})


# ======================= AI 自动化（~/.auto 规则/脚本） =======================
def _load_auto_rules():
    try:
        with open(backends.AUTO_RULES, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


def _save_auto_rules(rules):
    try:
        import os as _os
        _os.makedirs(backends.AUTO_DIR, exist_ok=True)
        tmp = backends.AUTO_RULES + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(rules, f, ensure_ascii=False, indent=2)
        _os.replace(tmp, backends.AUTO_RULES)
    except Exception:
        pass


@app.route("/api/auto/rules", methods=["GET"])
def api_auto_rules():
    """列出所有自动化规则 + 脚本 + 最近日志（供面板）。"""
    from backends import AUTO_SCRIPTS, AUTO_RULES, AUTO_LOGS
    rules = _load_auto_rules()
    scripts = []
    try:
        for fn in sorted(os.listdir(AUTO_SCRIPTS)):
            if fn.endswith(".py"):
                p = os.path.join(AUTO_SCRIPTS, fn)
                scripts.append({"name": fn, "path": p,
                                "mtime": time.strftime("%m-%d %H:%M", time.localtime(os.path.getmtime(p)))})
    except Exception:
        pass
    logs = []
    try:
        for fn in sorted(os.listdir(AUTO_LOGS))[-5:]:
            p = os.path.join(AUTO_LOGS, fn)
            logs.append({"name": fn, "path": p,
                         "tail": open(p, encoding="utf-8", errors="ignore").read()[-400:]})
    except Exception:
        pass
    return jsonify({"rules": rules, "scripts": scripts, "logs": logs,
                    "dir": AUTO_RULES})


@app.route("/api/auto/rule", methods=["POST"])
def api_auto_rule_add():
    """手工添加/更新一条规则。"""
    data = request.get_json(silent=True) or {}
    rules = _load_auto_rules()
    rid = data.get("id") or "r%d" % int(time.time())
    rec = {
        "id": rid, "name": data.get("name") or rid,
        "script": data.get("script") or "",
        "trigger": data.get("trigger") or {"type": "manual"},
        "enabled": bool(data.get("enabled", True)),
        "created": time.strftime("%Y-%m-%d %H:%M:%S"),
        "desc": data.get("desc") or "",
    }
    rules = [r for r in rules if r.get("id") != rid]
    rules.append(rec)
    _save_auto_rules(rules)
    return jsonify({"ok": True, "rules": rules})


@app.route("/api/auto/rule/<rid>", methods=["DELETE"])
def api_auto_rule_del(rid):
    rules = [r for r in _load_auto_rules() if r.get("id") != rid]
    _save_auto_rules(rules)
    return jsonify({"ok": True, "rules": rules})


@app.route("/api/auto/rule/<rid>/toggle", methods=["POST"])
def api_auto_rule_toggle(rid):
    rules = _load_auto_rules()
    for r in rules:
        if r.get("id") == rid:
            r["enabled"] = not r.get("enabled", True)
    _save_auto_rules(rules)
    return jsonify({"ok": True, "rules": rules})


@app.route("/api/auto/run/<rid>", methods=["POST"])
def api_auto_run(rid):
    """手动触发某条规则的脚本。"""
    rules = _load_auto_rules()
    rule = next((r for r in rules if r.get("id") == rid), None)
    if not rule or not rule.get("script"):
        return jsonify({"ok": False, "error": "规则或脚本不存在"})
    try:
        subprocess.Popen(["python3", rule["script"]], start_new_session=True,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return jsonify({"ok": True, "msg": f"已触发 {rule.get('name', rid)}"})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})


# ======================= AI 日程（~/.schedule） =======================
@app.route("/api/schedule", methods=["GET"])
def api_schedule_list():
    from schedule import load_schedule
    return jsonify({"items": load_schedule()})


@app.route("/api/schedule", methods=["POST"])
def api_schedule_add():
    from schedule import add_item, load_schedule
    data = request.get_json(silent=True) or {}
    it = add_item(data.get("title") or "未命名日程", data.get("task_prompt") or "",
                  data.get("condition") or {"type": "time", "when": ""},
                  bool(data.get("clarified", True)))
    return jsonify({"ok": True, "item": it, "items": load_schedule()})


@app.route("/api/schedule/<sid>", methods=["DELETE"])
def api_schedule_del(sid):
    from schedule import delete_item, load_schedule
    delete_item(sid)
    return jsonify({"ok": True, "items": load_schedule()})


@app.route("/api/schedule/<sid>/toggle", methods=["POST"])
def api_schedule_toggle(sid):
    from schedule import load_schedule, save_schedule
    items = load_schedule()
    for it in items:
        if it.get("id") == sid:
            it["status"] = "pending" if it.get("status") == "done" else "done"
    save_schedule(items)
    return jsonify({"ok": True, "items": load_schedule()})


@app.route("/api/schedule/<sid>/run", methods=["POST"])
def api_schedule_run(sid):
    """立即执行某条日程。"""
    from schedule import get_item, load_schedule, run_item
    it = get_item(sid)
    if not it:
        return jsonify({"ok": False, "error": "日程不存在"})
    res = run_item(it)
    return jsonify({"ok": res.get("ok"), "result": res.get("result"),
                    "items": load_schedule()})


# ======================= AI 记忆（习惯/职业/常用软件） =======================
@app.route("/api/memory", methods=["GET"])
def api_memory():
    """当前 AI 记忆 + 调度配置。"""
    cfg = load_config()
    return jsonify({
        "memory": tsai_ctx.load_memory(),
        "interval": cfg.get("memory_interval", "off"),
        "ctx_minutes": int(cfg.get("ctx_minutes", 10) or 10),
    })


@app.route("/api/memory/interval", methods=["POST"])
def api_memory_interval():
    """设置记忆自动循环间隔: off/daily/weekly/monthly/quarterly。"""
    data = request.get_json(silent=True) or {}
    iv = (data.get("interval") or "off").strip().lower()
    allowed = {"off", "daily", "weekly", "monthly", "quarterly"}
    if iv not in allowed:
        return jsonify({"ok": False, "error": "非法间隔"}), 400
    cfg = load_config()
    cfg["memory_interval"] = iv
    cfg["memory_last"] = cfg.get("memory_last") or ""
    save_config(cfg)
    return jsonify({"ok": True, "interval": iv})


@app.route("/api/memory/update", methods=["POST"])
def api_memory_update():
    """立即执行一次 AI 记忆更新（默认最近 7 天日志）。

    ai_gate 默认关（stubbed）：不真正调 AI，返回本地空记忆 + 提示。
    用户需在 ~/.activity/config.json 设 ai_enabled=true 才真更新。
    """
    data = request.get_json(silent=True) or {}
    minutes = int(data.get("minutes") or 60 * 24 * 7)
    out = ai_g.update_memory(minutes=minutes)
    cfg = load_config()
    cfg["memory_last"] = time.strftime("%Y-%m-%d %H:%M:%S")
    save_config(cfg)
    return jsonify({"ok": True, **out})


def _memory_scheduler():
    """后台线程：按 memory_interval 自动循环更新 AI 记忆。"""
    import datetime as _dt
    intervals = {
        "daily": lambda d: d + _dt.timedelta(days=1),
        "weekly": lambda d: d + _dt.timedelta(weeks=1),
        "monthly": lambda d: d + _dt.timedelta(days=30),
        "quarterly": lambda d: d + _dt.timedelta(days=91),
    }
    while True:
        try:
            cfg = load_config()
            iv = cfg.get("memory_interval", "off")
            if iv in intervals:
                last = cfg.get("memory_last") or ""
                due = False
                if not last:
                    due = True  # 从未更新过 → 立即执行一次
                else:
                    try:
                        ldt = _dt.datetime.strptime(last[:19], "%Y-%m-%d %H:%M:%S")
                        delta = intervals[iv](ldt) - ldt  # 距上次的期望间隔
                        due = (_dt.datetime.now() - ldt) >= delta
                    except Exception:
                        due = False
                if due:
                    try:
                        ai_g.update_memory(minutes=60 * 24 * 7)
                        c = load_config()
                        c["memory_last"] = time.strftime("%Y-%m-%d %H:%M:%S")
                        save_config(c)
                    except Exception:
                        pass
        except Exception:
            pass
        time.sleep(60)


def _start_memory_scheduler():
    global _MEMORY_SCHED_LOCK, _MEMORY_SCHED_NEXT
    with _MEMORY_SCHED_LOCK:
        if _MEMORY_SCHED_NEXT == 0.0:
            _MEMORY_SCHED_NEXT = 1.0
            threading.Thread(target=_memory_scheduler, daemon=True).start()
            print("[chinai3] memory scheduler started", flush=True)


_start_memory_scheduler()


@app.route("/")
def index():
    return render_template("index.html")


def _aim_current_engine():
    """读取 AIM 引擎（aim oc status）：opencode / openclaw。"""
    try:
        out = subprocess.run(["aim", "oc", "status"],
                             capture_output=True, text=True, timeout=10)
        name = out.stdout.strip()
        return name if name else "opencode"
    except Exception:
        return "opencode"


@app.route("/api/aim/engine", methods=["GET"])
def aim_engine():
    return jsonify({"engine": _aim_current_engine()})


@app.route("/api/aim/engine", methods=["POST"])
def aim_engine_switch():
    data = request.get_json(silent=True) or {}
    target = (data.get("target") or "").strip().lower()
    if target in ("opencode", "openclaw"):
        arg = "default" if target == "opencode" else "openclaw"
    else:
        # 无 target：aim oc 裸切换（toggle opencode<->openclaw）
        try:
            r = subprocess.run(["aim", "oc"], capture_output=True, text=True, timeout=15)
        except Exception as e:
            return jsonify({"ok": False, "error": str(e)})
        return jsonify({"ok": r.returncode == 0, "engine": _aim_current_engine(),
                        "msg": r.stdout.strip() or "已切换"})
    try:
        r = subprocess.run(["aim", "oc", arg], capture_output=True, text=True, timeout=15)
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})
    if r.returncode != 0:
        return jsonify({"ok": False, "error": r.stderr.strip() or "aim oc 失败"})
    return jsonify({"ok": True, "engine": _aim_current_engine(),
                    "msg": r.stdout.strip() or f"已切换到 {target}"})


def _generate_title(text):
    """用 AI 给新对话起标题（本地 Ollama 除外）。

    用一次性 opencode 会话生成，不干扰 aim 的当前会话状态。
    """
    cfg = load_config()
    if cfg.get("backend") == "ollama":
        return None
    text = (text or "").strip()[:500]
    if not text:
        return None
    prompt = ("请为以下对话内容起一个简短的中文标题（不超过10个字，"
              "直接输出标题本身，不要任何其他文字）：\n\n" + text)
    try:
        r = subprocess.run(
            ["opencode", "run", "--format", "json", prompt],
            capture_output=True, text=True, timeout=60,
        )
    except Exception:
        return None
    title = None
    for line in r.stdout.splitlines():
        try:
            ev = json.loads(line)
            if ev.get("type") == "text" and ev.get("part", {}).get("text"):
                title = ev["part"]["text"].strip()
        except Exception:
            continue
    if title:
        title = title.splitlines()[-1].strip().strip('"').strip()
        title = title[:20]
    return title or None


@app.route("/api/title", methods=["POST"])
def title():
    data = request.get_json(silent=True) or {}
    text = data.get("text") or ""
    return jsonify({"title": _generate_title(text)})


@app.route("/api/config", methods=["GET"])
def get_config():
    return jsonify(load_config())


@app.route("/api/config", methods=["POST"])
def set_config():
    cfg = load_config()
    data = request.get_json(silent=True) or {}
    for k, v in data.items():
        if k in cfg:
            cfg[k] = v
    save_config(cfg)
    return jsonify(cfg)


@app.route("/api/models", methods=["GET"])
def models():
    cfg = load_config()
    if request.args.get("backend"):
        cfg["backend"] = request.args["backend"]
    backend = make_backend(cfg)
    return jsonify({"models": backend.get_models()})


@app.route("/api/status", methods=["GET"])
def status():
    cfg = load_config()
    backend = make_backend(cfg)
    return jsonify({"status": backend.get_status()})


# ---------------- 截图 OCR（复刻 key） ----------------
def _ocr(path):
    try:
        r = subprocess.run(["tesseract", path, "-", "-l", "chi_sim+eng"],
                           capture_output=True, text=True, timeout=30)
        return (r.stdout or "").strip()
    except Exception:
        return ""


@app.route("/api/screenshot", methods=["POST"])
def api_screenshot():
    try:
        shot_dir = os.path.join(DATA_DIR, "shots")
        os.makedirs(shot_dir, exist_ok=True)
        ts = time.strftime("%Y%m%d-%H%M%S")
        path = os.path.join(shot_dir, f"shot-{ts}.png")
        subprocess.run(["gnome-screenshot", "-a", "-f", path], check=True, timeout=60)
        ocr = _ocr(path)
        return jsonify({"ok": True, "path": path, "ocr": ocr})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


# ---------------- 界面上下文（tine tree，复刻 key） ----------------
@app.route("/api/ctx-tine", methods=["POST"])
def api_ctx_tine():
    data = request.get_json(silent=True) or {}
    if data.get("clear"):
        with _lock:
            _ctx_tine["text"] = ""
            _ctx_tine["ts"] = 0
        return jsonify({"ok": True, "cleared": True})
    try:
        r = subprocess.run(["tine", "tree"], capture_output=True, text=True, timeout=25)
        text = (r.stdout or r.stderr or "").strip()
    except Exception as e:
        text = f"错误: {e}"
    with _lock:
        _ctx_tine["text"] = text
        _ctx_tine["ts"] = time.time()
    return jsonify({"ok": True, "text": text[:3000], "preview": text[:200], "len": len(text)})


@app.route("/api/ctx-tine/status")
def api_ctx_tine_status():
    with _lock:
        return jsonify({"has": bool(_ctx_tine["text"]), "len": len(_ctx_tine["text"]),
                        "preview": _ctx_tine["text"][:120]})


@app.route("/api/ctx-tine/peek", methods=["GET", "POST"])
def api_ctx_tine_peek():
    """send 时取用并清空（一次性前置）。"""
    with _lock:
        t = _ctx_tine["text"]
        _ctx_tine["text"] = ""
        _ctx_tine["ts"] = 0
    return jsonify({"ok": True, "text": t})


@app.route("/api/chat", methods=["POST"])
def chat():
    global _active_backend
    data = request.get_json(silent=True) or {}
    cfg = load_config()
    engine = data.get("engine") or cfg.get("engine", "chat")
    if engine not in ("chat", "key", "scr", "auto", "schedule"):
        engine = "chat"
    backend = make_backend(cfg, engine)
    with _lock:
        _active_backend = backend
    messages = data.get("messages", [])
    model = data.get("model", "")
    files = data.get("files") or []

    def generate():
        try:
            for chunk in backend.chat(messages, model, files=files):
                if not chunk:
                    continue
                yield chunk
        finally:
            backend.stop()
            global _active_backend
            with _lock:
                if _active_backend is backend:
                    _active_backend = None

    return Response(generate(), mimetype="text/plain; charset=utf-8")


@app.route("/api/reset", methods=["POST"])
def reset():
    """重置当前引擎的会话状态（新对话）。"""
    data = request.get_json(silent=True) or {}
    engine = data.get("engine") or load_config().get("engine", "chat")
    backend = get_engine_backend(engine, load_config())
    if backend is not None:
        backend.reset()
    return jsonify({"ok": True})


@app.route("/api/conversations", methods=["GET"])
def conversations():
    """列出 aim 全局会话历史（aim se）。"""
    try:
        out = subprocess.run(["aim", "se"], capture_output=True, timeout=10)
    except Exception as e:
        return jsonify({"error": str(e), "conversations": []})
    rows = []
    for line in out.stdout.decode("utf-8", errors="replace").splitlines():
        parts = line.split("\t")
        if parts and parts[0].strip().isdigit():
            rows.append({
                "num": int(parts[0].strip()),
                "time": parts[1].strip() if len(parts) > 1 else "",
                "engine": parts[2].strip() if len(parts) > 2 else "",
                "mode": parts[3].strip() if len(parts) > 3 else "",
                "prompt": parts[4].strip() if len(parts) > 4 else "",
            })
    return jsonify({"conversations": rows})


@app.route("/api/conversation/switch", methods=["POST"])
def conversation_switch():
    """aim change <num>：切换 aim run 继续的会话。"""
    data = request.get_json(silent=True) or {}
    num = data.get("num")
    try:
        r = subprocess.run(["aim", "change", str(num)], capture_output=True, text=True, timeout=15)
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})
    if r.returncode != 0:
        return jsonify({"ok": False, "error": r.stderr.strip() or "切换失败"})
    # 记录当前会话 id 到持久化后端（后续 --conv 实时计算编号）
    sid = _current_aim_session()
    cfg = load_config()
    backend = get_engine_backend(cfg.get("engine", "chat"), cfg)
    if backend is not None and hasattr(backend, "_session_id"):
        backend._session_id = sid
    return jsonify({"ok": True, "msg": (r.stdout.strip() or f"已切换到会话 {num}")})


@app.route("/api/conversation/switch-session", methods=["POST"])
def conversation_switch_session():
    """按 aim session id 切换（历史记录点击时自动延续对应 AIM 对话）。"""
    data = request.get_json(silent=True) or {}
    session = data.get("session")
    if not session:
        return jsonify({"ok": False, "error": "缺少 session"})
    if _session_to_rank(session) is None:
        return jsonify({"ok": False, "error": "找不到对应的 AIM 会话"})
    cfg = load_config()
    backend = get_engine_backend(cfg.get("engine", "chat"), cfg)
    if backend is not None and hasattr(backend, "_session_id"):
        backend._session_id = session
    return jsonify({"ok": True, "msg": "已切换到对应 AIM 会话"})


@app.route("/api/apps", methods=["GET"])
def apps():
    cfg = load_config()
    current = cfg.get("engine", "chat")
    result = []
    for aid, meta in AI_APPS.items():
        item = {"id": aid, "name": meta["name"], "icon": meta["icon"],
                "type": meta["type"], "desc": meta["desc"],
                "active": aid == current}
        result.append(item)
    return jsonify({"apps": result})


@app.route("/api/launch", methods=["POST"])
def launch():
    data = request.get_json(silent=True) or {}
    aid = data.get("app")
    if aid not in AI_APPS:
        return jsonify({"ok": False, "error": "未知应用"}), 404
    cmd = AI_APPS[aid]["cmd"]
    try:
        subprocess.Popen(
            cmd,
            start_new_session=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return jsonify({"ok": True, "name": AI_APPS[aid]["name"]})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/stop", methods=["POST"])
def stop():
    backend = get_active_backend()
    if backend is not None:
        backend.stop()
        return jsonify({"ok": True})
    return jsonify({"ok": False})


@app.route("/api/history", methods=["GET"])
def history():
    return jsonify(load_history())


@app.route("/api/history/add", methods=["POST"])
def history_add():
    data = request.get_json(silent=True) or {}
    title = (data.get("title") or "对话")[:40]
    msgs = data.get("messages") or []
    if not msgs:
        return jsonify({"ok": False, "error": "空对话"})
    rec_id = data.get("id")
    session = _current_aim_session()
    records = load_history()
    if rec_id:
        # 同 ID 会话实时更新（upsert），避免每轮插入重复记录
        for i, r in enumerate(records):
            if r.get("id") == rec_id:
                records[i] = {"id": rec_id, "title": title,
                              "time": time.strftime("%Y-%m-%d %H:%M:%S"),
                              "messages": msgs, "session": session}
                save_history(records[:MAX_HISTORY])
                return jsonify({"ok": True, "updated": True})
        record = {"id": rec_id, "title": title,
                  "time": time.strftime("%Y-%m-%d %H:%M:%S"),
                  "messages": msgs, "session": session}
        records.insert(0, record)
    else:
        record = {"id": int(time.time() * 1000), "title": title,
                  "time": time.strftime("%Y-%m-%d %H:%M:%S"),
                  "messages": msgs, "session": session}
        records.insert(0, record)
    save_history(records[:MAX_HISTORY])
    return jsonify({"ok": True})


@app.route("/api/history/delete", methods=["POST"])
def history_delete():
    data = request.get_json(silent=True) or {}
    ids = set(data.get("ids", []))
    records = [r for r in load_history() if r.get("id") not in ids]
    save_history(records)
    return jsonify({"ok": True})


@app.route("/api/history/clear", methods=["POST"])
def history_clear():
    save_history([])
    return jsonify({"ok": True})


# ======================= 朗读 TTS =======================
UPLOAD_DIR = os.path.join(DATA_DIR, "uploads")

_tts_proc = None
_tts_lock = threading.Lock()


@app.route("/api/tts", methods=["POST"])
def tts():
    global _tts_proc
    data = request.get_json(silent=True) or {}
    if data.get("stop"):
        with _tts_lock:
            proc = _tts_proc
            _tts_proc = None
        if proc is not None and proc.poll() is None:
            try:
                proc.kill()
            except Exception:
                pass
        return jsonify({"ok": True})
    text = (data.get("text") or "").strip()
    if not text:
        return jsonify({"ok": False, "error": "空文本"}), 400
    with _tts_lock:
        proc = _tts_proc
        if proc is not None and proc.poll() is None:
            try:
                proc.kill()
            except Exception:
                pass
        proc = subprocess.Popen(
            ["espeak-ng", "-v", "cmn", "-s", "155", "-g", "6", text],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        _tts_proc = proc
    return jsonify({"ok": True})


# ======================= 文件上传 =======================
@app.route("/api/upload", methods=["POST"])
def upload():
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    files = request.files.getlist("files")
    saved = []
    for f in files:
        if not f.filename:
            continue
        base = os.path.basename(f.filename)
        stem, ext = os.path.splitext(base)
        dest = os.path.join(UPLOAD_DIR, base)
        n = 1
        while os.path.exists(dest):
            dest = os.path.join(UPLOAD_DIR, f"{stem}_{n}{ext}")
            n += 1
        try:
            f.save(dest)
            saved.append({"name": os.path.basename(dest), "path": dest})
        except Exception:
            pass
    return jsonify({"ok": True, "files": saved})


# ======================= 系统 AI 应用 =======================
def _desktop_get(content, key):
    m = re.search(rf"^{re.escape(key)}\[zh_CN\]\s*=\s*(.+)$", content, re.M)
    if not m:
        m = re.search(rf"^{re.escape(key)}\s*=\s*(.+)$", content, re.M)
    return m.group(1).strip() if m else None


def _parse_exec(line):
    parts = shlex.split(line)
    args = [p for p in parts if not p.startswith("%")]
    if not args:
        return None
    i = 0
    if args[i] == "env":
        i += 1
        while i < len(args) and "=" in args[i] and not args[i].startswith("-"):
            i += 1
    return args[i:]


@app.route("/api/system-ai-apps", methods=["GET"])
def system_ai_apps():
    result = []
    seen = set()
    for f in glob.glob("/usr/share/applications/*.desktop"):
        try:
            with open(f, encoding="utf-8", errors="replace") as fh:
                content = fh.read()
            name = _desktop_get(content, "Name")
            comment = _desktop_get(content, "Comment") or ""
            exec_line = _desktop_get(content, "Exec") or ""
            if not name:
                continue
            low = name.lower()
            # 只按应用名匹配"AI"（避免注释里的 avail/detail 等误命中），排除 TSAI-* / Chinai 系列
            if "ai" not in low or low.startswith("tsai") or "chinai" in low:
                continue
            cmd = _parse_exec(exec_line)
            if not cmd:
                continue
            key = " ".join(cmd)
            if key in seen:
                continue
            seen.add(key)
            result.append({"name": name, "comment": comment, "cmd": cmd, "file": os.path.basename(f)})
        except Exception:
            continue
    return jsonify({"apps": result})


@app.route("/api/launch-sys", methods=["POST"])
def launch_sys():
    data = request.get_json(silent=True) or {}
    cmd = data.get("cmd")
    if not cmd or not isinstance(cmd, list):
        return jsonify({"ok": False, "error": "缺少命令"}), 400
    try:
        subprocess.Popen(cmd, start_new_session=True,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500
