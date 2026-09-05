"""AI 助手 — chindshell 套壳后端（Flask）。

完整复刻原版 GTK(key/ui.py+backend.py) 的交互：
- 流式对话（aim newrun/run），会话 ID 跟踪防串门
- 对话记录列表（aim se）、查看内容、切换会话继续聊
- 截图 + OCR（作为附件，随下条消息发给 AI）
- 界面上下文（tine tree，随下条消息自动前置）
- 附件上传（-f）
- IPC（--screenshot/--wake/--context）
历史保存：~/.ai-assistant/history.json（成对记录 engine+session，防串门）
"""
import json
import os
import re
import subprocess
import sys
import threading
import time

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
for p in (BASE_DIR, "/usr/chindows"):
    if p not in sys.path:
        sys.path.insert(0, p)

from flask import Flask, Response, jsonify, render_template, request  # noqa: E402

from chindshell import chat as chatmod  # noqa: E402
from chindshell import flask as csf  # noqa: E402

app = Flask(__name__)
csf.register(app)

DATA_DIR = os.path.join(os.path.expanduser("~"), ".ai-assistant")
HISTORY_PATH = os.path.join(DATA_DIR, "history.json")
UPLOAD_DIR = os.path.join(DATA_DIR, "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)

session = chatmod.StreamSession()
state = {"pending_newrun": True, "session_id": None, "ctx_text": ""}
tracker = chatmod.ConversationTracker(HISTORY_PATH)
_lock = threading.Lock()

_context_cache = {"text": "", "ts": 0}


def _aim_cmd(prompt, files, new, conv_rank=None):
    if new:
        cmd = ["aim", "newrun", prompt]
    elif conv_rank:
        cmd = ["aim", "run", "--conv", str(conv_rank), prompt]
    else:
        cmd = ["aim", "run", prompt]
    for f in files or []:
        cmd += ["-f", f]
    return cmd


def _capture_session_id():
    return chatmod.current_aim_session()


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/send", methods=["POST"])
def api_send():
    data = request.get_json(silent=True) or {}
    text = (data.get("text") or "").strip()
    files = data.get("files") or []
    if not text:
        return jsonify({"ok": False, "error": "消息为空"})

    new = bool(state["pending_newrun"])
    state["pending_newrun"] = False
    ctx = state["ctx_text"] or ""
    state["ctx_text"] = ""

    parts = []
    if ctx:
        parts.append("【界面上下文】\n" + ctx)
    for f in files:
        parts.append("【用户附件】" + f)
    parts.append(text)
    prompt = "\n\n".join(parts)
    tracker.add_user(prompt)

    conv_rank = None
    if not new and state["session_id"]:
        conv_rank = chatmod.aim_session_to_rank(state["session_id"])
        if conv_rank is None:
            new = True
    cmd = _aim_cmd(prompt, files, new, conv_rank)
    session.start(cmd)
    return jsonify({"ok": True, "new": new})


@app.route("/api/stream")
def api_stream():
    since = int(request.args.get("since", 0) or 0)
    chunks, done, error, total = session.poll(since)
    if done and error and not chunks:
        pass
    return jsonify({"chunks": "".join(chunks), "done": done, "error": error, "total": total})


@app.route("/api/stop", methods=["POST"])
def api_stop():
    session.stop()
    return jsonify({"ok": True})


@app.route("/api/newchat", methods=["POST"])
def api_newchat():
    session.stop()
    state["pending_newrun"] = True
    state["session_id"] = None
    state["ctx_text"] = ""
    tracker.save()
    return jsonify({"ok": True})


# ---------------- 对话记录（aim se）----------------
def _aim_se():
    try:
        r = subprocess.run(["aim", "se"], capture_output=True, timeout=20)
        text = r.stdout.decode("utf-8", errors="replace")
        rows = []
        for line in text.splitlines():
            parts = line.split("\t")
            if parts and parts[0].strip().isdigit():
                rows.append({
                    "num": int(parts[0].strip()),
                    "time": parts[1].strip() if len(parts) > 1 else "",
                    "engine": parts[2].strip() if len(parts) > 2 else "",
                    "command": parts[3].strip() if len(parts) > 3 else "",
                    "prompt": parts[4].strip() if len(parts) > 4 else "",
                })
        return rows
    except Exception:
        return []


@app.route("/api/conversations")
def api_conversations():
    return jsonify({"conversations": _aim_se()})


@app.route("/api/conversation/view", methods=["POST"])
def api_conversation_view():
    data = request.get_json(silent=True) or {}
    num = data.get("num")
    try:
        r = subprocess.run(["aim", "se", str(num)], capture_output=True, timeout=30)
        return jsonify({"ok": True, "text": r.stdout.decode("utf-8", errors="replace")})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/conversation/switch", methods=["POST"])
def api_conversation_switch():
    data = request.get_json(silent=True) or {}
    num = data.get("num")
    try:
        r = subprocess.run(["aim", "change", str(num)], capture_output=True, timeout=15)
        if r.returncode != 0:
            return jsonify({"ok": False, "error": r.stderr.decode() or "切换失败"}), 500
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500
    sid = _capture_session_id()
    with _lock:
        state["session_id"] = sid
        state["pending_newrun"] = False
    return jsonify({"ok": True, "session": sid, "msg": "已切换到对应 AIM 会话"})


@app.route("/api/conversation/load", methods=["POST"])
def api_conversation_load():
    """载入某历史/会话内容到当前对话列表继续聊（按 session 恢复）。"""
    data = request.get_json(silent=True) or {}
    session_id = data.get("session")
    if session_id:
        with _lock:
            state["session_id"] = session_id
            state["pending_newrun"] = False
        return jsonify({"ok": True, "session": session_id})
    return jsonify({"ok": False, "error": "缺少 session"}), 400


# ---------------- 截图 + OCR ----------------
def _ocr(path):
    try:
        r = subprocess.run(["tesseract", path, "-", "-l", "chi_sim+eng"],
                           capture_output=True, text=True, timeout=30)
        return (r.stdout or "").strip()
    except Exception:
        return ""


def _take_screenshot():
    try:
        os.makedirs(os.path.join(DATA_DIR, "shots"), exist_ok=True)
        ts = time.strftime("%Y%m%d-%H%M%S")
        path = os.path.join(DATA_DIR, "shots", f"shot-{ts}.png")
        subprocess.run(["gnome-screenshot", "-a", "-f", path], check=True, timeout=60)
        ocr = _ocr(path)
        return {"ok": True, "path": path, "ocr": ocr}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@app.route("/api/screenshot", methods=["POST"])
def api_screenshot():
    res = _take_screenshot()
    return jsonify(res)


# ---------------- 界面上下文（tine tree）----------------
@app.route("/api/context", methods=["POST"])
def api_context():
    """抓取界面上下文并缓存，随下一条消息自动前置；clear=1 时清空。"""
    data = request.get_json(silent=True) or {}
    if data.get("clear"):
        with _lock:
            state["ctx_text"] = ""
            _context_cache["text"] = ""
        return jsonify({"ok": True, "cleared": True})
    try:
        r = subprocess.run(["tine", "tree"], capture_output=True, text=True, timeout=25)
        text = (r.stdout or r.stderr or "").strip()
    except Exception as e:
        text = f"错误: {e}"
    with _lock:
        state["ctx_text"] = text
        _context_cache["text"] = text
        _context_cache["ts"] = time.time()
    return jsonify({"ok": True, "text": text[:3000], "preview": text[:200]})


@app.route("/api/context/status")
def api_context_status():
    with _lock:
        return jsonify({"has": bool(state["ctx_text"]),
                        "len": len(state["ctx_text"]),
                        "preview": state["ctx_text"][:120]})


# ---------------- 附件上传 ----------------
@app.route("/api/upload", methods=["POST"])
def api_upload():
    f = request.files.get("file")
    if not f or not f.filename:
        return jsonify({"ok": False, "error": "缺少文件"}), 400
    name = os.path.basename(f.filename)
    base, ext = os.path.splitext(name)
    path = os.path.join(UPLOAD_DIR, name)
    n = 1
    while os.path.exists(path):
        path = os.path.join(UPLOAD_DIR, f"{base}_{n}{ext}")
        n += 1
    f.save(path)
    return jsonify({"ok": True, "name": os.path.basename(path), "path": path})


# ---------------- 历史 ----------------
@app.route("/api/history")
def api_history():
    return jsonify(tracker.load())


@app.route("/api/history/switch", methods=["POST"])
def api_history_switch():
    data = request.get_json(silent=True) or {}
    record = data.get("record") or {}
    messages = record.get("messages") or []
    sid = record.get("session")
    if messages:
        tracker.messages = [{"role": m.get("role"), "content": m.get("content")}
                            for m in messages]
    if sid:
        with _lock:
            state["session_id"] = sid
            state["pending_newrun"] = False
        return jsonify({"ok": True, "session": sid, "messages": tracker.messages})
    return jsonify({"ok": True, "messages": tracker.messages})


@app.route("/api/history/clear", methods=["POST"])
def api_history_clear():
    tracker.clear()
    return jsonify({"ok": True})


# ---------------- IPC ----------------
import socket as _socket  # noqa: E402
from ipc import Server as _IPCServer  # noqa: E402

_notice = {"cmd": "", "text": ""}
_ipc_lock = threading.Lock()
# 主实例注入的唤醒回调（present 窗口）；未注入时退化为仅写 notice
_wake_cb = None


def set_wake_callback(cb):
    """由 key/main.py 主实例注入，wake 命令触发时回调（通常为 present 窗口）。"""
    global _wake_cb
    _wake_cb = cb


def _notify(cmd, text):
    with _ipc_lock:
        _notice["cmd"] = cmd
        _notice["text"] = text


def _handle_ipc(cmd):
    cmd = cmd.strip()
    if cmd == "screenshot":
        res = _take_screenshot()
        if res.get("ok"):
            _notify("screenshot", f"截图: {res['path']}\nOCR: {res.get('ocr') or '(无)'}")
        else:
            _notify("screenshot", f"截图失败: {res.get('error')}")
    elif cmd == "context":
        try:
            r = subprocess.run(["tine", "tree"], capture_output=True, text=True, timeout=25)
            text = (r.stdout or r.stderr or "").strip()
        except Exception as e:
            text = f"错误: {e}"
        with _lock:
            state["ctx_text"] = text
        _notify("context", text[:2000])
    elif cmd == "wake":
        if _wake_cb:
            try:
                _wake_cb()
            except Exception as e:
                print(f"[AI助手] 唤醒失败: {e}", flush=True)
        _notify("wake", "已唤醒")


def _start_ipc():
    try:
        srv = _IPCServer(_handle_ipc)
        if srv.start():
            print("[AI助手] IPC server started", flush=True)
    except Exception as e:
        print(f"[AI助手] IPC 启动失败: {e}", flush=True)


def start_ipc():
    """由主实例（key/main.py 后台常驻）显式调用，启动 IPC socket 服务。"""
    _start_ipc()


@app.route("/api/notice")
def api_notice():
    with _ipc_lock:
        n = {"cmd": _notice["cmd"], "text": _notice["text"]}
        _notice["cmd"] = ""
    return jsonify(n)
